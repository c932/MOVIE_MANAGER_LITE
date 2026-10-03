"""
刮削模块

提供豆瓣评分注入和榜单对比功能：
1. douban-cli 豆瓣评分注入（单部/批量）
2. 豆瓣电影排行榜对比
3. 最新电影检查与推荐

此模块完全独立，不影响现有电影墙核心功能。
"""

__version__ = "2.1.0"
__author__ = "Movie Manager Lite Team"

from .douban_cli import (
    run_douban_cli, search_movie, get_movie_detail,
    inject_douban_to_nfo, read_nfo_movie_info, scrape_single_movie,
)
from .douban_ranking import (
    RankedMovie,
    fetch_douban_top250, fetch_douban_chart, compare_with_local,
)
from .new_movie_checker import NewMovie, fetch_nowplaying, fetch_coming_soon

# RankingFetcher / NewMovieFetcher 依赖 PyQt6，放到 qt_tasks.py 中按需加载，
# 保证网页版服务端 `import scraper.*` 时不会拉起 Qt。
_QT_LAZY = {"RankingFetcher", "NewMovieFetcher"}


def __getattr__(name):
    if name in _QT_LAZY:
        from . import qt_tasks
        return getattr(qt_tasks, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "run_douban_cli",
    "search_movie",
    "get_movie_detail",
    "inject_douban_to_nfo",
    "read_nfo_movie_info",
    "scrape_single_movie",
    "RankedMovie",
    "RankingFetcher",
    "fetch_douban_top250",
    "fetch_douban_chart",
    "compare_with_local",
    "NewMovie",
    "NewMovieFetcher",
    "fetch_nowplaying",
    "fetch_coming_soon",
]
