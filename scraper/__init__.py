"""
刮削工作流模块

提供独立的电影刮削功能，集成：
1. TinyMediaManager CLI 刮削
2. TMM_DOUBAN 豆瓣评分注入（普通模式 + Selenium 模式）
3. 自动刷新媒体库

此模块完全独立，不影响现有电影墙核心功能。
"""

__version__ = "1.2.0"
__author__ = "Movie Manager Lite Team"

from .scrape_workflow import ScrapeConfig, ScrapeWorker, WorkflowResult, FailedMovie
from .scrape_dialog import ScrapeDialog
from .manual_match_dialog import ManualMatchDialog

__all__ = [
    "ScrapeConfig",
    "ScrapeWorker", 
    "WorkflowResult",
    "FailedMovie",
    "ScrapeDialog",
    "ManualMatchDialog",
]
