"""榜单更新时预存公开简介与海报，打开详情时直接读取。"""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import re
import time
from threading import Event
from urllib.parse import urlsplit

from models.movie import Movie
from scraper.douban_ranking import RankedMovie
from scraper.metadata_sources import DoubanProvider, ProviderError, TmdbProvider
from scraper.public_sources import douban_public_search, tmdb_public_details, tmdb_public_search
from scraper.scrape_models import Candidate
from scraper.scrape_settings import ScrapeSettings
from utils.library_sync import atomic_json, read_json
from wall_common.images import ImageError, cached_remote
from wall_common.jobs import JobContext

IMAGE_PROXY_HOSTS = ('douban.com', 'doubanio.com', 'imdb.com', 'media-amazon.com', 'tmdb.org')


def allowed_poster(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and any(host == root or host.endswith('.' + root) for root in IMAGE_PROXY_HOSTS)


def cached_browse(data_dir: Path, identity: str) -> dict[str, str]:
    if not re.fullmatch(r'(?:tt)?\d{1,12}', identity or ''):
        return {}
    try:
        cached = read_json(data_dir / 'discovery' / f'subject-{identity}.json', {})
    except (OSError, ValueError):
        return {}
    if not isinstance(cached, dict):
        return {}
    plot = cached.get('plot')
    poster = cached.get('poster_url')
    result = {
        'plot': plot.strip() if isinstance(plot, str) else '',
        'poster_url': poster if isinstance(poster, str) and allowed_poster(poster) else '',
    }
    for key in ('title', 'original_title', 'year', 'premiered', 'imdb_id', 'tmdb_id', 'enrichment_note'):
        value = cached.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in ('genres', 'countries', 'directors'):
        value = cached.get(key)
        if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
            result[key] = value
    actors = cached.get('actors')
    if isinstance(actors, list):
        valid_actors = [{'name': str(item.get('name', '')).strip(), 'role': str(item.get('role', '')).strip(),
                         'thumb': str(item.get('thumb', '')).strip()}
                        for item in actors if isinstance(item, dict) and str(item.get('name', '')).strip()]
        if valid_actors:
            result['actors'] = valid_actors
    ratings = cached.get('ratings')
    if isinstance(ratings, dict):
        valid_ratings = {}
        for source in ('douban', 'imdb', 'tmdb'):
            try:
                score = float(ratings.get(source, 0))
            except (TypeError, ValueError):
                continue
            if 0 < score <= 10:
                valid_ratings[source] = score
        if valid_ratings:
            result['ratings'] = valid_ratings
    return result


def cached_plot(data_dir: Path, identity: str) -> str:
    return cached_browse(data_dir, identity).get('plot', '')


def _cache_poster(url: str, cover_dir: Path) -> bool:
    if not allowed_poster(url):
        return False
    try:
        cached_remote(url, cover_dir, ttl=float('inf'), timeout=6)
        return True
    except (OSError, ImageError):
        return False


def enrich_top250(data_dir: Path, cover_dir: Path, rows: list[RankedMovie], previous: list[RankedMovie],
                  library: list[Movie], settings: ScrapeSettings, ctx: JobContext) -> dict[str, int]:
    from scraper.imdb_ratings import ImdbRatings

    prior = {m.douban_id: m for m in previous if m.douban_id}
    local: dict[str, Movie] = {}
    for movie in library:
        douban = re.search(r'/subject/(\d+)', movie.douban_url or '')
        for identity in (movie.imdb_id, douban[1] if douban else ''):
            if identity:
                local.setdefault(identity, movie)
    network = replace(settings, timeout=min(settings.timeout, 8))
    tmdb = TmdbProvider(network) if settings.tmdb_api_key or settings.tmdb_token else None
    imdb = ImdbRatings(network)
    douban = DoubanProvider(network)
    direct_douban_failed = Event()
    normalize = lambda text: re.sub(r'[\W_]+', '', text.casefold())

    def metadata_fields(metadata, detail: dict) -> dict:
        fields = metadata.fields
        for key in ('title', 'original_title', 'year', 'premiered', 'plot'):
            if not detail.get(key) and fields.get(key):
                detail[key] = fields[key]
        for key in ('genres', 'countries', 'directors'):
            if not detail.get(key) and fields.get(key):
                detail[key] = fields[key]
        if not detail.get('actors') and fields.get('actors'):
            detail['actors'] = fields['actors']
        for detail_key, identity_key in (('imdb_id', 'imdb'), ('tmdb_id', 'tmdb')):
            if not detail.get(detail_key) and metadata.ids.get(identity_key):
                detail[detail_key] = metadata.ids[identity_key]
        if not detail.get('poster_url') and metadata.artwork:
            detail['poster_url'] = metadata.artwork[0].preview_url or metadata.artwork[0].url
        for source, score in metadata.ratings.items():
            if source in ('douban', 'imdb', 'tmdb') and 0 < score <= 10:
                detail.setdefault('ratings', {})[source] = score
        return detail

    def douban_by_title(title: str, year: str):
        if not title or not year:
            return None
        candidates = douban.search(title, year)
        title_key = normalize(title)
        matches = [candidate for candidate in candidates
                   if candidate.year == year and title_key in (normalize(candidate.title), normalize(candidate.original_title))]
        return matches[0] if len(matches) == 1 else None

    def fill(row: RankedMovie) -> tuple[bool, bool, bool]:
        ctx.check_cancelled()
        ident = row.douban_id
        old = prior.get(ident)
        movie = local.get(ident)
        detail = cached_browse(data_dir, ident)
        for key in ('genres', 'countries', 'directors'):
            if not detail.get(key) and getattr(row, key, None):
                detail[key] = list(getattr(row, key))
        if not detail.get('actors') and getattr(row, 'actors', None):
            detail['actors'] = [{'name': name, 'role': '', 'thumb': ''} for name in row.actors]
        if not detail.get('poster_url') and row.poster_url:
            detail['poster_url'] = row.poster_url
        source = 'imdb' if row.source == 'imdb_top250' else 'douban'
        detail.setdefault('ratings', {}).setdefault(source, float(row.rating or 0))
        if not 0 < detail['ratings'][source] <= 10:
            detail['ratings'].pop(source, None)
        row.plot = detail.get('plot') or row.plot or (movie.plot if movie else '') or (old.plot if old else '')
        if not row.plot and detail.get('plot'):
            row.plot = detail['plot']
        if not 0 < row.rating <= 10:
            row.rating = (old.rating if old else 0) or (movie.ratings.get(source, 0) if movie else 0)
        if source == 'imdb' and not 0 < row.rating <= 10 and re.fullmatch(r'tt\d+', ident):
            try:
                row.rating = imdb.rating(ident)[0] or 0
                if 0 < row.rating <= 10:
                    detail['ratings']['imdb'] = row.rating
            except ProviderError:
                pass

        douban_metadata = None
        needs_douban = not (detail.get('actors') and detail.get('genres')
                            and detail.get('plot') and detail['ratings'].get('douban'))
        if source == 'douban' and ident.isdigit() and needs_douban and not direct_douban_failed.is_set():
            try:
                douban_metadata = douban.by_id(ident)
                metadata_fields(douban_metadata, detail)
            except ProviderError:
                direct_douban_failed.set()
                pass
        elif source == 'imdb' and needs_douban and not direct_douban_failed.is_set():
            try:
                candidate = douban_by_title(row.title, row.year)
                if candidate:
                    douban_metadata = douban.details(candidate)
                    metadata_fields(douban_metadata, detail)
            except ProviderError:
                direct_douban_failed.set()
                pass

        if source == 'douban' and douban_metadata and not detail['ratings'].get('imdb') and detail.get('imdb_id'):
            try:
                score = imdb.rating(detail['imdb_id'])[0]
                if score and 0 < score <= 10:
                    detail['ratings']['imdb'] = score
            except ProviderError:
                pass
        row.plot = detail.get('plot') or row.plot

        if tmdb and (not detail['ratings'].get('tmdb') or not (detail.get('actors') and detail.get('genres'))):
            try:
                if source == 'imdb' and re.fullmatch(r'tt\d+', ident):
                    tmdb_id, score, _ = tmdb.rating_by_imdb(ident)
                    detail['tmdb_id'] = tmdb_id
                    if score and 0 < score <= 10:
                        detail['ratings']['tmdb'] = score
                    metadata_fields(tmdb.details(Candidate('tmdb', tmdb_id, row.title)), detail)
                elif detail.get('imdb_id'):
                    _, score, _ = tmdb.rating_by_imdb(detail['imdb_id'])
                    if score and 0 < score <= 10:
                        detail['ratings']['tmdb'] = score
            except ProviderError:
                pass

        public_douban = None
        if not (detail.get('actors') and detail.get('genres')
                and detail.get('plot') and detail['ratings'].get('douban')):
            public_douban = douban_public_search(row.title, row.year)
            if public_douban is None and '之' in row.title:
                public_douban = douban_public_search(row.title.split('之', 1)[0], row.year)
            if public_douban:
                detail['title'] = detail.get('title') or public_douban.title
                detail['original_title'] = detail.get('original_title') or public_douban.original_title
                detail['plot'] = detail.get('plot') or public_douban.plot
                detail['directors'] = detail.get('directors') or public_douban.directors
                detail['actors'] = detail.get('actors') or [
                    {'name': name, 'role': '', 'thumb': ''} for name in public_douban.actors
                ]
                detail['poster_url'] = detail.get('poster_url') or public_douban.poster_url
                if public_douban.subject_id:
                    detail['douban_id'] = public_douban.subject_id
                if 0 < public_douban.rating <= 10:
                    detail['ratings']['douban'] = public_douban.rating

        if not detail['ratings'].get('tmdb') or not (detail.get('genres') and detail.get('actors')):
            query = (public_douban.original_title if public_douban else '') or row.title
            public_tmdb_id = tmdb_public_search(query, row.year)
            if public_tmdb_id:
                public_tmdb = tmdb_public_details(public_tmdb_id)
                if public_tmdb:
                    detail['title'] = detail.get('title') or public_tmdb['title']
                    detail['original_title'] = detail.get('original_title') or public_tmdb['title']
                    detail['plot'] = detail.get('plot') or public_tmdb['plot']
                    detail['genres'] = detail.get('genres') or public_tmdb['genres']
                    detail['countries'] = detail.get('countries') or public_tmdb['countries']
                    detail['directors'] = detail.get('directors') or public_tmdb['directors']
                    detail['actors'] = detail.get('actors') or public_tmdb['actors']
                    detail['poster_url'] = detail.get('poster_url') or public_tmdb['poster_url']
                    detail['premiered'] = detail.get('premiered') or public_tmdb['premiered']
                    detail['imdb_id'] = detail.get('imdb_id') or public_tmdb['imdb_id']
                    detail['tmdb_id'] = detail.get('tmdb_id') or public_tmdb['tmdb_id']
                    if 0 < public_tmdb['tmdb_rating'] <= 10:
                        detail['ratings']['tmdb'] = public_tmdb['tmdb_rating']
                    if detail.get('imdb_id') and not detail['ratings'].get('imdb'):
                        try:
                            score = imdb.rating(detail['imdb_id'])[0]
                            if score and 0 < score <= 10:
                                detail['ratings']['imdb'] = score
                        except ProviderError:
                            pass
        row.plot = detail.get('plot') or row.plot

        urls = dict.fromkeys((detail.get('poster_url') or '', row.poster_url, old.poster_url if old else ''))
        poster = next((url for url in urls if _cache_poster(url, cover_dir)), '')
        if poster:
            detail['poster_url'] = poster
            row.poster_url = poster
        else:
            row.poster_url = row.poster_url or (old.poster_url if old else '')
        detail['plot'] = detail.get('plot') or row.plot
        detail['ratings'][source] = row.rating if 0 < row.rating <= 10 else detail['ratings'].get(source, 0)
        if not 0 < detail['ratings'].get(source, 0) <= 10:
            detail['ratings'].pop(source, None)
        missing_sources = [source for source in ('douban', 'imdb', 'tmdb')
                           if not 0 < detail['ratings'].get(source, 0) <= 10]
        if missing_sources or not (detail.get('actors') and detail.get('genres')):
            detail['enrichment_note'] = '部分跨来源资料暂不可用，已保留可用资料。'
        else:
            detail.pop('enrichment_note', None)
        detail['title'] = detail.get('title') or row.title
        detail['original_title'] = detail.get('original_title', '')
        detail['year'] = row.year
        detail['premiered'] = detail.get('premiered') or row.premiered
        detail['fetched_at'] = time.time()
        atomic_json(data_dir / 'discovery' / f'subject-{ident}.json', detail)
        return (any(0 < score <= 10 for score in detail['ratings'].values()),
                bool(detail.get('plot')), bool(poster or (movie and movie.poster_path)))

    stats = {'ratings': 0, 'plots': 0, 'posters': 0}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, flags in enumerate(pool.map(fill, rows), 1):
            for key, included in zip(stats, flags):
                stats[key] += included
            ctx.update(current=count, total=len(rows), stage='补齐榜单资料',
                       message=f'正在补齐评分、简介和海报（{count}/{len(rows)}）…')
    ctx.check_cancelled()
    return stats


def warm_browse(data_dir: Path, cover_dir: Path, rows: Iterable[dict[str, str]],
                ctx: JobContext | None = None) -> dict[str, int]:
    """Deduplicate metadata and poster URLs across titles and preserve prior successes."""
    from .discovery import subject_detail

    posters = set()
    subjects = {}
    for row in rows:
        identity = row.get('douban_id') or row.get('imdb_id') or ''
        alternate = cached_browse(data_dir, identity).get('poster_url') if identity.startswith('tt') else ''
        url = alternate or row.get('poster_url') or ''
        if allowed_poster(url):
            posters.add(url)
        if re.fullmatch(r'(?:tt)?\d{1,12}', identity) and (identity.isdigit() or row.get('plot')):
            subjects[identity] = row.get('plot') or subjects.get(identity, '')

    def poster(url: str) -> bool:
        if ctx:
            ctx.check_cancelled()
        return _cache_poster(url, cover_dir)

    def subject(item: tuple[str, str]) -> bool:
        if ctx:
            ctx.check_cancelled()
        identity, plot = item
        try:
            if cached_plot(data_dir, identity):
                return True
            if plot:
                atomic_json(data_dir / 'discovery' / f'subject-{identity}.json', {'plot': plot})
            else:
                subject_detail(data_dir, identity, ctx=None)
            return True
        except (OSError, ValueError):
            return False

    if ctx:
        ctx.update(stage='预存资料', message='正在预存榜单海报和简介…')
    with ThreadPoolExecutor(max_workers=6) as pool:
        covers = pool.map(poster, sorted(posters))
        plots = pool.map(subject, subjects.items())
        result = {'posters': sum(covers), 'plots': sum(plots), 'poster_total': len(posters), 'plot_total': len(subjects)}
    if ctx:
        ctx.check_cancelled()
    return result
