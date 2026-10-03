"""
榜单/新片抓取的 Qt 后台线程

这些类原本位于 douban_ranking.py / new_movie_checker.py 末尾，因其依赖 PyQt6，
会被网页版服务端（无界面环境）导入时连带拉起 PyQt，故迁移到本模块。

原模块通过模块级 __getattr__ 懒加载继续对外暴露同名类，
因此旧的导入路径 `from scraper.douban_ranking import RankingFetcher` 依然有效。
"""
import logging
from typing import List

from PyQt6.QtCore import QThread, pyqtSignal

from .douban_ranking import (
    RankedMovie,
    compare_with_local,
    fetch_douban_chart,
    fetch_douban_top250,
    fetch_imdb_top250,
    load_imdb_cache,
    load_ranking_cache,
    save_ranking_cache,
)
from .new_movie_checker import (
    NewMovie,
    compare_with_local as compare_new_with_local,
    fetch_coming_soon,
    fetch_nowplaying,
    load_new_movie_cache,
    save_new_movie_cache,
)

logger = logging.getLogger(__name__)


class RankingFetcher(QThread):
    """
    后台抓取排行榜并对比本地库

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
        self._sources = sources or ['top250', 'chart']
        self._use_cache = use_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        all_ranked: List[RankedMovie] = []
        top250: List[RankedMovie] = []
        chart: List[RankedMovie] = []
        imdb_top250: List[RankedMovie] = []

        try:
            # 优先从缓存加载（仅在 use_cache=True 且缓存存在时）
            if self._use_cache:
                cached_top250, cached_chart = load_ranking_cache()
                cached_imdb = load_imdb_cache() if 'imdb_top250' in self._sources else []
                if cached_top250 or cached_chart or cached_imdb:
                    self.progress.emit("从本地缓存加载榜单数据...")
                    if 'top250' in self._sources and cached_top250:
                        top250 = cached_top250
                        self.progress.emit(f"  豆瓣Top250: {len(top250)} 部电影（缓存）")
                        all_ranked.extend(top250)
                    if 'chart' in self._sources and cached_chart:
                        chart = cached_chart
                        self.progress.emit(f"  豆瓣热门: {len(chart)} 部电影（缓存）")
                        all_ranked.extend(chart)
                    if 'imdb_top250' in self._sources and cached_imdb:
                        imdb_top250 = cached_imdb
                        self.progress.emit(f"  IMDB Top250: {len(imdb_top250)} 部电影（缓存）")
                        all_ranked.extend(imdb_top250)
                    if all_ranked:
                        self.progress.emit(f"榜单合计: {len(all_ranked)} 部电影")
                        self.progress.emit("正在与本地电影库对比...")
                        owned, missing = compare_with_local(all_ranked, self._local_movies)
                        self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
                        self.finished.emit(owned, missing)
                        return

            # 缓存不可用或强制刷新：从网络抓取（增量模式）
            # 加载旧缓存用于增量对比（已有电影跳过详情获取，仅更新评分/排名）
            all_cached: List[RankedMovie] = []
            if not self._use_cache:
                cached_top250_old, cached_chart_old = load_ranking_cache()
                cached_imdb_old = load_imdb_cache() if 'imdb_top250' in self._sources else []
                all_cached = cached_top250_old + cached_chart_old + cached_imdb_old

            if 'top250' in self._sources:
                self.progress.emit("正在抓取豆瓣 Top250 榜单...")
                top250 = fetch_douban_top250(cached_movies=all_cached)
                self.progress.emit(f"  Top250 获取完成: {len(top250)} 部电影")
                all_ranked.extend(top250)

                if self._cancelled:
                    return

            if 'chart' in self._sources:
                self.progress.emit("正在抓取豆瓣近期热门榜单...")
                chart = fetch_douban_chart(cached_movies=all_cached)
                self.progress.emit(f"  热门榜单获取完成: {len(chart)} 部电影")
                all_ranked.extend(chart)

                if self._cancelled:
                    return

            if 'imdb_top250' in self._sources:
                self.progress.emit("正在抓取 IMDB Top250 榜单...")
                imdb_top250 = fetch_imdb_top250(cached_movies=all_cached)
                self.progress.emit(f"  IMDB Top250 获取完成: {len(imdb_top250)} 部电影")
                all_ranked.extend(imdb_top250)

                if self._cancelled:
                    return

            # 保存到缓存
            if top250 or chart:
                save_ranking_cache(top250, chart, imdb_top250 if imdb_top250 else None)
            elif imdb_top250:
                # 只有 IMDB 数据时也保存（合并到现有缓存）
                save_ranking_cache([], [], imdb_top250)

            self.progress.emit(f"榜单合计: {len(all_ranked)} 部电影")
            self.progress.emit("正在与本地电影库对比...")

            owned, missing = compare_with_local(all_ranked, self._local_movies)
            self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")

            self.finished.emit(owned, missing)

        except Exception as e:
            logger.exception("抓取榜单失败")
            self.error.emit(str(e))


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

            owned, missing = compare_new_with_local(all_new, self._local_movies)
            self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")

            self.finished.emit(owned, missing)

        except Exception as e:
            logger.exception("获取新片信息失败")
            self.error.emit(str(e))
