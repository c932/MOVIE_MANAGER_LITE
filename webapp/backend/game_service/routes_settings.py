"""
游戏墙设置端点（契约 docs/web_api_contract.md 3.3）。

GET /settings  → store.settings_read()（API key 掩码，不回明文）
PUT /settings  → store.settings_write(payload)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request

from .deps import get_store
from .store import StoreError

logger = logging.getLogger("game_service.routes_settings")

router = APIRouter()


@router.get("/settings")
def get_settings(request: Request) -> Dict[str, Any]:
    """读取设置（API key 只回布尔 + 掩码，绝不回明文）。"""
    store = get_store(request)
    return store.settings_read()


@router.put("/settings")
def put_settings(
    request: Request,
    payload: Dict[str, Any] = Body(..., description="设置项子集"),
) -> Dict[str, bool]:
    """部分更新设置。"""
    store = get_store(request)
    try:
        store.settings_write(payload)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": True}
