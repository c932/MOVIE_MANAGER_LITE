"""
游戏墙 API 路由聚合器。

所有路径自动带 /api/game 前缀（由 wall_common.factory.create_app 挂载）。
实现规范见 docs/web_api_contract.md 第 3 节，按职责拆分为：

- routes_games.py    列表/详情/编辑/tier/cover/steam/llm 同步端点（3.1–3.2）
- routes_tasks.py    Excel 差分/应用、联网补全、LLM 判定、本地扫描（后台任务）
- routes_settings.py 设置读写（3.3）
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request

from .routes_games import router as games_router
from .routes_settings import router as settings_router
from .routes_tasks import router as tasks_router

router = APIRouter(tags=["game"])

router.include_router(games_router)
router.include_router(tasks_router)
router.include_router(settings_router)


@router.get("/system/info")
def system_info(request: Request) -> Dict[str, Any]:
    """服务端能力自检。"""
    st = request.app.state.settings
    return {
        "service": "game",
        "data_dir": str(st.data_dir),
    }
