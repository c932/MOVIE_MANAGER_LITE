"""
后台任务管理器

桌面版用 QThread + 信号上报进度；网页版改为：
- submit(kind, fn) 启动守护线程执行 fn(ctx)
- 前端轮询 GET {prefix}/jobs/{id} 获取进度与结果
- ctx.check_cancelled() 支持协作式取消（长任务应定期调用）
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("wall_common.jobs")

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

_FINISHED = (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED)


class JobCancelled(Exception):
    """任务被用户取消（由 ctx.check_cancelled() 抛出）。"""


@dataclass
class Job:
    id: str
    kind: str
    status: str = STATUS_QUEUED
    stage: str = ""
    message: str = ""
    current: int = 0
    total: int = 0
    error: Optional[str] = None
    result: Any = None
    logs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    LOG_LIMIT = 300

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "error": self.error,
            "result": self.result,
            "logs": list(self.logs),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobContext:
    """传给任务函数的上下文：进度上报 + 取消检查。"""

    def __init__(self, job: Job):
        self._job = job

    @property
    def job_id(self) -> str:
        return self._job.id

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self._job.cancel_event.is_set():
            raise JobCancelled()

    def update(self, *, current: Optional[int] = None, total: Optional[int] = None,
               stage: Optional[str] = None, message: Optional[str] = None) -> None:
        job = self._job
        if current is not None:
            job.current = current
        if total is not None:
            job.total = total
        if stage is not None:
            job.stage = stage
        if message is not None:
            job.message = message

    def log(self, message: str) -> None:
        """追加一条日志，同时作为当前消息展示。"""
        job = self._job
        job.logs.append(message)
        if len(job.logs) > Job.LOG_LIMIT:
            del job.logs[: len(job.logs) - Job.LOG_LIMIT]
        job.message = message
        logger.info("[%s] %s", job.kind, message)


class JobManager:
    """进程内任务管理：提交、查询、取消、清理历史。"""

    def __init__(self, history: int = 60):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._history = history

    # ── 提交 ────────────────────────────────────────────────
    def submit(self, kind: str, fn: Callable[[JobContext], Any], *,
               unique: bool = False) -> Job:
        """
        提交任务。

        Args:
            kind: 任务类型（如 "library.refresh"）
            fn:   任务体，接收 JobContext，返回值作为 job.result
            unique: 同 kind 若有未完成任务则直接复用，避免重复提交
        """
        with self._lock:
            if unique:
                for job in self._jobs.values():
                    if job.kind == kind and job.status not in _FINISHED:
                        return job
            self._prune_locked()
            job = Job(id=f"j_{uuid.uuid4().hex[:10]}", kind=kind)
            self._jobs[job.id] = job

        worker = threading.Thread(
            target=self._run, args=(job, fn),
            name=f"job-{kind}-{job.id}", daemon=True,
        )
        worker.start()
        return job

    def _run(self, job: Job, fn: Callable[[JobContext], Any]) -> None:
        job.status = STATUS_RUNNING
        job.started_at = time.time()
        ctx = JobContext(job)
        try:
            result = fn(ctx)
            if job.cancel_event.is_set():
                job.status = STATUS_CANCELLED
            else:
                job.result = result
                job.status = STATUS_DONE
        except JobCancelled:
            job.status = STATUS_CANCELLED
            job.message = "任务已取消"
            job.logs.append("任务已取消")
        except Exception as exc:  # noqa: BLE001  任务体的任何异常都要落盘
            job.status = STATUS_ERROR
            job.error = f"{type(exc).__name__}: {exc}"
            logger.error("任务 %s(%s) 失败: %s\n%s",
                         job.id, job.kind, job.error, traceback.format_exc())
        finally:
            job.finished_at = time.time()

    # ── 查询 / 取消 ─────────────────────────────────────────
    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, kind: Optional[str] = None, limit: int = 20) -> List[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        return jobs[:limit]

    def cancel(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status in _FINISHED:
            return job
        job.cancel_event.set()
        return job

    def wait(self, job_id: str, timeout: float = 30.0) -> Optional[Job]:
        """测试辅助：等待任务结束。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(job_id)
            if job is None:
                return None
            if job.status in _FINISHED:
                return job
            time.sleep(0.05)
        return self.get(job_id)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status not in _FINISHED)

    # ── 清理 ────────────────────────────────────────────────
    def _prune_locked(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in _FINISHED]
        if len(finished) <= self._history:
            return
        finished.sort(key=lambda j: j.finished_at or j.created_at)
        for job in finished[: len(finished) - self._history]:
            self._jobs.pop(job.id, None)
