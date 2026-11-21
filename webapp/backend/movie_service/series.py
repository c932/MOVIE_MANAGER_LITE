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
            return path, cached, False, ''
        existing = {part['tmdb_id']: part for part in cached.get('parts', [])}
        for part in updated:
            previous = existing.get(part['tmdb_id'], {})
            for field in ('rating', 'plot', 'poster_url', 'premiered', 'year'):
                if not part.get(field) and previous.get(field):
                    part[field] = previous[field]
        return path, {'anchor': anchor, 'parts': updated, 'fetched_at': time.time()}, True, ''

    catalogs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, result in enumerate(pool.map(collect, groups.items()), 1):
            catalogs.append(result)
            ctx.update(current=count, total=len(groups), stage='更新系列', message=f'正在更新系列片单（{count}/{len(groups)}）…')
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
    summary = (f'查询到 {len(groups)} 个本地系列，更新了 {changed} 个 TMDB 片单，'
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
            items.append({**part, 'movie_id': None, 'rating_source': 'tmdb'})
        else:
            matched.add(movie.nfo_path)
            items.append(_local_row(movie, poster_url=part['poster_url'], catalog_score=part['rating'],
                                    catalog_plot=part.get('plot', '')))
    items.extend(_local_row(movie) for movie in members if movie.nfo_path not in matched)
    items.sort(key=lambda row: (row['premiered'] or row['year'] or '9999', row['title']))
    return {'name': name, 'source': 'tmdb' if parts else 'local', 'items': items}


def _movie_order(movie: Movie) -> str:
    return movie.premiered or movie.year or '9999'


def _local_row(movie: Movie, *, poster_url: str = '', catalog_score: float = 0,
               catalog_plot: str = '') -> dict[str, Any]:
    rating, source = preferred_rating(movie)
    if not rating:
        rating = movie.ratings.get('themoviedb') or catalog_score
        source = 'tmdb'
    return {'movie_id': movie_id(movie.nfo_path), 'tmdb_id': movie.tmdb_id, 'title': movie.title,
            'original_title': movie.original_title, 'year': movie.year, 'premiered': movie.premiered,
            'rating': rating, 'rating_source': source, 'poster_url': poster_url, 'plot': movie.plot or catalog_plot}
