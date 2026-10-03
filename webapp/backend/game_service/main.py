"""
游戏墙 Web 服务入口。

注意：第一行必须设置 APP_DIR_NAME_OVERRIDE（与 game_main.py 一致），
必须早于任何 utils.* 导入，保证数据目录解析到游戏墙自己的目录。

启动（仓库根目录）：
    MML_DATA_DIR=/var/lib/game-wall \
    PYTHONPATH=".:webapp/backend" \
    uvicorn game_service.main:app --host 127.0.0.1 --port 8011
"""
import os

os.environ.setdefault("APP_DIR_NAME_OVERRIDE", "LocalGameWall")

import logging  # noqa: E402
import threading  # noqa: E402
from typing import Optional  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from wall_common.factory import create_app, jobs_router  # noqa: E402

logger = logging.getLogger("game_service.main")

# Starlette/FastAPI 默认英文 detail → 中文（契约：错误统一 {"detail": 中文}）
_HTTP_DETAIL_TRANSLATIONS = {
    "Not Found": "接口不存在",
    "Method Not Allowed": "请求方法不允许",
}


def _register_error_handlers(app: FastAPI) -> None:
    """覆盖工厂的默认异常处理，保证游戏墙错误一律中文 detail。"""
    from gamewall.steam_client import SteamCancelled

    from .store import StoreError

    @app.exception_handler(StoreError)
    async def _store_error(_: Request, exc: StoreError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(SteamCancelled)
    async def _steam_cancelled(_: Request, exc: SteamCancelled):
        return JSONResponse(status_code=409, content={"detail": "任务已取消"})

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(_: Request, exc: StarletteHTTPException):
        detail: object = exc.detail
        if isinstance(detail, str):
            detail = _HTTP_DETAIL_TRANSLATIONS.get(detail, detail)
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": detail},
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": f"请求参数校验失败: {exc.errors()}"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"服务内部错误：{type(exc).__name__}: {exc}"},
        )


def create(data_dir: Optional[str] = None) -> FastAPI:
    """构建游戏墙应用（测试传入临时数据目录）。"""
    from .router import router

    app = create_app(
        service="game",
        title="Game Wall API",
        routers=[router, jobs_router()],
        data_dir=data_dir,
    )
    # 有状态对象只挂 app 实例（绝不放模块导入期；与 movie_service 一致）：
    # store 由 deps.get_store() 懒初始化，多 app/多数据目录互不干扰
    app.state.store = None
    app.state.store_lock = threading.Lock()
    _register_error_handlers(app)
    return app


app = create()
