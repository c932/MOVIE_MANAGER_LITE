"""榜单更新时预存公开简介与海报，打开详情时直接读取。"""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable
from pathlib import Path
import re
from urllib.parse import urlsplit

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


def cached_plot(data_dir: Path, identity: str) -> str:
    if not re.fullmatch(r'(?:tt)?\d{1,12}', identity or ''):
        return ''
    try:
        cached = read_json(data_dir / 'discovery' / f'subject-{identity}.json', {})
        plot = cached.get('plot') if isinstance(cached, dict) else None
        return plot.strip() if isinstance(plot, str) else ''
    except (OSError, ValueError):
        return ''


def warm_browse(data_dir: Path, cover_dir: Path, rows: Iterable[dict[str, str]],
                ctx: JobContext | None = None) -> dict[str, int]:
    """Deduplicate metadata and poster URLs across titles and preserve prior successes."""
    from .discovery import subject_detail

    posters = set()
    subjects = {}
    for row in rows:
        url = row.get('poster_url') or ''
        if allowed_poster(url):
            posters.add(url)
        identity = row.get('douban_id') or row.get('imdb_id') or ''
        if re.fullmatch(r'(?:tt)?\d{1,12}', identity) and (identity.isdigit() or row.get('plot')):
            subjects[identity] = row.get('plot') or subjects.get(identity, '')

    def poster(url: str) -> bool:
        if ctx:
            ctx.check_cancelled()
        try:
            cached_remote(url, cover_dir, ttl=float('inf'), timeout=6)
            return True
        except (OSError, ImageError):
            return False

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
