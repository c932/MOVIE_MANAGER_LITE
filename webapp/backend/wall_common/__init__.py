"""
网页版服务端共享基础设施（电影墙服务 / 游戏墙服务共用）。

包内模块：
- settings   运行设置（服务身份、数据目录、缓存目录）
- jobs       后台任务管理器（线程 + 进度轮询）
- images     Pillow 图片缩放/远程封面缓存
- factory    FastAPI 应用工厂（CORS、健康检查、异常处理）
- api        任务查询/取消的通用路由
"""
from .settings import Settings, resolve, align_app_paths  # noqa: F401
from .jobs import JobManager, JobContext, JobCancelled  # noqa: F401

__all__ = [
    "Settings", "resolve", "align_app_paths",
    "JobManager", "JobContext", "JobCancelled",
]
