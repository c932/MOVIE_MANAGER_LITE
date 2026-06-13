"""
最新电影检查模块

通过 douban-cli 获取正在热映和即将上映的电影，与本地库对比，
识别本地缺失的新片并给出补充建议。支持本地缓存，避免重复获取详情。
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

from PyQt6.QtCore import QThread, pyqtSignal

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


def _get_cache_path() -> Path:
    """获取新片缓存文件路径"""
    global _CACHE_PATH
    if _CACHE_PATH is None:
        from utils.app_paths import resolve_data_file
        _CACHE_PATH = resolve_data_file("new_movie_cache.json")
    return _CACHE_PATH


def save_new_movie_cache(nowplaying: List[NewMovie], coming: List[NewMovie]) -> bool:
    """保存新片数据到本地缓存"""
    try:
        from datetime import datetime
        path = _get_cache_path()
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


def load_new_movie_cache() -> Tuple[List[NewMovie], List[NewMovie]]:
    """从本地缓存加载新片数据，失败返回空列表"""
    try:
        path = _get_cache_path()
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


def _fetch_details_concurrent(ids: List[str]) -> dict:
    """并发获取电影详情，返回 {douban_id: detail_dict}"""
    if not ids:
        return {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from scraper.douban_ranking import _fetch_movie_detail

    details = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_movie_detail, did): did for did in ids}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result.get("detail"):
                    details[result["douban_id"]] = result["detail"]
            except Exception as e:
                logger.warning(f"获取新片详情失败: {e}")
    return details


def fetch_nowplaying(cached_movies: List[NewMovie] = None) -> List[NewMovie]:
    """
    获取豆瓣正在热映电影列表

    数据源：douban-cli now --json
    筛选：仅保留有评分且 vote_count > 0 的条目（过滤掉混入的即将上映电影）

    cached_movies: 缓存中已有的电影列表，用于跳过详情获取（增量更新）
    """
    data = _run_cli("now", "--limit", "50", timeout=30)
    if not data or not isinstance(data, list):
        logger.error("douban-cli now 返回数据为空")
        return []

    # 筛选正在热映：有实际评分（score != "-"）且有投票
    candidates = []
    for item in data:
        if not isinstance(item, dict):
            continue
        score_str = str(item.get("score", "-"))
        vote_count = int(item.get("vote_count", 0) or 0)
        if score_str in ("-", "", "0") or vote_count <= 0:
            continue
        candidates.append(item)

    logger.info(f"正在热映: {len(data)} 部中筛选出 {len(candidates)} 部（有评分）")

    if not candidates:
        return []

    # 构建缓存查询表：douban_id -> NewMovie
    cached_lookup = {}
    if cached_movies:
        cached_lookup = {m.douban_id: m for m in cached_movies if m.douban_id}

    # 仅获取缓存中没有的新电影详情
    all_ids = [str(item.get("id", "")) for item in candidates if item.get("id")]
    new_ids = [did for did in all_ids if did and did not in cached_lookup]

    if new_ids:
        logger.info(f"正在热映: {len(new_ids)}/{len(all_ids)} 部为新电影，获取详情")
        new_details = _fetch_details_concurrent(new_ids)
    else:
        logger.info(f"正在热映: 全部 {len(all_ids)} 部均在缓存中，跳过详情获取")
        new_details = {}

    movies: List[NewMovie] = []
    for item in candidates:
        douban_id = str(item.get("id", ""))
        title = str(item.get("title", "")).strip()
        if not title or not douban_id:
            continue

        try:
            rating = float(item.get("score", 0) or 0)
        except (ValueError, TypeError):
            rating = 0.0

        # 优先使用缓存数据
        if douban_id in cached_lookup:
            movies.append(cached_lookup[douban_id])
            continue

        # 从详情提取上映日期和年份
        detail = new_details.get(douban_id, {})
        from scraper.douban_ranking import _parse_pubdate
        premiered = _parse_pubdate(detail.get("pubdate", [])) if detail else ""
        year = str(detail.get("year", "")) if detail else ""
        if not year and premiered and len(premiered) >= 4:
            year = premiered[:4]
        if not year:
            year = str(item.get("release_date", ""))[:4] if item.get("release_date") not in (None, "-", "") else ""

        # 从详情提取类型
        genres = []
        if detail and detail.get("genres"):
            genres = [str(g) for g in detail["genres"]]

        movies.append(NewMovie(
            title=title,
            year=year,
            rating=rating,
            douban_id=douban_id,
            status='nowplaying',
            genres=genres,
            premiered=premiered,
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

    # 构建缓存查询表：douban_id -> NewMovie
    cached_lookup = {}
    if cached_movies:
        cached_lookup = {m.douban_id: m for m in cached_movies if m.douban_id}

    # 仅获取缓存中没有的新电影详情
    all_ids = [str(item.get("id", "")) for item in data if item.get("id")]
    new_ids = [did for did in all_ids if did and did not in cached_lookup]

    if new_ids:
        logger.info(f"即将上映: {len(new_ids)}/{len(all_ids)} 部为新电影，获取详情")
        new_details = _fetch_details_concurrent(new_ids)
    else:
        logger.info(f"即将上映: 全部 {len(all_ids)} 部均在缓存中，跳过详情获取")
        new_details = {}

    movies: List[NewMovie] = []
    for item in data:
        douban_id = str(item.get("id", ""))
        title = str(item.get("title", "")).strip()
        if not title or not douban_id:
            continue

        # 类型（coming 命令直接返回 types）
        genres = [str(g) for g in item.get("types", [])] if item.get("types") else []

        # 优先使用缓存数据
        if douban_id in cached_lookup:
            cached_movie = cached_lookup[douban_id]
            # 更新标题和类型（可能已变更）
            movies.append(NewMovie(
                title=title,
                year=cached_movie.year,
                rating=cached_movie.rating,
                douban_id=douban_id,
                status='coming',
                genres=genres or cached_movie.genres,
                premiered=cached_movie.premiered,
            ))
            continue

        # 从详情提取上映日期和评分
        detail = new_details.get(douban_id, {})
        from scraper.douban_ranking import _parse_pubdate
        premiered = _parse_pubdate(detail.get("pubdate", [])) if detail else ""
        # 详情无日期时，使用 coming 命令返回的 release_date（如 "06月15日"）
        if not premiered:
            premiered = _parse_release_date(item.get("release_date", ""))
        year = str(detail.get("year", "")) if detail else ""
        if not year and premiered and len(premiered) >= 4:
            year = premiered[:4]

        rating = 0.0
        if detail and detail.get("rating"):
            try:
                rating = float(detail["rating"])
            except (ValueError, TypeError):
                pass

        movies.append(NewMovie(
            title=title,
            year=year,
            rating=rating,
            douban_id=douban_id,
            status='coming',
            genres=genres,
            premiered=premiered,
        ))

    logger.info(f"即将上映: 获取 {len(movies)} 部电影")
    return movies


# ─────────────────── 日期解析 ───────────────────

def _parse_release_date(release_date: str) -> str:
    """解析 coming 命令返回的 release_date（如 '06月15日'）为 'YYYY-MM-DD' 格式"""
    import re
    from datetime import datetime
    if not release_date:
        return ""
    m = re.match(r'(\d{1,2})月(\d{1,2})日', release_date)
    if not m:
        return ""
    month, day = int(m.group(1)), int(m.group(2))
    now = datetime.now()
    year = now.year
    # 如果当前是12月但电影在1-2月，说明是明年的
    if now.month >= 11 and month <= 2:
        year += 1
    return f"{year:04d}-{month:02d}-{day:02d}"


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


# ─────────────────── 后台工作线程 ───────────────────

class NewMovieFetcher(QThread):
    """
    后台抓取新片并对比本地库

    信号:
        progress(str)          - 进度日志
        finished(list, list)   - 完成: (owned, missing)
        error(str)             - 错误信息
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, list)
    error = pyqtSignal(str)

    def __init__(self, local_movies: list, sources: list = None,
                 use_cache: bool = True, parent=None):
        super().__init__(parent)
        self._local_movies = local_movies
        self._sources = sources or ['nowplaying', 'coming']
        self._use_cache = use_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        all_new: List[NewMovie] = []
        nowplaying: List[NewMovie] = []
        coming: List[NewMovie] = []

        try:
            # 优先从缓存加载（仅在 use_cache=True 且缓存存在时）
            if self._use_cache:
                cached_nowplaying, cached_coming = load_new_movie_cache()
                if cached_nowplaying or cached_coming:
                    self.progress.emit("从本地缓存加载新片数据...")
                    if 'nowplaying' in self._sources and cached_nowplaying:
                        nowplaying = cached_nowplaying
                        self.progress.emit(f"  正在热映: {len(nowplaying)} 部（缓存）")
                        all_new.extend(nowplaying)
                    if 'coming' in self._sources and cached_coming:
                        coming = cached_coming
                        self.progress.emit(f"  即将上映: {len(coming)} 部（缓存）")
                        all_new.extend(coming)
                    if all_new:
                        self.progress.emit(f"新片合计: {len(all_new)} 部")
                        self.progress.emit("正在与本地电影库对比...")
                        owned, missing = compare_with_local(all_new, self._local_movies)
                        self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
                        self.finished.emit(owned, missing)
                        return

            # 缓存不可用或强制刷新：从网络抓取（增量模式）
            # 加载旧缓存用于增量对比（只获取新电影的详情）
            cached_nowplaying, cached_coming = load_new_movie_cache() if not self._use_cache else ([], [])
            all_cached = cached_nowplaying + cached_coming

            if 'nowplaying' in self._sources:
                self.progress.emit("正在获取豆瓣正在热映...")
                nowplaying = fetch_nowplaying(cached_movies=all_cached)
                self.progress.emit(f"  正在热映: {len(nowplaying)} 部")
                all_new.extend(nowplaying)

                if self._cancelled:
                    return

            if 'coming' in self._sources:
                self.progress.emit("正在获取豆瓣即将上映...")
                coming = fetch_coming_soon(cached_movies=all_cached)
                self.progress.emit(f"  即将上映: {len(coming)} 部")
                all_new.extend(coming)

                if self._cancelled:
                    return

            # 保存到缓存（合并：未请求的来源保留旧缓存）
            save_nowplaying = nowplaying if nowplaying else (cached_nowplaying if not self._use_cache else [])
            save_coming = coming if coming else (cached_coming if not self._use_cache else [])
            if save_nowplaying or save_coming:
                save_new_movie_cache(save_nowplaying, save_coming)

            self.progress.emit(f"新片合计: {len(all_new)} 部")
            self.progress.emit("正在与本地电影库对比...")

            owned, missing = compare_with_local(all_new, self._local_movies)
            self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")

            self.finished.emit(owned, missing)

        except Exception as e:
            logger.exception("获取新片信息失败")
            self.error.emit(str(e))
