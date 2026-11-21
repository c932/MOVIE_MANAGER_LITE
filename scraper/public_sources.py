"""Public search/detail fallbacks used when configured provider APIs are unavailable."""
from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class PublicMovie:
    title: str
    original_title: str
    year: str
    rating: float
    votes: int
    plot: str
    poster_url: str
    subject_id: str
    directors: list[str]
    actors: list[str]


def fetch_text(url: str, *, timeout: int = 15) -> str:
    result = subprocess.run(
        [
            "curl", "-L", "-sS", "--max-time", str(timeout),
            "-A", USER_AGENT,
            "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
            url,
        ],
        capture_output=True,
        timeout=timeout + 5,
        check=True,
    )
    return result.stdout[:3 * 1024 * 1024].decode("utf-8", "replace")


def _clean(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def douban_public_search(query: str, year: str) -> PublicMovie | None:
    """Search Douban through Jina Reader and parse the first matching movie card."""
    if not query.strip():
        return None
    url = "https://r.jina.ai/http://www.douban.com/search?cat=1002&q=" + quote(query)
    try:
        text = fetch_text(url)
    except OSError:
        return None
    query_key = re.sub(r"[\W_]+", "", query.casefold())
    matches: list[PublicMovie] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        header = re.match(r"### \[电影\]\[(?P<title>[^\]]+)\]\((?P<link>[^)]+)\)", line)
        if not header:
            continue
        meta_index = next((position for position, value in enumerate(lines[index + 1:], index + 1) if value.strip()), None)
        meta_line = lines[meta_index] if meta_index is not None else ""
        plot_index = (next((position for position, value in enumerate(lines[meta_index + 1:], meta_index + 1) if value.strip()), None)
                      if meta_index is not None else None)
        plot_line = lines[plot_index] if plot_index is not None else ""
        poster = ""
        for previous in reversed(lines[max(0, index - 4):index]):
            image = re.search(r"\((https?://[^)]+)\)", previous)
            if image:
                poster = image.group(1)
                break
        meta = re.search(
            r"(?P<rating>\d+(?:\.\d+)?)\((?P<votes>\d+)人评价\)"
            r"(?:可播放)?原名:(?P<original>.*?) / (?P<people>.*?) / (?P<year>\d{4})",
            meta_line,
        )
        if not meta:
            continue
        subject = re.search(r"movie\.douban\.com%2Fsubject%2F(\d+)", header.group("link"))
        people = [name.strip() for name in meta.group("people").split("/") if name.strip()]
        movie = PublicMovie(
            title=_clean(header.group("title")),
            original_title=_clean(meta.group("original")),
            year=meta.group("year"),
            rating=float(meta.group("rating")),
            votes=int(meta.group("votes")),
            plot=_clean(plot_line),
            poster_url=poster,
            subject_id=subject.group(1) if subject else "",
            directors=people[:1],
            actors=people[1:],
        )
        matches.append(movie)
        title_key = re.sub(r"[\W_]+", "", movie.title.casefold())
        original_key = re.sub(r"[\W_]+", "", movie.original_title.casefold())
        if movie.year == year and query_key in (title_key, original_key):
            return movie
    year_matches = [movie for movie in matches if movie.year == year]
    return (year_matches or matches or [None])[0]


def tmdb_public_search(query: str, year: str) -> str:
    """Return the first TMDB movie ID whose public search result matches the year."""
    if not query.strip():
        return ""
    url = "https://www.themoviedb.org/search?query=" + quote(query) + "&language=zh-CN"
    try:
        text = fetch_text(url)
    except OSError:
        return ""
    pattern = re.compile(
        r'<a[^>]+href="/movie/(?P<id>\d+)[^"]*".*?'
        r'<h2[^>]*>.*?<span>(?P<title>[^<]+)</span>.*?'
        r'<span class="release_date[^"]*">(?P<date>[^<]+)</span>',
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        if year and year not in match.group("date"):
            continue
        return match.group("id")
    first = re.search(r'href="/movie/(\d+)', text)
    return first.group(1) if first else ""


def tmdb_public_details(movie_id: str) -> dict[str, Any]:
    """Parse the Movie JSON-LD on TMDB's public page."""
    if not re.fullmatch(r"[1-9]\d*", movie_id):
        return {}
    try:
        text = fetch_text(f"https://www.themoviedb.org/movie/{movie_id}?language=zh-CN")
    except OSError:
        return {}
    for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', text, re.DOTALL):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if data.get("@type") != "Movie":
            continue
        rating = data.get("aggregateRating") or {}
        same_as = data.get("sameAs")
        if isinstance(same_as, str):
            same_as = [same_as]
        imdb_id = next((re.search(r"/title/(tt\d+)", value).group(1)
                        for value in same_as or [] if re.search(r"/title/(tt\d+)", value)), "")
        countries = data.get("countryOfOrigin") or []
        if isinstance(countries, dict):
            countries = [countries]
        return {
            "tmdb_id": movie_id,
            "title": _clean(data.get("name", "")),
            "plot": _clean(data.get("description", "")),
            "premiered": _clean(data.get("datePublished", "")),
            "year": _clean(data.get("datePublished", ""))[:4],
            "genres": [_clean(item) for item in data.get("genre", []) if _clean(item)],
            "countries": [_clean(item.get("name", "")) for item in countries if isinstance(item, dict)],
            "directors": [_clean(item.get("name", "")) for item in data.get("director", []) if isinstance(item, dict)],
            "actors": [{"name": _clean(item.get("name", "")), "role": "", "thumb": ""}
                       for item in data.get("actor", []) if isinstance(item, dict) and _clean(item.get("name", ""))],
            "poster_url": data.get("image", ""),
            "imdb_id": imdb_id,
            "tmdb_rating": float(rating.get("ratingValue") or 0),
            "tmdb_votes": int(rating.get("ratingCount") or 0),
        }
    return {}
