"""完整电影刮削：服务器管理候选/草稿，所有网络及源文件操作在后台执行。"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from scraper.scrape_models import ScrapeError
from .deps import get_store
from .scrape_workspace import ScrapeWorkspace

router = APIRouter(prefix='/scrape')


def get_workspace(request: Request) -> ScrapeWorkspace:
    store = get_store(request)
    with request.app.state.store_lock:
        if not hasattr(request.app.state, 'scrape_workspace'):
            request.app.state.scrape_workspace = ScrapeWorkspace(store)
        return request.app.state.scrape_workspace


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Search(StrictModel):
    source: str = Field(pattern='^(tmdb|douban)$')
    query: str = Field(min_length=1, max_length=500)
    year: str = Field(default='', max_length=4, pattern=r'^\d{0,4}$')
    page: int = Field(default=1, ge=1, le=500)


class Preview(StrictModel):
    target_id: str = Field(max_length=100)
    candidate: str = Field(max_length=100)
    previous: str | None = Field(default=None, max_length=100)


class Confirm(StrictModel):
    plot_source: str = Field(pattern='^(tmdb|douban)$')
    title: str = Field(max_length=1000)
    plot: str = Field(max_length=100000)
    poster_index: int | None = Field(default=None, ge=0)
    rebuild_nfo: bool = False


class Save(StrictModel):
    selected_fields: list[str] = Field(min_length=1, max_length=20)
    overwrite: bool = False
    metadata_only: bool = False
    replace_identity_ack: bool = False


class Edit(StrictModel):
    changes: dict
    votes: dict[str, int] = Field(default_factory=dict)
    poster_base64: str | None = Field(default=None, max_length=14000000)


def job(request: Request, kind: str, action, *, exclusive: bool = False):
    ws = get_workspace(request)
    if exclusive and not ws.operation_lock.acquire(blocking=False):
        raise HTTPException(409, '正在扫描或保存电影，请等待当前操作完成')
    def run(ctx):
        try:
            ctx.check_cancelled()
            return action(ws, ctx)
        except Exception as exc:
            message = str(exc)
            # 上游网络错误可能含 URL 凭据；不得出现在任务状态或日志。
            for secret in (ws.settings().tmdb_api_key, ws.settings().tmdb_token, ws.settings().omdb_api_key):
                if secret:
                    message = message.replace(secret, '***')
            from wall_common.jobs import JobCancelled
            if isinstance(exc, JobCancelled):
                raise
            raise ScrapeError(message[:2000]) from None
        finally:
            if exclusive:
                ws.operation_lock.release()
    try:
        result = request.app.state.jobs.submit('scrape.' + kind, run)
    except Exception:
        if exclusive:
            ws.operation_lock.release()
        raise
    return {'job_id': result.id}


@router.get('/workspace')
def rows(request: Request):
    return {'rows': get_workspace(request).rows()}


@router.post('/workspace/scan')
def scan(request: Request):
    return job(request, 'scan', lambda ws, ctx: ws.scan(ctx), exclusive=True)


@router.get('/settings')
def settings(request: Request):
    return get_workspace(request).public_settings()


@router.put('/settings')
def save_settings(request: Request, payload: dict):
    try:
        return get_workspace(request).save_settings(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, '刮削设置无效，请检查语言、超时、代理和请求间隔') from exc


@router.post('/search')
def search(request: Request, payload: Search):
    return job(request, 'search', lambda ws, ctx: ws.search(**payload.model_dump()))


@router.post('/preview')
def preview(request: Request, payload: Preview):
    return job(request, 'preview', lambda ws, ctx: ws.preview(payload.target_id, payload.candidate, payload.previous))


@router.post('/sessions/{session}/confirm')
def confirm(request: Request, session: str, payload: Confirm):
    return job(request, 'confirm', lambda ws, ctx: ws.confirm(session, payload.model_dump()), exclusive=True)


@router.post('/sessions/{session}/save')
def save(request: Request, session: str, payload: Save):
    return job(request, 'save', lambda ws, ctx: ws.save(session, payload.model_dump()), exclusive=True)


@router.post('/edit/{target_id}')
def edit(request: Request, target_id: str):
    return job(request, 'edit.load', lambda ws, ctx: ws.edit(target_id))


@router.post('/edit/sessions/{session}/save')
def save_edit(request: Request, session: str, payload: Edit):
    return job(request, 'edit.save', lambda ws, ctx: ws.save_editor(session, payload.changes, payload.votes, payload.poster_base64), exclusive=True)
