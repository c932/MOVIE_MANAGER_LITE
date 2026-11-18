"""
最新电影检查模块

通过 douban-cli 获取正在热映和即将上映的电影，与本地库对比，
识别本地缺失的新片并给出补充建议。支持本地缓存，避免重复获取详情。
"""
import json
import logging
import re
import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional


logger = logging.getLogger(__name__)


@dataclass
class NewMovie:
    """新片信息"""
    title: str
    year: str
    rating: float
    douban_id: str
    status: str  # "nowplaying" | "coming"
    genres: List[str] = field(default_factory=list)
    poster_url: str = ""
    premiered: str = ""  # 完整上映日期，如 "2025-11-27"


# ─────────────────── 序列化 ───────────────────

def _movie_to_dict(m: NewMovie) -> dict:
    return {
        "title": m.title, "year": m.year, "rating": m.rating,
        "douban_id": m.douban_id, "status": m.status,
        "genres": m.genres, "poster_url": m.poster_url,
        "premiered": m.premiered,
    }


def _dict_to_movie(d: dict) -> NewMovie:
    return NewMovie(
        title=d.get("title", ""), year=d.get("year", ""),
        rating=float(d.get("rating", 0) or 0), douban_id=d.get("douban_id", ""),
        status=d.get("status", "nowplaying"),
        genres=d.get("genres", []), poster_url=d.get("poster_url", ""),
        premiered=d.get("premiered", ""),
    )


# ─────────────────── 缓存管理 ───────────────────

_CACHE_PATH: Optional[Path] = None


def _get_cache_path(cache_path: Optional[Path] = None) -> Path:
    """获取新片缓存文件路径（cache_path 显式指定时优先，供多数据目录的网页版使用）"""
    if cache_path is not None:
        return Path(cache_path)
    global _CACHE_PATH
    if _CACHE_PATH is None:
        from utils.app_paths import resolve_data_file
        _CACHE_PATH = resolve_data_file("new_movie_cache.json")
    return _CACHE_PATH


def save_new_movie_cache(nowplaying: List[NewMovie], coming: List[NewMovie], *,
                         cache_path: Optional[Path] = None) -> bool:
    """保存新片数据到本地缓存"""
    try:
        from datetime import datetime
        path = _get_cache_path(cache_path)
        data = {
            "timestamp": datetime.now().isoformat(),
            "nowplaying": [_movie_to_dict(m) for m in nowplaying],
            "coming": [_movie_to_dict(m) for m in coming],
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"新片缓存已保存: 热映 {len(nowplaying)} 部, 即将上映 {len(coming)} 部 -> {path}")
        return True
    except Exception as e:
        logger.error(f"保存新片缓存失败: {e}")
        return False


def load_new_movie_cache(cache_path: Optional[Path] = None) -> Tuple[List[NewMovie], List[NewMovie]]:
    """从本地缓存加载新片数据，失败返回空列表"""
    try:
        path = _get_cache_path(cache_path)
        if not path.exists():
            return [], []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        nowplaying = [_dict_to_movie(d) for d in data.get('nowplaying', [])]
        coming = [_dict_to_movie(d) for d in data.get('coming', [])]
        logger.info(f"从缓存加载新片: 热映 {len(nowplaying)} 部, 即将上映 {len(coming)} 部")
        return nowplaying, coming
    except Exception as e:
        logger.error(f"加载新片缓存失败: {e}")
        return [], []


# ─────────────────── 抓取函数（douban-cli）───────────────────

def _run_cli(*args: str, timeout: int = 30) -> Optional[list | dict]:
    """复用 douban_cli 的 douban-cli 调用"""
    from scraper.douban_cli import run_douban_cli
    return run_douban_cli(*args, timeout=timeout)


def _parse_cinema_posters(page: str) -> dict:
    """从豆瓣城市电影页面解析条目 ID 与海报。"""
    return {
        douban_id: html.unescape(cover_url)
        for douban_id, cover_url in re.findall(
            r'<div class="item mod[^"]*">\s*'
            r'<a class="thumb" href="https://movie\.douban\.com/subject/(\d+)/">\s*'
            r'<img src="([^"]+)"',
            page,
            re.DOTALL,
        )
    }


def _fetch_cinema_posters(segment: str) -> dict:
    from scraper.douban_ranking import _fetch_url
    page = _fetch_url(f'https://movie.douban.com/cinema/{segment}/shanghai/')
    return _parse_cinema_posters(page)


def fetch_nowplaying(cached_movies: List[NewMovie] = None) -> List[NewMovie]:
    """
    获取豆瓣正在热映电影列表

    数据源：douban-cli now --json
    保持豆瓣页面顺序与条目，包括暂无评分电影。

    cached_movies: 缓存中已有的电影列表，用于跳过详情获取（增量更新）
    """
    data = _run_cli("now", "--limit", "50", timeout=30)
    if not data or not isinstance(data, list):
        logger.error("douban-cli now 返回数据为空")
        return []

    cached_lookup = {
        m.douban_id: m for m in (cached_movies or []) if m.douban_id
    }

    movies: List[NewMovie] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        douban_id = str(item.get("id", ""))
        title = str(item.get("title", "")).strip()
        if not title or not douban_id:
            continue

        try:
            rating = float(item.get("rating", item.get("score", 0)) or 0)
        except (ValueError, TypeError):
            rating = 0.0

        cached = cached_lookup.get(douban_id)
        meta_parts = [part.strip() for part in str(item.get("meta", "")).split(" / ")]
        year = meta_parts[0][:4] if meta_parts and re.match(r"^\d{4}$", meta_parts[0][:4]) else (cached.year if cached else "")
        genres = meta_parts[2].split() if len(meta_parts) > 2 and meta_parts[2] else (cached.genres if cached else [])
        premiered = _parse_release_date(str(item.get("release_date", "")), year)

        movies.append(NewMovie(
            title=title,
            year=year,
            rating=rating,
            douban_id=douban_id,
            status='nowplaying',
            genres=genres,
            premiered=premiered,
            poster_url=str(item.get("cover", "") or (cached.poster_url if cached else "")),
        ))

    logger.info(f"正在热映: 获取 {len(movies)} 部电影")
    return movies


def fetch_coming_soon(cached_movies: List[NewMovie] = None) -> List[NewMovie]:
    """
    获取豆瓣即将上映电影列表

    数据源：douban-cli coming --json

    cached_movies: 缓存中已有的电影列表，用于跳过详情获取（增量更新）
    """
    data = _run_cli("coming", timeout=30)
    if not data or not isinstance(data, list):
        logger.error("douban-cli coming 返回数据为空")
        return []

    cached_lookup = {
        m.douban_id: m for m in (cached_movies or []) if m.douban_id
    }
    try:
        posters = _fetch_cinema_posters('later')
    except Exception as exc:
        logger.warning(f"获取即将上映海报失败，将使用旧缓存: {exc}")
        posters = {}

    movies: List[NewMovie] = []
    for item in data:
        douban_id = str(item.get("id", ""))
        title = str(item.get("title", "")).strip()
        if not title or not douban_id:
            continue

        genres = [str(g) for g in item.get("types", [])] if item.get("types") else []
        cached = cached_lookup.get(douban_id)
        fallback_year = cached.year if cached else ""
        premiered = _parse_release_date(str(item.get("release_date", "")), fallback_year)
        year = premiered[:4] if premiered else fallback_year
        rating = cached.rating if cached else 0.0
        if not genres and cached:
            genres = cached.genres
        poster_url = str(posters.get(douban_id) or (cached.poster_url if cached else ""))
        movies.append(NewMovie(
            title=title,
            year=year,
            rating=rating,
            douban_id=douban_id,
            status='coming',
            genres=genres,
            poster_url=poster_url,
            premiered=premiered,
        ))

    logger.info(f"即将上映: 获取 {len(movies)} 部电影")
    return movies


def _parse_release_date(release_date: str, fallback_year: str = "") -> str:
    """解析豆瓣常见上映日期为 YYYY-MM-DD；无法确定年份时返回空。"""
    import re
    from datetime import datetime
    if not release_date:
        return ""
    text = release_date.strip()
    full = re.match(r"(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?", text)
    if full:
        year, month, day = int(full.group(1)), int(full.group(2)), int(full.group(3) or 1)
        return f"{year:04d}-{month:02d}-{day:02d}"
    short = re.match(r"(\d{1,2})(?:月|\.)(\d{1,2})日?", text)
    if not short:
        return ""
    month, day = int(short.group(1)), int(short.group(2))
    year = int(fallback_year) if str(fallback_year).isdigit() else datetime.now().year
    if not fallback_year:
        now = datetime.now()
        if now.month >= 11 and month <= 2:
            year += 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _legacy_parse_release_date(release_date: str) -> str:
    """保留旧函数名的兼容入口。"""
    return _parse_release_date(release_date)


# ─────────────────── 对比函数 ───────────────────

def compare_with_local(new_movies: List[NewMovie],
                       local_movies: list) -> Tuple[List[NewMovie], List[NewMovie]]:
    """
    对比新片与本地库

    使用 douban_ranking._find_local_match 进行匹配（含豆瓣 ID、别名表等完整逻辑）
    """
    from scraper.douban_ranking import _find_local_match

    owned: List[NewMovie] = []
    missing: List[NewMovie] = []

    for nm in new_movies:
        if _find_local_match(nm, local_movies) is not None:
            owned.append(nm)
        else:
            missing.append(nm)

    return owned, missing


# Qt 后台线程 NewMovieFetcher 已迁移到 scraper/qt_tasks.py（避免网页版服务端导入时拉起 PyQt6），
# 通过模块级 __getattr__ 懒加载保留原有导入路径。
def __getattr__(name):
    if name == 'NewMovieFetcher':
        from .qt_tasks import NewMovieFetcher
        return NewMovieFetcher
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
