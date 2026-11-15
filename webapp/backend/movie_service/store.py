"""
电影墙数据存取层（HTTP/任务层与领域模块之间的适配）。

职责：
- 每个 app 实例一份 MovieStore（挂在 app.state），持有缓存/观看历史/收藏/失败记录；
  **绝不在模块导入期创建任何有状态对象**，多数据目录的多个 app 互不干扰。
- 所有对电影列表与 JSON 文件的读改写都走 store.lock（进程内线程锁）；
  movie_cache.json 用「临时文件 + os.replace」原子替换。
- Movie → 契约 2.1 的 DTO 转换（列表截断 plot/actors，详情不截断）。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from utils.cache_manager import CacheManager
from utils.config_manager import ConfigManager
from utils.failed_movies_manager import FailedMoviesManager
from utils.favorite_manager import FavoriteManager
from utils.watch_history import WatchHistoryManager
from wall_common.settings import Settings
from utils.library_sync import LibraryDatabase, movie_key
from utils.genres import localize_genres, preferred_rating

logger = logging.getLogger("movie_service.store")

LIST_PLOT_LIMIT = 200
LIST_ACTORS_LIMIT = 8

# 榜单缓存文件名（与 scraper/*_cache 模块默认文件名保持一致）
RANKING_CACHE_NAME = "douban_ranking_cache.json"
NEW_MOVIE_CACHE_NAME = "new_movie_cache.json"


# ─────────────────── 通用工具 ───────────────────


def movie_id(nfo_path: str) -> str:
    """契约 2.1：id = sha1(normalize_path(nfo_path))[:16]。"""
    return movie_key(nfo_path)


def normalize(nfo_path: str) -> str:
    return WatchHistoryManager.normalize_path(nfo_path)


def parse_nfo(nfo_path: str) -> Optional[Movie]:
    """服务端解析 NFO（带上 user rating 解析）。"""
    return NFOParser.parse(nfo_path, include_user_rating=True)


def movie_to_dto(
    movie: Movie,
    *,
    detail: bool = False,
    watched: bool = False,
    favorite: bool = False,
    rank: Optional[Dict[str, Optional[int]]] = None,
) -> Dict[str, Any]:
    """Movie → 契约 2.1 DTO。detail=False 时截断 plot(200) 与 actors(8)。"""
    plot = movie.plot or ""
    actors = list(movie.actors or [])
    if not detail:
        if len(plot) > LIST_PLOT_LIMIT:
            plot = plot[:LIST_PLOT_LIMIT]
        actors = actors[:LIST_ACTORS_LIMIT]

    ratings: Dict[str, Any] = dict(movie.ratings or {})
    user_rating = ratings.get("user", 0) or 0
    try:
        user_rating = float(user_rating)
    except (TypeError, ValueError):
        user_rating = 0.0

    rank_out = None
    if rank and (rank.get("douban_top250") or rank.get("imdb_top250")):
        rank_out = {
            "douban_top250": rank.get("douban_top250"),
            "imdb_top250": rank.get("imdb_top250"),
        }

    primary_rating, primary_source = preferred_rating(movie)
    return {
        "id": movie_id(movie.nfo_path) if movie.nfo_path else "",
        "title": movie.title or "",
        "original_title": movie.original_title or "",
        "year": movie.year or "",
        "premiered": movie.premiered or "",
        "plot": plot,
        "tagline": movie.tagline or "",
        "runtime": movie.runtime or "",
        "file_size": movie.file_size or "",
        "set_name": movie.set_name or "",
        "genres": localize_genres(movie.genres),
        "countries": list(movie.countries or []),
        "tags": list(movie.tags or []),
        "rating": primary_rating,
        "rating_source": primary_source,
        "ratings": ratings,
        "user_rating": user_rating,
        "watched": bool(watched),
        "favorite": bool(favorite),
        "directors": list(movie.directors or []),
        "actors": [{"name": a.name, "role": a.role, "thumb": a.thumb} for a in actors],
        "resolution": movie.resolution or "",
        "hdr_type": movie.hdr_type or "",
        "video_codec": movie.video_codec or "",
        "audio_codec": movie.audio_codec or "",
        "imdb_id": movie.imdb_id or "",
        "tmdb_id": movie.tmdb_id or "",
        "douban_url": movie.douban_url or "",
        "video_path": movie.video_path or "",
        "nfo_path": movie.nfo_path or "",
        "poster_path": movie.poster_path or "",
        "fanart_path": movie.fanart_path or "",
        "added_time": float(movie.added_time or 0.0),
        "has_poster": bool(movie.poster_path),
        "has_fanart": bool(movie.fanart_path),
        "rank": rank_out,
    }


def movie_rank(
    movie: Movie,
    top_lookup: Dict[str, Any],
    imdb_lookup: Dict[str, Any],
) -> Optional[Dict[str, Optional[int]]]:
    """
    查询某部电影在豆瓣/IMDB Top250 中的名次（语义同桌面版 _get_movie_rank_info）。
    无任何排名返回 None。
    """
    if not top_lookup and not imdb_lookup:
        return None

    from scraper.douban_ranking import _normalize_title

    result: Dict[str, Optional[int]] = {"douban_top250": None, "imdb_top250": None}
    title = movie.title or ""
    original_title = movie.original_title or ""
    year = movie.year or ""

    for lookup, key in ((top_lookup, "douban_top250"), (imdb_lookup, "imdb_top250")):
        if not lookup:
            continue
        for candidate in (title, original_title):
            norm = _normalize_title(candidate)
            if not norm:
                continue
            hit = None
            if year and f"{norm}_{year}" in lookup:
                hit = lookup[f"{norm}_{year}"]
            elif norm in lookup:
                hit = lookup[norm]
            if hit is not None:
                try:
                    result[key] = int(hit.get("rank") or 0) or None
                except (TypeError, ValueError):
                    result[key] = None
                break

    if result["douban_top250"] is None and result["imdb_top250"] is None:
        return None
    return result


# ─────────────────── 存储 ───────────────────


class MovieStore:
    """单个 app 实例的电影数据存取（线程安全）。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()
        data_dir = Path(settings.data_dir)

        self.cache_file = data_dir / "movie_cache.json"
        self.config_file = data_dir / "config.json"
        self.history_file = data_dir / "watch_history.json"
        self.favorites_file = data_dir / "favorites.json"
        self.failed_file = data_dir / "failed_movies.json"
        self.ranking_cache_file = data_dir / RANKING_CACHE_NAME
        self.new_movie_cache_file = data_dir / NEW_MOVIE_CACHE_NAME

        # 显式传路径，避免 utils.app_paths 全局目录串台
        self._cache = CacheManager(cache_file=str(self.cache_file))
        self.watch = WatchHistoryManager(history_file=str(self.history_file))
        self.fav = FavoriteManager(data_file=str(self.favorites_file))
        self.failed = FailedMoviesManager(file_path=str(self.failed_file))

        self._movies: List[Movie] = []
        self._by_id: Dict[str, Movie] = {}
        self._loaded = False
        self.database = LibraryDatabase(data_dir / 'library.sqlite3')
        self._db_revision = -1

    # ── 配置 ──────────────────────────────────────────────
    def config(self) -> ConfigManager:
        """
        当前数据目录的配置。

        ConfigManager 是进程级单例，这里每次显式按本 app 的 config.json 重新加载，
        保证读写的都是当前 app 的数据目录（并发调用方需持 store.lock）。
        """
        cfg = ConfigManager()
        cfg.load_config(str(self.config_file))
        return cfg

    def movie_paths(self) -> List[str]:
        return [str(p) for p in self.config().get_movie_paths()]

    # ── 电影列表 ──────────────────────────────────────────
    def ensure_loaded(self) -> None:
        """首次访问时从 movie_cache.json 载入（路径不匹配/不存在则为空列表）。"""
        with self.lock:
            if self._loaded and self.database.info()['revision'] == self._db_revision:
                return
            snapshot = self.database.snapshot()
            if snapshot['revision']:
                records = [item['data'] for item in snapshot['records'] if not item['deleted']]
                movies = [self._cache._deserialize_movie(item) for item in records]
                self.watch.watched_movies = {self.watch.normalize_path(item['nfo_path']) for item in records if item.get('watched')}
                self.fav.favorites = {self.fav.normalize_path(item['nfo_path']) for item in records if item.get('_favorite')}
            else:
                movies = self._cache.load_cache(self.movie_paths()) or []
                if movies:
                    self.database.replace({movie_id(movie.nfo_path): self.sync_record(movie) for movie in movies})
                    snapshot = self.database.snapshot()
            self._set_movies(movies)
            self._loaded = True
            self._db_revision = snapshot['revision']
            logger.info("电影缓存已载入: %d 部", len(movies))

    def snapshot(self) -> List[Movie]:
        self.ensure_loaded()
        with self.lock:
            return list(self._movies)

    def count(self) -> int:
        self.ensure_loaded()
        with self.lock:
            return len(self._movies)

    def get(self, mid: str) -> Optional[Movie]:
        self.ensure_loaded()
        with self.lock:
            return self._by_id.get(mid)

    def cache_info(self) -> Optional[dict]:
        return self._cache.get_cache_info()

    def _set_movies(self, movies: List[Movie]) -> None:
        self._movies = list(movies)
        self._by_id = {movie_id(m.nfo_path): m for m in self._movies if m.nfo_path}

    def save_cache(self) -> None:
        """把当前电影列表原子写回 movie_cache.json。"""
        with self.lock:
            self.database.replace({movie_id(movie.nfo_path): self.sync_record(movie) for movie in self._movies})
            self._db_revision = self.database.info()['revision']
            paths = self.movie_paths()
            tmp = self.cache_file.parent / f".{self.cache_file.name}.tmp"
            helper = CacheManager(cache_file=str(tmp))
            ok = helper.save_cache(self._movies, paths)
            if not ok:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise IOError("电影缓存写入失败")
            os.replace(tmp, self.cache_file)

    def sync_record(self, movie: Movie) -> dict:
        data = self._cache._serialize_movie(movie)
        data['watched'] = self.watch.is_watched(movie.nfo_path)
        data['_favorite'] = self.fav.is_favorite(movie.nfo_path)
        return data

    def replace_all(self, movies: List[Movie]) -> None:
        """整表替换（扫描任务完成后调用）并落盘。"""
        with self.lock:
            self._set_movies(movies)
            self._loaded = True
            self.save_cache()

    # ── 解析 / 状态写入 ───────────────────────────────────
    def reparse(self, movie: Movie) -> Optional[Movie]:
        """
        重新解析 NFO 并替换缓存中的对象（保留 added_time），落盘后返回新对象。
        解析失败返回 None（原对象不动）。
        """
        from .nas import NASPaths
        mapper = NASPaths(self.settings.data_dir)
        updated = parse_nfo(mapper.source(movie.nfo_path)) if movie.nfo_path else None
        if updated is None:
            return None
        mapper.movie(updated)
        with self.lock:
            if not updated.added_time:
                updated.added_time = float(movie.added_time or 0.0)
            updated.watched = self.watch.is_watched(movie.nfo_path)
            idx = None
            for i, current in enumerate(self._movies):
                if current is movie or (current.nfo_path and current.nfo_path == movie.nfo_path):
                    idx = i
                    break
            if idx is None:
                return None
            self._movies[idx] = updated
            self._set_movies(self._movies)
            self.save_cache()
        return updated

    def set_watched(self, movie: Movie, value: bool) -> None:
        with self.lock:
            if value:
                self.watch.mark_watched(movie.nfo_path)
            else:
                self.watch.mark_unwatched(movie.nfo_path)
            movie.watched = value
            self.save_cache()

    def set_favorite(self, movie: Movie, value: bool) -> None:
        with self.lock:
            if value:
                self.fav.add_favorite(movie.nfo_path)
            else:
                self.fav.remove_favorite(movie.nfo_path)
            self.save_cache()

    def set_user_rating(self, movie: Movie, rating: float) -> None:
        """写回 NFO 的 <ratings><rating name="user"> 并刷新缓存。"""
        if not (0.0 <= float(rating) <= 10.0):
            raise ValueError("评分必须在 0-10 之间")
        with self.lock:
            # 个人评分属于共享资料，不依赖 NAS 在线；源 NFO 编辑由明确操作触发。
            try:
                has_source = bool(movie.nfo_path) and Path(movie.nfo_path).is_file()
            except OSError:
                has_source = False
            if has_source:
                if not NFOParser.update_user_rating(movie.nfo_path, float(rating)):
                    raise OSError('写入 NFO 用户评分失败')
            movie.ratings['user'] = float(rating)
            self.save_cache()

    def remove(self, movie: Movie) -> None:
        """仅删本地记录：缓存 + 观看历史 + 收藏 + 失败记录（不动媒体文件）。"""
        with self.lock:
            self._set_movies(
                [
                    m
                    for m in self._movies
                    if m is not movie
                    and not (movie.nfo_path and m.nfo_path == movie.nfo_path)
                ]
            )
            self.save_cache()
            if movie.nfo_path:
                self.fav.remove_favorite(movie.nfo_path)
                self.watch.mark_unwatched(movie.nfo_path)
                self.failed.remove_failed(movie.nfo_path)

    def apply_watched(self, movies: List[Movie]) -> None:
        """批量按观看历史刷新内存对象的 watched 字段（供扫描任务收尾调用）。"""
        with self.lock:
            for movie in movies:
                movie.watched = bool(movie.nfo_path) and self.watch.is_watched(movie.nfo_path)

    def prune_stale_records(self, valid_nfo_paths: set) -> Tuple[int, int]:
        """按当前扫描结果清理失效的观看历史/收藏记录，返回 (移除的观看数, 移除的收藏数)。"""
        with self.lock:
            old_watched = len(self.watch.watched_movies)
            self.watch.watched_movies = {p for p in self.watch.watched_movies if p in valid_nfo_paths}
            removed_watched = old_watched - len(self.watch.watched_movies)
            if removed_watched > 0:
                self.watch.save()

            old_fav = len(self.fav.favorites)
            self.fav.favorites = {p for p in self.fav.favorites if p in valid_nfo_paths}
            removed_fav = old_fav - len(self.fav.favorites)
            if removed_fav > 0:
                self.fav.save()

            # 清理「上次打开的电影」记录
            cfg = self.config()
            last_nfo = cfg.get_last_opened_movie()
            if last_nfo and normalize(last_nfo) not in valid_nfo_paths:
                cfg.set_last_opened_movie("")
                cfg.save_config(str(self.config_file))

            if removed_watched or removed_fav:
                logger.info(
                    "已清理本地失效记录: 观看历史=%d, 收藏=%d", removed_watched, removed_fav
                )
            return removed_watched, removed_fav

    # ── DTO ───────────────────────────────────────────────
    def rank_lookups(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """豆瓣/IMDB Top250 排名查询表（读本数据目录的榜单缓存）。"""
        from scraper.douban_ranking import (
            get_imdb_top250_rank_lookup,
            get_top250_rank_lookup,
        )

        try:
            top = get_top250_rank_lookup(cache_path=self.ranking_cache_file)
        except Exception as exc:  # noqa: BLE001
            logger.debug("加载豆瓣 Top250 排名表失败: %s", exc)
            top = {}
        try:
            imdb = get_imdb_top250_rank_lookup(cache_path=self.ranking_cache_file)
        except Exception as exc:  # noqa: BLE001
            logger.debug("加载 IMDB Top250 排名表失败: %s", exc)
            imdb = {}
        return top, imdb

    def dto(
        self,
        movie: Movie,
        *,
        detail: bool = False,
        rank_lookups: Optional[Tuple[dict, dict]] = None,
    ) -> Dict[str, Any]:
        """构建单部电影 DTO（watched 以 WatchHistoryManager 为准，favorite 以 FavoriteManager 为准）。"""
        with self.lock:
            watched = bool(movie.nfo_path) and self.watch.is_watched(movie.nfo_path)
            favorite = bool(movie.nfo_path) and self.fav.is_favorite(movie.nfo_path)
        rank = None
        if rank_lookups is not None:
            rank = movie_rank(movie, rank_lookups[0], rank_lookups[1])
        return movie_to_dto(movie, detail=detail, watched=watched, favorite=favorite, rank=rank)
