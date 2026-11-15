"""有效像素尺寸优先，缺失技术资料时从视频文件名补全；不访问文件系统。"""
from __future__ import annotations

import ntpath
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.movie import Movie


def resolution_from_dimensions(width: object, height: object) -> str:
    try:
        w, h = int(width), int(height)
    except (ValueError, TypeError, OverflowError):
        return ''
    if w <= 0 or h <= 0:
        return ''
    if w >= 7680 or h >= 4320:
        return '8K'
    if w >= 3840 or h >= 2160:
        return '4K'
    if w >= 2048 or h >= 1440:
        return '2K'
    if w >= 1920 or h >= 1080:
        return '1080p'
    if w >= 1280 or h >= 720:
        return '720p'
    return '480p' if h == 480 else '576p' if h == 576 else 'SD'


def technical_from_filename(path: str) -> tuple[str, str]:
    name = ntpath.basename(str(path).replace('/', '\\'))
    matches = re.findall(r'(?i)(?<![a-z0-9])(4320p|2160p|1440p|1080[pi]|720[pi]|576p|480p|[248]k)(?![a-z0-9])', name)
    aliases = {'4320p':'8K','8k':'8K','2160p':'4K','4k':'4K','1440p':'2K','2k':'2K',
               '1080i':'1080p','720i':'720p'}
    resolution = aliases.get(matches[0].lower(), matches[0].lower()) if matches else ''
    formats = []
    for item in re.findall(r'(?i)(?<![a-z0-9])(dolby[ ._-]*vision|dovi|dv|hdr10\+?|hdr|hlg)(?![a-z0-9])', name):
        value = 'Dolby Vision' if re.sub(r'[ ._-]','',item).lower() in {'dolbyvision','dovi','dv'} else item.upper()
        if value not in formats:
            formats.append(value)
    return resolution, ' / '.join(formats)


def normalize_movie_technical(movie: Movie) -> None:
    verified = resolution_from_dimensions(movie.video_width, movie.video_height)
    inferred, hdr = technical_from_filename(movie.video_path or movie.nfo_path)
    if verified:
        movie.resolution = verified
    elif not movie.resolution or movie.resolution.upper() == 'SD':
        movie.resolution = inferred or movie.resolution
    if not movie.hdr_type:
        movie.hdr_type = hdr
