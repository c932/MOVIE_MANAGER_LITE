"""网页 NAS 连接/目录配置；登录和挂载放入可轮询后台任务。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, SecretStr

from .deps import get_store
from .nas import NASManager

router = APIRouter()


class NASConfig(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=445, ge=1, le=65535)
    username: str = Field(default='', max_length=200)
    password: SecretStr | None = None
    domain: str = Field(default='', max_length=200)
    share: str = Field(default='', max_length=100)
    vers: str = Field(default='3.0', pattern=r'^(3\.0|3\.1\.1|2\.1|2\.0)$')
    guest: bool = False


class LibrarySelection(BaseModel):
    connection_id: str = Field(pattern=r'^[a-f0-9]{16}$')
    path: str = Field(default='', max_length=2000)


class Libraries(BaseModel):
    libraries: list[LibrarySelection] = Field(max_length=100)


def manager(request: Request):
    return NASManager(request.app.state.settings.data_dir)


@router.get('/nas')
def nas_status(request: Request):
    try:
        return dict(manager(request).status(), available=True)
    except ValueError as exc:
        from utils.library_sync import read_json
        libraries = read_json(request.app.state.settings.data_dir / 'nas_libraries.json', {}).get('libraries', [])
        return {'available': False, 'connections': [], 'libraries': libraries, 'detail': str(exc)}


def _connection_job(request, payload: NASConfig, action: str):
    value = payload.model_dump(exclude={'password'})
    value['password'] = payload.password.get_secret_value() if payload.password is not None else None
    service = manager(request)
    def run(ctx):
        ctx.update(stage='NAS 连接', message='正在验证 NAS 登录与共享目录…')
        result = service.transport({'action': action, 'config': value})
        if action == 'connect':
            # 仅登记公共路径映射，密码始终只在 root 连接助手内保存。
            from utils.library_sync import atomic_json, read_json
            data = read_json(service.paths.file, {'connections': [], 'libraries': []})
            connections = {item['id']: item for item in data['connections']}
            connections[result['id']] = {key: result[key] for key in ('id', 'host', 'share', 'mount_path', 'read_only')}
            data['connections'] = list(connections.values())
            atomic_json(service.paths.file, data)
        return result
    job = request.app.state.jobs.submit('nas.' + action, run, unique=True)
    return {'job_id': job.id}


@router.post('/nas/shares')
def shares(request: Request, payload: NASConfig):
    return _connection_job(request, payload, 'shares')


@router.post('/nas/connect')
def connect(request: Request, payload: NASConfig):
    return _connection_job(request, payload, 'connect')


@router.post('/nas/{mid}/disconnect')
def disconnect(request: Request, mid: str):
    service = manager(request)
    if request.app.state.jobs.active_count():
        raise HTTPException(409, '请等待当前扫描或连接任务结束后再断开 NAS')
    job = request.app.state.jobs.submit('nas.disconnect', lambda ctx: service.transport({'action': 'disconnect', 'id': mid}), unique=True)
    return {'job_id': job.id}


@router.get('/nas/{mid}/directories')
def directories(request: Request, mid: str, path: str = Query('', max_length=2000)):
    try:
        return manager(request).directories(mid, path)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put('/nas/libraries')
def save_libraries(request: Request, payload: Libraries):
    store = get_store(request)
    if request.app.state.jobs.active_count():
        raise HTTPException(409, '请等待当前扫描或连接任务结束后再修改媒体库目录')
    try:
        with store.lock:
            paths = manager(request).save_libraries([item.model_dump() for item in payload.libraries])
            cfg = store.config()
            cfg.set_movie_paths(paths)
            cfg.save_config(str(store.config_file))
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'saved': True, 'movie_paths': paths}
