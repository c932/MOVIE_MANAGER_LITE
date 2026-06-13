"""
刮削工作流模块

提供独立的电影刮削功能，集成：
1. douban-cli 豆瓣评分注入
2. 自动刷新媒体库
3. 豆瓣电影排行榜对比
4. 最新电影检查与推荐

此模块完全独立，不影响现有电影墙核心功能。
"""

__version__ = "2.0.0"
__author__ = "Movie Manager Lite Team"

from .douban_cli import run_douban_cli, search_movie, get_movie_detail, inject_douban_to_nfo, read_nfo_movie_info
from .scrape_workflow import ScrapeConfig, ScrapeWorker, WorkflowResult, FailedMovie
from .scrape_dialog import ScrapeDialog
from .manual_match_dialog import ManualMatchDialog
from .douban_ranking import RankedMovie, RankingFetcher, fetch_douban_top250, fetch_douban_chart, compare_with_local
from .new_movie_checker import NewMovie, NewMovieFetcher, fetch_nowplaying, fetch_coming_soon

__all__ = [
    "run_douban_cli",
    "search_movie",
    "get_movie_detail",
    "inject_douban_to_nfo",
    "read_nfo_movie_info",
    "ScrapeConfig",
    "ScrapeWorker", 
    "WorkflowResult",
    "FailedMovie",
    "ScrapeDialog",
    "ManualMatchDialog",
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
