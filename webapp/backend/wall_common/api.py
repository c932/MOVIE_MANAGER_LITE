"""通用任务路由：列表 / 详情 / 取消。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from .jobs import JobManager


def build_jobs_router() -> APIRouter:
    router = APIRouter(tags=["jobs"])

    def _mgr(request: Request) -> JobManager:
        return request.app.state.jobs

    @router.get("/jobs")
    def list_jobs(request: Request, kind: Optional[str] = None, limit: int = 20):
        """按创建时间倒序返回最近任务（用于页面刷新后恢复进度条）。"""
        limit = max(1, min(limit, 100))
        return {"jobs": [j.to_dict() for j in _mgr(request).list(kind=kind, limit=limit)]}

    @router.get("/jobs/{job_id}")
    def get_job(request: Request, job_id: str):
        job = _mgr(request).get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job.to_dict()

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(request: Request, job_id: str):
        job = _mgr(request).cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job.to_dict()

    return router
