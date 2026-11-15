"""共享电影资料协议与独立海报副本；不接受任意服务端文件路径。"""
from __future__ import annotations

import hashlib
import math
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from utils.library_sync import movie_key
from .deps import get_store

router = APIRouter()


class Change(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9]{16}$')
    base: dict[str, Any] | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    deleted: bool = False


class Push(BaseModel):
    server_id: str = ''
    changes: list[Change] = Field(max_length=20000)


def assets_dir(request: Request) -> Path:
    path = request.app.state.settings.data_dir / 'shared_posters'
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get('/sync/changes')
def changes(request: Request, since: int = Query(0, ge=0)) -> dict:
    store = get_store(request)
    with store.lock:
        store.ensure_loaded()
        return store.database.snapshot(since)


@router.post('/sync/push')
def push(request: Request, payload: Push) -> dict:
    store = get_store(request)
    with store.lock:
        store.ensure_loaded()
        sid = store.database.info()['server_id']
        if payload.server_id and payload.server_id != sid:
            raise HTTPException(409, '后端数据库已更换，请重新下载后同步')
        for change in payload.changes:
            from models.movie import Movie
            from utils.cache_manager import CacheManager
            if set(change.data) - set(Movie.__dataclass_fields__) - {'_favorite'}:
                raise HTTPException(422, '同步仅接受电影资料字段，不接受配置或凭据')
            try:
                validated = TypeAdapter(Movie).validate_python(change.data)
                clean = CacheManager()._serialize_movie(validated)
                for key in set(change.data) - {'_favorite'}:
                    change.data[key] = clean[key]
                if '_favorite' in change.data and not isinstance(change.data['_favorite'], bool):
                    raise ValueError('收藏状态必须为布尔值')
                if 'ratings' in change.data:
                    ratings = TypeAdapter(dict[str, float]).validate_python(change.data['ratings'])
                    for source, value in ratings.items():
                        # TMM 的烂番茄等来源使用百分制；只约束已知十分制来源。
                        maximum = 10 if source.casefold() in {'tmdb', 'imdb', 'douban', 'user'} else None
                        if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
                            raise ValueError(f'ratings.{source}={value} 不符合该来源评分范围')
                    change.data['ratings'] = ratings
                if any(not math.isfinite(change.data[key]) for key in ('rating', 'added_time') if key in change.data):
                    raise ValueError('评分与加入时间必须为有效数值')
            except (ValidationError, ValueError, TypeError, KeyError) as exc:
                label = str(change.data.get('title') or change.id)[:80]
                if isinstance(exc, ValidationError):
                    issue = exc.errors()[0]
                    reason = '.'.join(str(part) for part in issue['loc']) + ' 字段类型无效'
                elif isinstance(exc, KeyError):
                    reason = f'字段 {exc.args[0]} 无法保存'
                else:
                    reason = str(exc)[:160]
                raise HTTPException(422, f'电影「{label}」资料格式无效：{reason}') from exc
            if not change.deleted and change.base is None:
                if not change.data.get('nfo_path') or movie_key(change.data['nfo_path']) != change.id:
                    raise HTTPException(422, '新电影缺少有效 NFO 标识')
            if 'nfo_path' in change.data and movie_key(change.data['nfo_path']) != change.id:
                raise HTTPException(422, '不可在同步中更改电影标识')
        result = store.database.push([change.model_dump() for change in payload.changes])
        store.ensure_loaded()
        return dict(result, server_id=sid)


@router.get('/sync/assets')
def manifest(request: Request) -> dict:
    return {path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in assets_dir(request).glob('*.jpg')}


@router.get('/sync/assets/{mid}')
def get_asset(request: Request, mid: str):
    from .deps import require_movie
    require_movie(get_store(request), mid)
    path = assets_dir(request) / f'{mid}.jpg'
    if not path.is_file():
        raise HTTPException(404, '后端尚无此电影的海报副本')
    return FileResponse(path, media_type='image/jpeg')


@router.put('/sync/assets/{mid}')
async def put_asset(request: Request, mid: str):
    from .deps import require_movie
    store = get_store(request)
    require_movie(store, mid)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 8 * 1024 * 1024:
            raise HTTPException(413, '海报不能超过 8 MB')
        chunks.append(chunk)
    payload = b''.join(chunks)
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError('图片过大')
            image.verify()
    except Exception as exc:
        raise HTTPException(422, '海报不是有效图片') from exc
    dest = assets_dir(request) / f'{mid}.jpg'
    with store.lock:
        current = hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else ''
        expected = request.headers.get('If-Match', '')
        digest = hashlib.sha256(payload).hexdigest()
        if current and current != digest and expected != current:
            raise HTTPException(409, '海报已在其他客户端更新，保留服务器海报')
        fd, name = tempfile.mkstemp(dir=dest.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
            os.replace(name, dest)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return {'sha256': digest}
