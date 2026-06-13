"""
刮削工作流模块

提供独立的电影刮削功能，集成：
1. TinyMediaManager CLI 刮削
2. TMM_DOUBAN 豆瓣评分注入（普通模式 + Selenium 模式）
3. 自动刷新媒体库
4. 豆瓣电影排行榜对比
5. 最新电影检查与推荐

此模块完全独立，不影响现有电影墙核心功能。
"""

__version__ = "1.3.0"
__author__ = "Movie Manager Lite Team"

from .scrape_workflow import ScrapeConfig, ScrapeWorker, WorkflowResult, FailedMovie
from .scrape_dialog import ScrapeDialog
from .manual_match_dialog import ManualMatchDialog
from .douban_ranking import RankedMovie, RankingFetcher, fetch_douban_top250, fetch_douban_chart, compare_with_local
from .new_movie_checker import NewMovie, NewMovieFetcher, fetch_nowplaying, fetch_coming_soon

__all__ = [
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
