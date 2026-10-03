"""FastAPI 应用工厂：CORS、健康检查、异常处理、日志。"""
from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import settings as settings_mod
from .images import ImageError
from .jobs import JobCancelled, JobManager

logger = logging.getLogger("wall_common.factory")

DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def settings_of(request: Request) -> settings_mod.Settings:
    """从请求取本 app 的设置（替代进程级单例）。"""
    return request.app.state.settings


def create_app(
    *,
    service: str,
    title: str,
    routers: Sequence[APIRouter],
    version: str = "1.0.0",
    data_dir: Optional[os.PathLike] = None,
    lifespan=None,
) -> FastAPI:
    """
    构建服务应用。

    Args:
        service: "movie" | "game"
        routers: 业务路由（自动加 /api/movie 或 /api/game 前缀）
        data_dir: 显式数据目录（测试传 pytest 临时目录；生产传 None 走环境变量/默认值）
    """
    st = settings_mod.resolve(service, data_dir=data_dir)
    settings_mod.align_app_paths(st.data_dir)
    _setup_logging()

    app = FastAPI(
        title=title,
        version=version,
        docs_url=f"{st.api_prefix}/docs",
        openapi_url=f"{st.api_prefix}/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = st
    app.state.jobs = JobManager(history=st.job_history)

    origins = [
        o.strip()
        for o in os.environ.get("MML_CORS_ORIGINS", DEFAULT_CORS).split(",")
        if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for router in routers:
        app.include_router(router, prefix=st.api_prefix)

    @app.get(f"{st.api_prefix}/health", tags=["system"])
    def health() -> dict:
        return {
            "status": "ok",
            "service": service,
            "version": version,
            "data_dir": str(st.data_dir),
            "active_jobs": app.state.jobs.active_count(),
        }

    # ── 异常处理 ────────────────────────────────────────────
    @app.exception_handler(JobCancelled)
    async def _job_cancelled(_: Request, exc: JobCancelled):
        return JSONResponse(status_code=409, content={"detail": str(exc) or "任务已取消"})

    @app.exception_handler(ImageError)
    async def _image_error(_: Request, exc: ImageError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc.errors())})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

    logger.info("%s 应用已创建 data_dir=%s prefix=%s", service, st.data_dir, st.api_prefix)
    return app


def jobs_router() -> APIRouter:
    """任务查询/取消通用路由（各服务以自己的前缀挂载）。"""
    from .api import build_jobs_router  # noqa: PLC0415

    return build_jobs_router()
