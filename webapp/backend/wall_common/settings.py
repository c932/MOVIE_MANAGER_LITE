"""
服务端运行设置。

设计要点：
- Settings 是 **每个 app 实例** 一份（挂在 app.state），不搞进程级单例，
  这样测试可以在同一进程里用不同数据目录创建多个 app。
- 数据目录解析顺序：显式 data_dir 参数 > MML_DATA_DIR 环境变量 > 测试临时目录 > 与桌面版一致的默认目录。
- align_app_paths() 负责让领域模块 utils.app_paths 与服务解析出的目录保持一致，
  并重置 ConfigManager 单例，避免进程内目录/配置串台。
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]  # webapp/backend
REPO_ROOT = BACKEND_ROOT.parents[1]                 # 仓库根目录

# 保证 wall_common 与仓库领域模块（models/parsers/utils/gamewall/scraper）可导入
for _p in (str(REPO_ROOT), str(BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger("wall_common.settings")

SERVICES = ("movie",)
_API_PREFIX = {"movie": "/api/movie"}


@dataclass(frozen=True)
class Settings:
    service: str                       # "movie" | "game"
    api_prefix: str                    # 路由前缀，如 /api/movie
    repo_root: Path                    # 仓库根目录
    backend_root: Path                 # webapp/backend
    data_dir: Path                     # 运行数据（config/cache/posters）
    image_cache_dir: Path              # 服务端生成的缩略图缓存
    cover_cache_dir: Path              # 远程封面代理缓存（游戏墙）
    max_upload_mb: int = 20
    poster_max_edge: int = 1400        # 海报/封面请求的最大边长
    job_history: int = 60              # 保留的已完成任务数


def _default_data_dir(service: str) -> Path:
    """与 utils/app_paths 的桌面版默认行为保持一致。"""
    return REPO_ROOT / "data"


def resolve(service: str, data_dir: Optional[Path] = None) -> Settings:
    """解析服务设置（不产生任何全局副作用）。"""
    if service not in SERVICES:
        raise ValueError(f"未知服务: {service!r}，应为 {SERVICES}")

    if data_dir is not None:
        resolved = Path(data_dir)
    elif os.environ.get("MML_TESTING"):
        # 测试进程里没显式指定目录时，绝不允许落到真实 data/
        resolved = Path(tempfile.mkdtemp(prefix=f"mml-{service}-test-"))
    elif os.environ.get("MML_DATA_DIR"):
        resolved = Path(os.environ["MML_DATA_DIR"])
    else:
        resolved = _default_data_dir(service)

    resolved.mkdir(parents=True, exist_ok=True)
    image_cache = resolved / "web_cache" / "images"
    cover_cache = resolved / "web_cache" / "covers"
    image_cache.mkdir(parents=True, exist_ok=True)
    cover_cache.mkdir(parents=True, exist_ok=True)

    return Settings(
        service=service,
        api_prefix=_API_PREFIX[service],
        repo_root=REPO_ROOT,
        backend_root=BACKEND_ROOT,
        data_dir=resolved,
        image_cache_dir=image_cache,
        cover_cache_dir=cover_cache,
    )


def align_app_paths(resolved: Path) -> None:
    """
    让领域模块（utils.app_paths / ConfigManager 单例）指向同一数据目录。

    - 通过 MML_DATA_DIR 让之后才导入的 utils.app_paths 解析到同一位置；
    - 若 utils.app_paths 已导入且目录不一致，直接校正其模块全局；
    - 重置 ConfigManager 单例，使其按新目录重新加载配置。
    """
    os.environ.setdefault("MML_DATA_DIR", str(resolved))
    import utils.app_paths as ap  # noqa: PLC0415
    if Path(ap.DATA_DIR) != resolved:
        logger.info("校正 utils.app_paths.DATA_DIR: %s -> %s", ap.DATA_DIR, resolved)
        ap.DATA_DIR = resolved

    from utils.config_manager import ConfigManager  # noqa: PLC0415
    ConfigManager._instance = None
    ConfigManager._config = {}
