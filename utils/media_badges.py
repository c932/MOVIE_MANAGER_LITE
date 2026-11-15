"""两端共用的技术图标目录；未知格式保留原值，不推测视频能力。"""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import sys


def asset_root() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'logo' / 'media-badges'


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((asset_root() / 'manifest.json').read_text(encoding='utf-8'))


@dataclass(frozen=True)
class MediaBadge:
    key: str
    title: str
    file: str = ''


def media_badges(resolution: str = '', hdr_type: str = '') -> list[MediaBadge]:
    result: list[MediaBadge] = []
    value = re.sub(r'[\s_-]', '', resolution.lower())
    if resolution:
        entry = next(((key, info) for key, info in manifest()['resolution'].items()
                      if value in info['aliases']), None)
        result.append(MediaBadge(entry[0], resolution, entry[1]['file']) if entry
                      else MediaBadge('resolution', resolution))
    hdr = hdr_type.lower()
    compact = re.sub(r'[\s._-]', '', hdr)
    dv = 'dolbyvision' in compact or 'dovi' in compact or bool(re.search(r'\bdv\b', hdr))
    is_hdr = 'hdr' in compact or 'hlg' in compact
    if is_hdr:
        result.append(MediaBadge('hdr', hdr_type, manifest()['hdr']['file']))
    if dv:
        result.append(MediaBadge('dolbyvision', hdr_type, manifest()['dolbyvision']['file']))
    if hdr_type and not (dv or is_hdr):
        result.append(MediaBadge('dynamic-range', hdr_type))
    return result
