"""按已入库电影管理字幕，候选与压缩包内容均须确认后才写入源目录。"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from utils.subtitle_sources import SiteCheck, candidate_url, download_subtitles, search_subtitles
from utils.subtitles import (LANGUAGES, MAX_PACKAGE, SubtitleError, SubtitleFile, archive_subtitles,
                             detect_subtitles, save_subtitle, sync_subtitles)
from .deps import detail_dto, get_store, require_movie
from .nas import NASManager, NASPaths
from .routes_scrape_workspace import get_workspace
from .tasks import REFRESH_KIND

router = APIRouter(prefix='/movies/{movie_id}/subtitles')


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class Download(BaseModel):
    source: str
    id: str = Field(max_length=60)
    language: str = Field(default='', max_length=12)


class Save(BaseModel):
    token: str = Field(pattern=r'^[0-9a-f]{32}$')
    index: int = Field(ge=0, lt=80)
    language: str = Field(max_length=12)


@dataclass
class Draft:
    movie_id: str
    tracks: list[SubtitleFile]
    expires: float
    size: int


class Drafts:
    def __init__(self):
        self.entries: dict[str, Draft] = {}
        self.lock = Lock()

    def add(self, movie_id: str, tracks: list[SubtitleFile]) -> dict:
        token = uuid4().hex
        size = sum(len(track.data) for track in tracks)
        with self.lock:
            now = monotonic()
            self.entries = {key: draft for key, draft in self.entries.items() if draft.expires > now}
            limit = 160 * 1024 * 1024
            available = limit - sum(draft.size for draft in self.entries.values())
            while self.entries and (len(self.entries) >= 6 or available < size):
                available += self.entries.pop(next(iter(self.entries))).size
            self.entries[token] = Draft(movie_id, tracks, now + 900, size)
        return {'token': token, 'tracks': [{'name': t.name, 'language': t.language} for t in tracks]}

    def get(self, movie_id: str, payload: Save) -> SubtitleFile:
        with self.lock:
            draft = self.entries.get(payload.token)
            if not draft or draft.expires <= monotonic() or draft.movie_id != movie_id:
                raise SubtitleError('字幕预览已过期，请重新准备文件')
            if payload.index >= len(draft.tracks):
                raise SubtitleError('请选择有效的字幕文件')
            return draft.tracks[payload.index]


def _drafts(request: Request) -> Drafts:
    get_store(request)
    with request.app.state.store_lock:
        if not hasattr(request.app.state, 'subtitle_drafts'):
            request.app.state.subtitle_drafts = Drafts()
        return request.app.state.subtitle_drafts


def _source_files(store, movie, *, writing: bool) -> tuple[Path, Path]:
    mapper = NASPaths(store.settings.data_dir)
    video = Path(mapper.source(movie.video_path)).resolve()
    nfo = Path(mapper.source(movie.nfo_path)).resolve()
    roots = [Path(path).resolve() for path in store.movie_paths()]
    if not movie.video_path or not movie.nfo_path or not any(
            video.is_relative_to(root) and nfo.is_relative_to(root) for root in roots):
        raise SubtitleError('电影源文件不在已配置的媒体目录中')
    if video.parent != nfo.parent:
        raise SubtitleError('电影与 NFO 须位于同一目录')
    for mapping in mapper.mappings():
        if not (video.is_relative_to(mapping['mount_path']) or nfo.is_relative_to(mapping['mount_path'])):
            continue
        connection = NASManager(store.settings.data_dir).connection(mapping['id'])
        if not connection['connected']:
            raise SubtitleError('NAS 未连接，请在设置中连接后重试')
        if writing and connection['read_only']:
            raise SubtitleError('NAS 共享为只读，请在设置中启用写入后重试')
    if not video.is_file() or not nfo.is_file():
        raise SubtitleError('电影或 NFO 不可访问')
    if writing and not all(os.access(path, os.W_OK) for path in {video.parent, nfo.parent, nfo}):
        raise SubtitleError('电影目录或 NFO 不可写')
    return video, nfo


@router.post('/search')
def search(request: Request, movie_id: str, payload: Search):
    movie = require_movie(get_store(request), movie_id)
    query = payload.query.strip()
    if not query:
        raise HTTPException(400, '请输入片名或字幕关键字')
    filename = Path(movie.video_path.replace('\\', '/')).stem
    original = movie.original_title if query == movie.title else ''
    return search_subtitles(query, filename, original)


@router.post('/download')
def download(request: Request, movie_id: str, payload: Download):
    require_movie(get_store(request), movie_id)
    try:
        page = candidate_url(payload.source, payload.id)
        tracks = download_subtitles(payload.source, payload.id, payload.language)
        return _drafts(request).add(movie_id, tracks)
    except SiteCheck as exc:
        return {'verification_url': page, 'message': str(exc)}
    except SubtitleError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/import')
def import_file(request: Request, movie_id: str, file: UploadFile = File(...)):
    require_movie(get_store(request), movie_id)
    try:
        tracks = archive_subtitles(file.filename or '', file.file.read(MAX_PACKAGE + 1))
        return _drafts(request).add(movie_id, tracks)
    except SubtitleError as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        file.file.close()


def _update(request: Request, movie_id: str, action, *, writing: bool):
    workspace = get_workspace(request)
    store = workspace.store
    jobs = request.app.state.jobs
    if any(j.status in {'queued', 'running'} and j.kind in {REFRESH_KIND, 'nas.connect', 'nas.disconnect'}
           for j in jobs.list(limit=60)):
        raise HTTPException(409, '请等待媒体库扫描或 NAS 操作完成')
    if not workspace.operation_lock.acquire(blocking=False):
        raise HTTPException(409, '正在扫描或保存电影，请等待当前操作完成')

    def run(ctx):
        try:
            ctx.check_cancelled()
            with store.lock:
                movie = require_movie(store, movie_id)
                video, nfo = _source_files(store, movie, writing=writing)
                name, tracks = action(video, nfo)
                if movie.subtitles != tracks:
                    movie.subtitles = tracks
                    store.save_cache()
                return {'movie': detail_dto(store, movie), 'saved_name': name}
        except (OSError, ValueError) as exc:
            from scraper.scrape_models import ScrapeError
            raise ScrapeError(str(exc)) from None
        finally:
            workspace.operation_lock.release()

    try:
        job = jobs.submit('subtitles.update', run)
    except Exception:
        workspace.operation_lock.release()
        raise
    return {'job_id': job.id}


@router.post('/detect')
def detect(request: Request, movie_id: str):
    return _update(request, movie_id, lambda video, nfo: ('', detect_subtitles(video, nfo)), writing=False)


@router.post('/sync')
def sync(request: Request, movie_id: str):
    return _update(request, movie_id, lambda video, nfo: ('', sync_subtitles(video, nfo)), writing=True)


@router.post('/save')
def save(request: Request, movie_id: str, payload: Save):
    if payload.language not in LANGUAGES:
        raise HTTPException(400, '请选择有效的字幕语言')
    try:
        track = _drafts(request).get(movie_id, payload)
    except SubtitleError as exc:
        raise HTTPException(409, str(exc)) from None
    def update(video: Path, nfo: Path):
        path = save_subtitle(video, nfo, track, payload.language)
        return path.name, detect_subtitles(video, nfo)
    return _update(request, movie_id, update, writing=True)
