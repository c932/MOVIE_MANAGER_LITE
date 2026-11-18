"""哔哩哔哩搜索与本机客户端启动桥。"""
from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

SEARCH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
SEARCH_PAGE = 'https://search.bilibili.com/video'
SEARCH_API = 'https://api.bilibili.com/x/web-interface/search/type'
VIDEO_WEB = 'https://www.bilibili.com/video/'

_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def movie_query(title: str, original_title: str = '', year: str = '', *, play: bool = False) -> str:
    values = [str(title or '').strip()]
    original = str(original_title or '').strip()
    if original and original.casefold() != values[0].casefold():
        values.append(original)
    if str(year or '').strip():
        values.append(str(year).strip())
    if play:
        values.append('电影')
    seen = set()
    unique = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return ' '.join(unique)


def search_web_url(keyword: str) -> str:
    query = urllib.parse.urlencode({'keyword': keyword, 'order': 'click'})
    return f'{SEARCH_PAGE}?{query}'


def search_player_uri(keyword: str) -> str:
    return 'bilibili://search?' + urllib.parse.urlencode({'keyword': keyword})


def video_web_url(bvid: str) -> str:
    return VIDEO_WEB + urllib.parse.quote(bvid, safe='')


def video_player_uri(bvid: str) -> str:
    return 'bilibili://video/' + urllib.parse.quote(bvid, safe='')


def _plain_text(value: object) -> str:
    text = html.unescape(re.sub(r'<[^>]+>', '', str(value or '')))
    return re.sub(r'\s+', ' ', text).strip()


def search_videos(keyword: str, limit: int = 8) -> list[dict]:
    """通过搜索结果页取得匿名 Cookie，再调用视频搜索接口。"""
    keyword = keyword.strip()
    if not keyword:
        return []
    cache_key = f'{keyword.casefold()}:{limit}'
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and time.time() - cached[0] < 1800:
            return [dict(item) for item in cached[1]]

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page_url = search_web_url(keyword)
    with opener.open(urllib.request.Request(page_url, headers=SEARCH_HEADERS), timeout=15) as response:
        response.read(512 * 1024)
    api_query = urllib.parse.urlencode({
        'search_type': 'video',
        'keyword': keyword,
        'page': 1,
        'page_size': max(1, min(limit, 20)),
    })
    with opener.open(urllib.request.Request(
        f'{SEARCH_API}?{api_query}',
        headers={**SEARCH_HEADERS, 'Referer': 'https://search.bilibili.com/'},
    ), timeout=15) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode('utf-8'))
    if payload.get('code') != 0:
        raise ValueError(f"B站搜索失败: {payload.get('message') or payload.get('code')}")

    results = []
    for item in (payload.get('data') or {}).get('result') or []:
        bvid = str(item.get('bvid') or '').strip()
        if not re.fullmatch(r'BV[0-9A-Za-z]+', bvid):
            continue
        results.append({
            'bvid': bvid,
            'title': _plain_text(item.get('title')),
            'author': _plain_text(item.get('author')),
            'play': int(item.get('play') or 0),
            'description': _plain_text(item.get('description')),
            'pic': str(item.get('pic') or ''),
            'url': video_web_url(bvid),
            'player_uri': video_player_uri(bvid),
        })
        if len(results) >= limit:
            break
    with _cache_lock:
        _cache[cache_key] = (time.time(), [dict(item) for item in results])
    return results


def _normalized(value: str) -> str:
    return re.sub(r'[\W_]+', '', value.casefold(), flags=re.UNICODE)


def find_play_video(title: str, original_title: str = '', year: str = '') -> dict | None:
    keyword = movie_query(title, original_title, year, play=True)
    results = search_videos(keyword)
    if not results:
        return None
    wanted = [value for value in (_normalized(title), _normalized(original_title)) if value]
    ranked = []
    for index, item in enumerate(results):
        candidate = _normalized(item['title'])
        score = sum(4 if value in candidate else 0 for value in wanted)
        if year and str(year) in item['title']:
            score += 2
        if '电影' in item['title'] or '完整' in item['title']:
            score += 1
        ranked.append((score, -index, item))
    ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return ranked[0][2] if ranked[0][0] > 0 else results[0]


def _protocol_registered() -> bool:
    if os.name != 'nt':
        return False
    try:
        import winreg
        for root, path in (
            (winreg.HKEY_CURRENT_USER, r'Software\Classes\bilibili'),
            (winreg.HKEY_CLASSES_ROOT, 'bilibili'),
        ):
            try:
                with winreg.OpenKey(root, path):
                    return True
            except OSError:
                continue
    except ImportError:
        return False
    return False


def _candidate_executables() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)'):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / 'bilibili' / '哔哩哔哩.exe')
            candidates.append(Path(base) / 'Programs' / 'bilibili' / '哔哩哔哩.exe')
    if os.name == 'nt':
        try:
            import winreg
            uninstall_paths = (
                (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
                (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
                (winreg.HKEY_LOCAL_MACHINE, r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            )
            for root, base_path in uninstall_paths:
                try:
                    with winreg.OpenKey(root, base_path) as base_key:
                        for index in range(winreg.QueryInfoKey(base_key)[0]):
                            try:
                                with winreg.OpenKey(base_key, winreg.EnumKey(base_key, index)) as app_key:
                                    name = str(winreg.QueryValueEx(app_key, 'DisplayName')[0] or '')
                                    if not re.search(r'bilibili|哔哩哔哩', name, re.IGNORECASE):
                                        continue
                                    for value_name in ('DisplayIcon', 'InstallLocation'):
                                        try:
                                            value = str(winreg.QueryValueEx(app_key, value_name)[0] or '')
                                        except OSError:
                                            continue
                                        raw = value.split(',', 1)[0].strip().strip('"')
                                        path = Path(raw)
                                        if path.suffix.lower() == '.exe':
                                            candidates.append(path)
                                        for filename in ('哔哩哔哩.exe', 'bilibili.exe'):
                                            candidates.append(path / filename)
                            except OSError:
                                continue
                except OSError:
                    continue
        except ImportError:
            pass
    unique = []
    seen = set()
    for path in candidates:
        normalized = str(path).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(path)
    return unique


def find_bilibili_executable() -> Path | None:
    for path in _candidate_executables():
        if not path.is_file() or '卸载' in path.name:
            continue
        if re.search(r'bilibili|哔哩', path.name, re.IGNORECASE):
            return path
    return None


def _launch_local(uri: str) -> bool:
    try:
        if _protocol_registered():
            os.startfile(uri)
            return True
        executable = find_bilibili_executable()
        if executable:
            subprocess.Popen([str(executable), uri], close_fds=True)
            return True
    except (OSError, ValueError):
        return False
    return False


def _open_with_fallback(
    player_uri: str,
    web_url: str,
    *,
    local_launcher: Callable[[str], bool],
    browser: Callable[..., bool],
) -> str:
    if local_launcher(player_uri):
        return 'app'
    browser(web_url, new=2)
    return 'browser'


def open_bilibili_search(
    title: str,
    original_title: str = '',
    year: str = '',
    *,
    local_launcher: Callable[[str], bool] = _launch_local,
    browser: Callable[..., bool] = webbrowser.open,
) -> str:
    keyword = movie_query(title, original_title, year)
    return _open_with_fallback(search_player_uri(keyword), search_web_url(keyword),
                               local_launcher=local_launcher, browser=browser)


def open_bilibili_play(
    title: str,
    original_title: str = '',
    year: str = '',
    *,
    local_launcher: Callable[[str], bool] = _launch_local,
    browser: Callable[..., bool] = webbrowser.open,
    finder: Callable[[str, str, str], dict | None] = find_play_video,
) -> str:
    keyword = movie_query(title, original_title, year, play=True)
    try:
        video = finder(title, original_title, year)
    except Exception:
        video = None
    player_uri = video['player_uri'] if video else search_player_uri(keyword)
    web_url = video['url'] if video else search_web_url(keyword)
    return _open_with_fallback(player_uri, web_url,
                               local_launcher=local_launcher, browser=browser)


def _allowed_bilibili_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (host == 'bilibili.com' or host.endswith('.bilibili.com'))


def open_bridge_url(
    url: str,
    *,
    local_launcher: Callable[[str], bool] = _launch_local,
    browser: Callable[..., bool] = webbrowser.open,
    finder: Callable[[str, str, str], dict | None] = find_play_video,
) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'moviewall' or parsed.netloc != 'bilibili' or parsed.path not in {'/search', '/play'}:
        raise ValueError('B站链接格式无效')
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False, strict_parsing=True)
    keywords = query.get('keyword') or []
    if len(keywords) != 1:
        raise ValueError('B站链接只允许一个搜索词')
    keyword = keywords[0].strip()
    if not keyword or len(keyword) > 200 or any(ord(character) < 32 for character in keyword):
        raise ValueError('B站搜索词无效')

    fallback_values = query.get('fallback') or []
    fallback = fallback_values[0] if len(fallback_values) == 1 else ''
    if fallback and not _allowed_bilibili_url(fallback):
        fallback = ''
    if parsed.path == '/search':
        return _open_with_fallback(search_player_uri(keyword), fallback or search_web_url(keyword),
                                   local_launcher=local_launcher, browser=browser)
    try:
        video = finder(keyword, '', '')
    except Exception:
        video = None
    player_uri = video['player_uri'] if video else search_player_uri(keyword)
    web_url = video['url'] if video else (fallback or search_web_url(keyword))
    return _open_with_fallback(player_uri, web_url,
                               local_launcher=local_launcher, browser=browser)
