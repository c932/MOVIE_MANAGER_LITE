"""
游戏墙后台任务端点（契约 docs/web_api_contract.md 3.2 的异步部分）。

长任务统一走 wall_common.jobs.JobManager：这里只负责提交任务体
（编排逻辑在 game_service.tasks），轮询进度由通用 /jobs 路由负责。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .deps import get_store
from .store import StoreError
from .tasks import (
    ENRICH_KIND,
    EXCEL_APPLY_KIND,
    EXCEL_DIFF_KIND,
    LLM_CLASSIFY_KIND,
    SCAN_INSTALLED_KIND,
    run_enrich,
    run_excel_apply,
    run_excel_diff,
    run_llm_classify,
    run_scan_installed,
)

logger = logging.getLogger("game_service.routes_tasks")

router = APIRouter()


# ─────────────────── 提交前校验 ───────────────────


def _require_excel(store) -> str:
    """Excel 路径已配置且文件存在，否则 400（避免提交后才发现）。"""
    from pathlib import Path

    path = store.excel_path()
    if not path:
        raise HTTPException(status_code=400, detail="未配置 Excel 文件路径")
    if not Path(path).is_file():
        raise HTTPException(status_code=400, detail=f"Excel 文件不存在: {path}")
    return path


def _validate_scope(store, scope: str, keys: Optional[List[str]]) -> Optional[List[str]]:
    """校验 scope/keys；selected 返回归一化去重后的 key 列表，其余返回 None。"""
    from gamewall.name_utils import normalize_name

    if scope not in ("all", "new", "selected"):
        raise HTTPException(
            status_code=400, detail=f"scope 无效: {scope}（应为 all/new/selected）")
    if scope != "selected":
        return None
    normalized: List[str] = []
    for item in keys or []:
        key = normalize_name(str(item or ""))
        if key and key not in normalized:
            normalized.append(key)
    if not normalized:
        raise HTTPException(status_code=400, detail="scope=selected 需要提供 keys")
    existing = set(store.keys())
    unknown = [key for key in normalized if key not in existing]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"以下游戏不存在: {', '.join(unknown[:10])}")
    return normalized


# ─────────────────── 请求体模型 ───────────────────


class EnrichRequest(BaseModel):
    scope: str = "all"          # all | new | selected
    keys: Optional[List[str]] = None
    options: Dict[str, bool] = {}  # steam, ratings


class LLMClassifyRequest(BaseModel):
    scope: str = "all"
    keys: Optional[List[str]] = None


# ─────────────────── Excel 差分 / 应用 ───────────────────


@router.post("/games/excel/diff")
def excel_diff(request: Request) -> Dict[str, str]:
    """检查 Excel 与当前库的差分（kind=excel.diff）。"""
    store = get_store(request)
    _require_excel(store)
    job = request.app.state.jobs.submit(
        EXCEL_DIFF_KIND,
        lambda ctx: run_excel_diff(store, ctx),
        unique=True,
    )
    return {"job_id": job.id}


@router.post("/games/excel/apply")
def excel_apply(request: Request) -> Dict[str, str]:
    """应用 Excel 更新并触发规则分类重算（kind=excel.apply）。"""
    store = get_store(request)
    _require_excel(store)
    job = request.app.state.jobs.submit(
        EXCEL_APPLY_KIND,
        lambda ctx: run_excel_apply(store, ctx),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── 联网补全 ───────────────────


@router.post("/games/enrich")
def enrich(request: Request, payload: EnrichRequest) -> Dict[str, str]:
    """联网补全（kind=enrich）：Steam + 第三方评分。"""
    store = get_store(request)
    selected = _validate_scope(store, payload.scope, payload.keys)
    if not payload.options.get("steam", True) and not payload.options.get("ratings", True):
        raise HTTPException(
            status_code=400, detail="options 至少启用 steam 或 ratings 之一")
    if not store.network_enabled():
        raise HTTPException(
            status_code=400, detail="联网功能已关闭（设置 network_enabled=false）")
    job = request.app.state.jobs.submit(
        ENRICH_KIND,
        lambda ctx: run_enrich(
            store, ctx,
            scope=payload.scope,
            keys=selected if selected is not None else payload.keys,
            options=payload.options,
        ),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── LLM 判定 ───────────────────


@router.post("/games/llm/classify")
def llm_classify(request: Request, payload: LLMClassifyRequest) -> Dict[str, str]:
    """LLM 五档判定（kind=llm.classify）。"""
    store = get_store(request)
    selected = _validate_scope(store, payload.scope, payload.keys)
    try:
        store.llm_config()  # 提前校验，避免提交后才发现没配置
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = request.app.state.jobs.submit(
        LLM_CLASSIFY_KIND,
        lambda ctx: run_llm_classify(
            store, ctx,
            scope=payload.scope,
            keys=selected if selected is not None else payload.keys,
        ),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── 本地扫描 ───────────────────


@router.post("/games/scan-installed")
def scan_installed(request: Request) -> Dict[str, str]:
    """扫描 game_dirs 中的 exe/.lnk 匹配已安装（kind=install.scan）。"""
    store = get_store(request)
    if not store.game_dirs():
        raise HTTPException(status_code=400, detail="未配置游戏目录（设置 game_dirs）")
    job = request.app.state.jobs.submit(
        SCAN_INSTALLED_KIND,
        lambda ctx: run_scan_installed(store, ctx),
        unique=True,
    )
    return {"job_id": job.id}
