"""
媒体库与设置端点（契约 2.2 的 /library/*、/settings）。

长任务统一走 wall_common.jobs.JobManager：这里只负责提交任务体
（编排逻辑在 movie_service.tasks），轮询进度由通用 /jobs 路由负责。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from wall_common.jobs import STATUS_CANCELLED, STATUS_DONE, STATUS_ERROR

from .deps import get_store
from .tasks import REFRESH_KIND, run_library_refresh

logger = logging.getLogger("movie_service.routes_library")

router = APIRouter()

_FINISHED = (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED)


class RefreshRequest(BaseModel):
    force: bool = False


class SettingsUpdate(BaseModel):
    """PUT /settings 的部分字段（未提交的键保持原值）。"""

    movie_paths: Optional[List[str]] = None
    blacklist_folders: Optional[List[str]] = None
    blacklist_patterns: Optional[List[str]] = None
    poster_width: Optional[int] = None
    poster_height: Optional[int] = None
    grid_columns: Optional[int] = None
    poster_scale: Optional[int] = None


@router.post("/library/refresh")
def refresh_library(
    request: Request, payload: Optional[RefreshRequest] = None
) -> Dict[str, str]:
    """提交媒体库刷新任务（force=true 为全量重建）。"""
    store = get_store(request)
    force = bool(payload.force) if payload else False

    job = request.app.state.jobs.submit(
        REFRESH_KIND,
        lambda ctx: run_library_refresh(store, ctx, force=force),
        unique=True,
    )
    return {"job_id": job.id}


@router.get("/library/info")
def library_info(request: Request) -> Dict[str, Any]:
    """缓存信息 + 正在进行的扫描任务 + 电影目录存在性。"""
    store = get_store(request)

    scanning = None
    for job in request.app.state.jobs.list(kind=REFRESH_KIND, limit=10):
        if job.status not in _FINISHED:
            scanning = job.to_dict()
            break

    return {
        "cache_info": store.cache_info(),
        "scanning": scanning,
        "paths_exist": [
            {"path": path, "exists": Path(path).exists()}
            for path in store.movie_paths()
        ],
    }


# ─────────────────── 设置 ───────────────────


@router.get("/settings")
def get_settings(request: Request) -> Dict[str, Any]:
    store = get_store(request)
    with store.lock:
        cfg = store.config()
        width, height = cfg.get_poster_size()
        return {
            "movie_paths": cfg.get_movie_paths(),
            "blacklist_folders": cfg.get_blacklist_folders(),
            "blacklist_patterns": cfg.get_blacklist_patterns(),
            "poster_width": width,
            "poster_height": height,
            "grid_columns": cfg.get_grid_columns(),
            "poster_scale": cfg.get_poster_scale(),
        }


@router.put("/settings")
def put_settings(request: Request, payload: SettingsUpdate) -> Dict[str, bool]:
    """部分更新设置（改 movie_paths 后前端应触发 /library/refresh）。"""
    store = get_store(request)
    data = payload.model_dump(exclude_unset=True)

    if data.get("poster_width") is not None and data["poster_width"] < 1:
        raise HTTPException(status_code=400, detail="poster_width 必须大于 0")
    if data.get("poster_height") is not None and data["poster_height"] < 1:
        raise HTTPException(status_code=400, detail="poster_height 必须大于 0")
    if data.get("grid_columns") is not None and data["grid_columns"] < 1:
        raise HTTPException(status_code=400, detail="grid_columns 必须大于 0")
    scale = data.get("poster_scale")
    if scale is not None and not (50 <= scale <= 200):
        raise HTTPException(status_code=400, detail="poster_scale 取值范围 50-200")

    with store.lock:
        cfg = store.config()  # 每次按本 app 数据目录重新加载
        if "movie_paths" in data:
            cfg.set_movie_paths(list(data["movie_paths"] or []))
        if "blacklist_folders" in data:
            cfg.set_value("blacklist_folders", list(data["blacklist_folders"] or []))
        if "blacklist_patterns" in data:
            cfg.set_value("blacklist_patterns", list(data["blacklist_patterns"] or []))
        for key in ("poster_width", "poster_height", "grid_columns"):
            if key in data and data[key] is not None:
                cfg.set_value(key, data[key])
        if "poster_scale" in data and data["poster_scale"] is not None:
            cfg.set_poster_scale(data["poster_scale"])
        cfg.save_config(str(store.config_file))

    return {"saved": True}
