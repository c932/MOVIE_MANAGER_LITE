"""可下载的 UTF-8 播放列表，让本机播放器直接读取原始 UNC 视频。"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from utils.play_protocol import video_path_from_url
from .deps import get_store, require_movie
from .nas import NASPaths

router = APIRouter()


@router.get('/movies/{mid}/playlist.m3u8')
def playlist(request: Request, mid: str) -> Response:
    store = get_store(request)
    movie = require_movie(store, mid)
    path = NASPaths(store.settings.data_dir).canonical(movie.video_path or '')
    try:
        video_path_from_url('moviewall://play?path=' + quote(path, safe=''))
    except ValueError as exc:
        raise HTTPException(400, '该电影缺少本机可播放的 Windows / NAS 视频路径，请先更新 NFO') from exc
    title = ''.join(char for char in movie.title if ord(char) >= 32)
    data = f'#EXTM3U\r\n#EXTINF:-1,{title}\r\n{path}\r\n'.encode('utf-8')
    filename = quote((title[:80] or 'movie') + '.m3u8', safe='')
    return Response(data, media_type='application/vnd.apple.mpegurl', headers={
        'Content-Disposition': f'attachment; filename="movie.m3u8"; filename*=UTF-8\'\'{filename}',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })
