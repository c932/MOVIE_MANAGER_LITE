"""
电影墙 API 路由聚合器。

所有路径自动带 /api/movie 前缀（由 wall_common.factory.create_app 挂载）。
实现规范见 docs/web_api_contract.md 第 2 节，按职责拆分为：

- routes_movies.py  电影列表/详情/状态/NFO/字段（2.1–2.3）
- routes_library.py 媒体库刷新与设置（2.2 /library/*、2.4）
- routes_fetch.py   刮削/榜单/新片/图片代理（2.2、2.5、2.6）
"""
from __future__ import annotations

import shutil
from typing import Any, Dict

from fastapi import APIRouter, Request

from .routes_fetch import router as fetch_router
from .routes_library import router as library_router
from .routes_movies import router as movies_router
from .routes_sync import router as sync_router
from .routes_nas import router as nas_router
from .routes_scrape_workspace import router as workspace_router
from .routes_playback import router as playback_router

router = APIRouter(tags=["movie"])

router.include_router(movies_router)
router.include_router(library_router)
router.include_router(fetch_router)
router.include_router(sync_router)
router.include_router(nas_router)
router.include_router(workspace_router)
router.include_router(playback_router)


@router.get("/system/info")
def system_info(request: Request) -> Dict[str, Any]:
    """服务端能力自检（Node 可用性决定豆瓣刮削是否可用）。"""
    st = request.app.state.settings
    from pathlib import Path
    from .deps import get_store
    paths = get_store(request).movie_paths()
    connected = set()
    try:
        from .nas import NASManager
        nas = NASManager(st.data_dir).status()
        connected = {item['id'] for item in nas['connections'] if item['connected']}
        nas_libraries = nas['libraries']
        nas_ready = bool(nas_libraries) and all(item['connection_id'] in connected for item in nas_libraries)
    except ValueError:
        from utils.library_sync import read_json
        nas_libraries = read_json(st.data_dir / 'nas_libraries.json', {}).get('libraries', [])
        nas_ready = False
    return {
        "service": "movie",
        "node": shutil.which("node") is not None,
        "npx": shutil.which("npx") is not None,
        "data_dir": str(st.data_dir),
        "source_available": nas_ready if nas_libraries else bool(paths) and all(Path(path).is_dir() for path in paths),
        "nas_configured": bool(nas_libraries),
        "nas_connected": bool(connected),
        "nas_connected_count": len(connected),
        "nas_library_count": len(nas_libraries),
        "sync": True,
    }
