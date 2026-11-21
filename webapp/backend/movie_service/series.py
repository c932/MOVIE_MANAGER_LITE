"""TMDB 系列片单缓存，以及与当前本地库的只读合并。"""
from dataclasses import replace
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
from .store import movie_id


def series_listing(data_dir: Path, name: str, members: list[Movie], library: list[Movie],
                   settings: ScrapeSettings) -> dict[str, Any]:
    anchors = list(dict.fromkeys(movie.tmdb_id for movie in sorted(members, key=_movie_order)
                                if re.fullmatch(r'[1-9]\d*', movie.tmdb_id or '')))
    path = data_dir / 'series_collections' / (sha256(name.encode()).hexdigest() + '.json')
    try:
        cached = read_json(path, {})
    except (OSError, ValueError):
        cached = {}
    if not isinstance(cached, dict) or cached.get('anchor') not in anchors:
        cached = {}
    parts = cached.get('parts') or []
    fetched_at = cached.get('fetched_at', 0)
    if (settings.tmdb_api_key or settings.tmdb_token) and time.time() - fetched_at >= 7 * 86400:
        provider = TmdbProvider(replace(settings, timeout=min(settings.timeout, 5)))
        for anchor in anchors[:3]:
            try:
                updated = provider.movie_collection(anchor)
            except ProviderError:
                break
            if updated:
                parts = updated
                try:
                    atomic_json(path, {'anchor': anchor, 'parts': parts, 'fetched_at': time.time()})
                except OSError:
                    pass  # 已取得的片单仍可显示。
                break

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
            items.append({**part, 'movie_id': None})
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
    rating, _ = preferred_rating(movie)
    if not rating:
        rating = movie.ratings.get('themoviedb') or catalog_score
    return {'movie_id': movie_id(movie.nfo_path), 'tmdb_id': movie.tmdb_id, 'title': movie.title,
            'original_title': movie.original_title, 'year': movie.year, 'premiered': movie.premiered,
            'rating': rating, 'poster_url': poster_url, 'plot': movie.plot or catalog_plot}
