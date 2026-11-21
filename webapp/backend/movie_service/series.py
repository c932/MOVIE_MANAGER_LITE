"""TMDB 系列片单缓存，以及与当前本地库的只读合并。"""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import re
import time
from typing import Any

from models.movie import Movie
from scraper.metadata_sources import ProviderError, TmdbProvider
from scraper.imdb_ratings import ImdbRatings
from scraper.public_sources import douban_public_search, tmdb_public_details
from scraper.scrape_settings import ScrapeSettings
from utils.genres import preferred_rating
from utils.library_sync import atomic_json, read_json
from wall_common.jobs import JobContext
from .browse_cache import warm_browse
from .store import MovieStore, movie_id


def group_series(library: list[Movie]) -> dict[str, list[Movie]]:
    groups: dict[str, list[Movie]] = {}
    for movie in library:
        if movie.set_name:
            groups.setdefault(movie.set_name, []).append(movie)
    return groups


def _collection_cache(data_dir: Path, name: str, members: list[Movie]) -> tuple[Path, list[str], dict]:
    anchors = list(dict.fromkeys(movie.tmdb_id for movie in sorted(members, key=_movie_order)
                                if re.fullmatch(r'[1-9]\d*', movie.tmdb_id or '')))
    path = data_dir / 'series_collections' / (sha256(name.encode()).hexdigest() + '.json')
    try:
        cached = read_json(path, {})
    except (OSError, ValueError):
        cached = {}
    if not isinstance(cached, dict) or cached.get('anchor') not in anchors:
        cached = {}
    return path, anchors, cached


def refresh_series(store: MovieStore, settings: ScrapeSettings, ctx: JobContext) -> dict:
    groups = group_series(store.snapshot())
    configured = bool(settings.tmdb_api_key or settings.tmdb_token)
    provider = TmdbProvider(replace(settings, timeout=min(settings.timeout, 8))) if configured else None
    imdb = ImdbRatings(replace(settings, timeout=min(settings.timeout, 10)))
    owned_tmdb_ids = {movie.tmdb_id for movie in store.snapshot() if movie.tmdb_id}

    def preferred_plot(current: str, candidate: str) -> str:
        if not candidate:
            return current
        if not current:
            return candidate
        candidate_chinese = bool(re.search(r"[\u4e00-\u9fff]", candidate))
        current_chinese = bool(re.search(r"[\u4e00-\u9fff]", current))
        if candidate_chinese and not current_chinese:
            return candidate
        if candidate_chinese == current_chinese and len(candidate) > len(current):
            return candidate
        return current

    def enrich_part(part: dict[str, Any]) -> dict[str, Any]:
        ctx.check_cancelled()
        detail = dict(part)
        detail.setdefault('ratings', {})
        try:
            public_tmdb = tmdb_public_details(str(part.get('tmdb_id') or ''))
            if public_tmdb:
                for key in ('title', 'original_title', 'premiered', 'poster_url', 'imdb_id', 'tmdb_id'):
                    if public_tmdb.get(key) and not detail.get(key):
                        detail[key] = public_tmdb[key]
                for key in ('genres', 'countries', 'directors'):
                    if public_tmdb.get(key) and not detail.get(key):
                        detail[key] = public_tmdb[key]
                if public_tmdb.get('actors') and not detail.get('actors'):
                    detail['actors'] = public_tmdb['actors']
                detail['plot'] = preferred_plot(detail.get('plot', ''), public_tmdb.get('plot', ''))
                if 0 < public_tmdb.get('tmdb_rating', 0) <= 10:
                    detail['ratings']['tmdb'] = public_tmdb['tmdb_rating']
        except OSError:
            pass
        try:
            public_douban = douban_public_search(part.get('title', ''), part.get('year', ''))
            if public_douban is None and '之' in part.get('title', ''):
                public_douban = douban_public_search(part['title'].split('之', 1)[0], part.get('year', ''))
            if public_douban:
                if public_douban.original_title and not detail.get('original_title'):
                    detail['original_title'] = public_douban.original_title
                if public_douban.directors and not detail.get('directors'):
                    detail['directors'] = public_douban.directors
                if public_douban.actors and not detail.get('actors'):
                    detail['actors'] = [{'name': name, 'role': '', 'thumb': ''} for name in public_douban.actors]
                if public_douban.poster_url and not detail.get('poster_url'):
                    detail['poster_url'] = public_douban.poster_url
                if public_douban.subject_id:
                    detail['douban_id'] = public_douban.subject_id
                detail['plot'] = preferred_plot(detail.get('plot', ''), public_douban.plot)
                if 0 < public_douban.rating <= 10:
                    detail['ratings']['douban'] = public_douban.rating
        except OSError:
            pass
        if detail.get('imdb_id') and not detail['ratings'].get('imdb'):
            try:
                score = imdb.rating(detail['imdb_id'])[0]
                if score and 0 < score <= 10:
                    detail['ratings']['imdb'] = score
            except ProviderError:
                pass
        return detail

    def collect(item: tuple[str, list[Movie]]) -> tuple[Path, dict, bool, str]:
        ctx.check_cancelled()
        name, members = item
        path, anchors, cached = _collection_cache(store.settings.data_dir, name, members)
        updated = []
        if provider:
            failure = False
            for anchor in anchors[:3]:
                try:
                    updated = provider.movie_collection(anchor, fill_missing=True)
                except ProviderError:
                    failure = True
                    continue
                if updated:
                    break
            if not updated and failure:
                return path, cached, False, 'failed'
        if not updated:
            return path, cached, bool(cached.get('parts', [])), ''
        existing = {part['tmdb_id']: part for part in cached.get('parts', [])}
        for index, part in enumerate(updated):
            previous = existing.get(part['tmdb_id'], {})
            for field in ('rating', 'plot', 'poster_url', 'premiered', 'year', 'original_title',
                          'genres', 'countries', 'directors', 'actors', 'douban_id', 'imdb_id', 'ratings'):
                if not part.get(field) and previous.get(field):
                    part[field] = previous[field]
        return path, {'anchor': anchor, 'parts': updated, 'fetched_at': time.time()}, True, ''

    catalogs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, result in enumerate(pool.map(collect, groups.items()), 1):
            catalogs.append(result)
            ctx.update(current=count, total=len(groups), stage='更新系列', message=f'正在更新系列片单（{count}/{len(groups)}）…')
    unowned_parts = [part for _, catalog, _, _ in catalogs
                     for part in catalog.get('parts', []) if part.get('tmdb_id') not in owned_tmdb_ids]
    ctx.update(stage='补齐系列资料', message=f'正在补齐 {len(unowned_parts)} 部未入库系列电影…')
    with ThreadPoolExecutor(max_workers=12) as pool:
        enriched_parts = list(pool.map(enrich_part, unowned_parts))
    enriched_by_id = {part['tmdb_id']: part for part in enriched_parts}
    for _, catalog, _, _ in catalogs:
        catalog['parts'] = [enriched_by_id.get(part.get('tmdb_id'), part)
                            for part in catalog.get('parts', [])]
    coverage = warm_browse(store.settings.data_dir, store.settings.cover_cache_dir,
                          (part for _, catalog, _, _ in catalogs for part in catalog.get('parts', [])), ctx)
    ctx.check_cancelled()
    changed = 0
    failed = 0
    for path, catalog, updated, error in catalogs:
        if updated:
            atomic_json(path, catalog)
            changed += 1
        failed += error == 'failed'
    summary = (f'查询到 {len(groups)} 个本地系列，补齐 {changed} 个系列资料，'
               f'已缓存 {coverage["posters"]} 张片单海报。')
    if not configured:
        summary += 'NUC 尚未配置 TMDB，已读取本地系列并补存已有片单的海报。'
    elif failed:
        summary += f'{failed} 个系列暂未更新，已保留上次的片单。'
    return {'updated': changed, 'failed': failed, 'settings_required': not configured,
            'cached_posters': coverage['posters'], 'summary': summary}


def series_listing(data_dir: Path, name: str, members: list[Movie], library: list[Movie]) -> dict[str, Any]:
    _, _, cached = _collection_cache(data_dir, name, members)
    parts = cached.get('parts') or []

    # 同一影片可能有多个文件，优先匹配当前系列的版本，同时保留额外的库内版本。
    by_tmdb: dict[str, Movie] = {}
    for movie in (*members, *library):
        if movie.tmdb_id:
            by_tmdb.setdefault(movie.tmdb_id, movie)
    items = []
    matched = set()
    for part in {item['tmdb_id']: item for item in parts}.values():
        movie = by_tmdb.get(part['tmdb_id'])
        if movie is None:
            items.append({**part, 'movie_id': None, 'set_name': name,
                          'rating_source': part.get('rating_source', 'tmdb')})
        else:
            matched.add(movie.nfo_path)
            items.append(_local_row(movie, part=part))
    items.extend(_local_row(movie, part={}) for movie in members if movie.nfo_path not in matched)
    items.sort(key=lambda row: (row['premiered'] or row['year'] or '9999', row['title']))
    return {'name': name, 'source': 'tmdb' if parts else 'local', 'items': items}


def _movie_order(movie: Movie) -> str:
    return movie.premiered or movie.year or '9999'


def _local_row(movie: Movie, *, part: dict[str, Any]) -> dict[str, Any]:
    rating, source = preferred_rating(movie)
    if not rating:
        rating = movie.ratings.get('themoviedb') or part.get('rating', 0)
        source = 'tmdb'
    result = {'movie_id': movie_id(movie.nfo_path), 'tmdb_id': movie.tmdb_id, 'title': movie.title,
              'original_title': movie.original_title, 'year': movie.year, 'premiered': movie.premiered,
              'rating': rating, 'rating_source': source,
              'poster_url': part.get('poster_url', ''), 'plot': movie.plot or part.get('plot', ''),
              'set_name': movie.set_name}
    for key in ('genres', 'countries', 'directors', 'actors', 'ratings', 'douban_id', 'imdb_id'):
        if part.get(key) and not result.get(key):
            result[key] = part[key]
    return result
