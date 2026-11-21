"""榜单更新时预存公开简介与海报，打开详情时直接读取。"""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import re
from urllib.parse import urlsplit

from models.movie import Movie
from scraper.douban_ranking import RankedMovie
from scraper.metadata_sources import ProviderError, TmdbProvider
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
    return {
        'plot': plot.strip() if isinstance(plot, str) else '',
        'poster_url': poster if isinstance(poster, str) and allowed_poster(poster) else '',
    }


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
    from .discovery import subject_detail
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
    normalize = lambda text: re.sub(r'[\W_]+', '', text.casefold())

    def fill(row: RankedMovie) -> tuple[bool, bool, bool]:
        ctx.check_cancelled()
        ident = row.douban_id
        old = prior.get(ident)
        movie = local.get(ident)
        cached = cached_browse(data_dir, ident)
        source = 'imdb' if row.source == 'imdb_top250' else 'douban'
        row.plot = row.plot or cached.get('plot') or (movie.plot if movie else '') or (old.plot if old else '')
        if not 0 < row.rating <= 10:
            row.rating = (old.rating if old else 0) or (movie.ratings.get(source, 0) if movie else 0)
        if source == 'imdb' and not 0 < row.rating <= 10 and re.fullmatch(r'tt\d+', ident):
            try:
                row.rating = imdb.rating(ident)[0] or 0
            except ProviderError:
                pass
        if not row.plot and source == 'douban' and ident.isdigit():
            try:
                row.plot = subject_detail(data_dir, ident, ctx=None)['plot']
            except (ValueError, OSError):
                pass
        urls = dict.fromkeys((cached.get('poster_url') or '', row.poster_url, old.poster_url if old else ''))
        poster = next((url for url in urls if _cache_poster(url, cover_dir)), '')
        if tmdb and (not row.plot or not poster):
            try:
                if source == 'imdb' or (movie and movie.tmdb_id):
                    candidates = tmdb.search(ident if source == 'imdb' else movie.tmdb_id)
                elif row.year and row.title:
                    title = normalize(row.title)
                    candidates = [m for m in tmdb.search(row.title, row.year) if m.year == row.year
                                  and title in (normalize(m.title), normalize(m.original_title))]
                else:
                    candidates = []
                if len(candidates) == 1:
                    candidate = candidates[0]
                    row.plot = row.plot or candidate.overview
                    alternate = candidate.poster_url.replace('/original/', '/w342/')
                    if not poster and _cache_poster(alternate, cover_dir):
                        poster = alternate
            except ProviderError:
                pass
        row.poster_url = poster or row.poster_url or (old.poster_url if old else '')
        return 0 < row.rating <= 10, bool(row.plot), bool(poster or (movie and movie.poster_path))

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
