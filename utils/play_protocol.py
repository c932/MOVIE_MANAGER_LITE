"""浏览器到 Windows 默认视频播放器的最小协议桥，不执行命令或脚本。"""
from __future__ import annotations
import ntpath
import os
import re
from urllib.parse import parse_qs, urlsplit

VIDEO_SUFFIXES = {'.mkv', '.mp4', '.avi', '.mov', '.m2ts', '.ts', '.wmv', '.webm', '.mpg', '.mpeg', '.iso', '.flv', '.m4v'}


def video_path_from_url(url: str) -> str:
    if len(url) > 32768:
        raise ValueError('播放链接过长')
    parsed = urlsplit(url)
    if parsed.scheme != 'moviewall' or parsed.netloc != 'play' or parsed.path not in {'', '/'} or parsed.fragment:
        raise ValueError('播放链接格式无效')
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {'path'} or len(query['path']) != 1:
        raise ValueError('播放链接只允许一个视频路径')
    path = query['path'][0]
    if any(ord(character) < 32 for character in path) or '"' in path or path.startswith(('\\\\?\\', '\\\\.\\')):
        raise ValueError('视频路径含有不支持的字符或设备路径')
    drive, tail = ntpath.splitdrive(path)
    if not (re.fullmatch(r'[A-Za-z]:', drive) and tail.startswith(('\\', '/')) or drive.startswith(('\\\\', '//')) and tail.startswith(('\\', '/'))):
        raise ValueError('请使用完整本地视频路径或 NAS 共享路径')
    if ntpath.splitext(path)[1].lower() not in VIDEO_SUFFIXES:
        raise ValueError('此链接不是受支持的视频文件')
    return path


def play_url(url: str, opener=None) -> None:
    path = video_path_from_url(url)
    if opener is None:
        if os.name != 'nt':
            raise ValueError('本地播放桥当前适用于 Windows 客户端')
        if not os.path.isfile(path):
            raise ValueError('无法访问视频，请确认本机已连接 NAS 并具有该共享的读取权限')
        opener = os.startfile
    opener(path)
