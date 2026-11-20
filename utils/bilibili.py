"""哔哩哔哩搜索与本机客户端启动桥。"""
from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Callable

SEARCH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
SEARCH_PAGE = 'https://search.bilibili.com/pgc'
SEARCH_API = 'https://api.bilibili.com/x/web-interface/search/all/v2'
VIDEO_WEB = 'https://www.bilibili.com/video/'
MOVIE_WEB = 'https://www.bilibili.com/bangumi/play/'
SEASON_API = 'https://api.bilibili.com/pgc/view/web/season'

_cache: dict[str, tuple[float, dict[str, list[dict]]]] = {}
_cache_lock = threading.Lock()


def search_web_url(keyword: str) -> str:
    query = urllib.parse.urlencode({'keyword': keyword.strip()})
    return f'{SEARCH_PAGE}?{query}'


def video_web_url(bvid: str) -> str:
    return VIDEO_WEB + urllib.parse.quote(bvid, safe='')


def video_player_uri(bvid: str, aid: int, cid: int, page: int = 1) -> str:
    query = urllib.parse.urlencode({
        'type': 'ugc', 'bvid': bvid, 'aid': aid, 'cid': cid,
        'page': page, 'itemId': cid,
    })
    return 'bilipc://page/player?' + query


def _plain_text(value: object) -> str:
    text = html.unescape(re.sub(r'<[^>]+>', '', str(value or '')))
    return re.sub(r'\s+', ' ', text).strip()


def _search_results(keyword: str) -> dict[str, list[dict]]:
    """在同一次搜索中取得官方影视和普通视频条目。"""
    if not keyword:
        return {}
    cache_key = keyword.casefold()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 1800:
            return cached[1]

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page_url = search_web_url(keyword)
    with opener.open(urllib.request.Request(page_url, headers=SEARCH_HEADERS), timeout=5) as response:
        response.read(512 * 1024)
    api_query = urllib.parse.urlencode({'keyword': keyword, 'page': 1})
    with opener.open(urllib.request.Request(
        f'{SEARCH_API}?{api_query}',
        headers={**SEARCH_HEADERS, 'Referer': 'https://search.bilibili.com/'},
    ), timeout=5) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode('utf-8'))
    if payload.get('code') != 0:
        raise ValueError(f"B站搜索失败: {payload.get('message') or payload.get('code')}")

    results = {
        group['result_type']: group.get('data') or []
        for group in (payload.get('data') or {}).get('result') or []
        if group.get('result_type') in {'media_ft', 'video'}
    }
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), results)
    return results


def _normalized(value: str) -> str:
    return re.sub(r'[\W_]+', '', value.casefold(), flags=re.UNICODE)


def _main_movie_episode(season_id: int) -> int | None:
    query = urllib.parse.urlencode({'season_id': season_id})
    request = urllib.request.Request(
        f'{SEASON_API}?{query}', headers={**SEARCH_HEADERS, 'Referer': f'{MOVIE_WEB}ss{season_id}'},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
    season = payload.get('result')
    if payload.get('code') != 0 or not isinstance(season, dict) or season.get('season_id') != season_id:
        return None

    candidates: list[tuple[int, int]] = []
    for episode in season.get('episodes') or []:
        epid = episode.get('id')
        if type(epid) is not int or epid <= 0:
            continue
        title = _plain_text(episode.get('title'))
        label = f"{title} {_plain_text(episode.get('long_title'))}"
        if re.search(r'预告|先导|花絮|幕后|特辑|片段|试看|\b(?:PV\d*|Trailer|Teaser)\b', label, re.I):
            continue
        # 站方有原版和配音版时，默认选择原版，其余影片按正片列表顺序。
        candidates.append((0 if title in {'原版', '正片'} else 1, epid))
    return min(candidates, key=lambda entry: entry[0])[1] if candidates else None


def _official_play_target(season_id: int) -> dict[str, str]:
    try:
        epid = _main_movie_episode(season_id)
    except (OSError, TypeError, ValueError):
        epid = None
    if epid is None:
        return {'url': f'{MOVIE_WEB}ss{season_id}?theme=movie', 'player_uri': ''}
    query = urllib.parse.urlencode({'type': 'ogv', 'epid': epid, 'seasonId': season_id})
    return {
        'url': f'{MOVIE_WEB}ep{epid}?theme=movie',
        'player_uri': f'bilipc://page/player?{query}',
    }


def find_play_video(title: str, original_title: str = '', year: str = '') -> dict | None:
    keyword = title.strip() or original_title.strip()
    results = _search_results(keyword)
    names = {_normalized(title), _normalized(original_title)} - {''}
    dated_names = {f'{name}{year}' for name in names} | {f'{year}{name}' for name in names} if year else set()
    matching_names = names | dated_names
    official: dict[int, dict] = {}
    for item in results.get('media_ft', []):
        season_id = item.get('season_id')
        if (item.get('season_type') == 2 and type(season_id) is int and season_id > 0
                and _normalized(_plain_text(item.get('title'))) in matching_names):
            official[season_id] = item
    if official:
        dated_seasons = [sid for sid, item in official.items() if year and (
            _plain_text(item.get('index_show')).startswith(f'{year}-')
            or _normalized(_plain_text(item.get('title'))) in dated_names
        )]
        seasons = dated_seasons or list(official)
        if len(seasons) == 1:
            return _official_play_target(seasons[0])
        return None

    dated = []
    undated = []
    for item in results.get('video', []):
        bvid = str(item.get('bvid') or '')
        if not re.fullmatch(r'BV[0-9A-Za-z]+', bvid):
            continue
        candidate = _normalized(_plain_text(item.get('title')))
        if candidate in dated_names:
            dated.append(bvid)
        elif candidate in names:
            undated.append(bvid)

    for bvid in list(dict.fromkeys(dated + undated))[:3]:
        try:
            detail = resolve_video(bvid)
        except (OSError, TypeError, ValueError):
            continue
        if _normalized(detail['title']) not in matching_names:
            continue
        return {
            **detail,
            'bvid': bvid,
            'url': video_web_url(bvid),
            'player_uri': video_player_uri(bvid, detail['aid'], detail['cid']),
        }
    return None


def resolve_video(bvid: str) -> dict:
    """读取视频 aid/cid，确保本地播放器能构造有效播放参数。"""
    url = 'https://api.bilibili.com/x/web-interface/view?' + urllib.parse.urlencode({'bvid': bvid})
    with urllib.request.urlopen(urllib.request.Request(
        url,
        headers={**SEARCH_HEADERS, 'Referer': video_web_url(bvid)},
    ), timeout=5) as response:
        payload = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
    if payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
        raise ValueError(f"B站视频不可用: {payload.get('message') or bvid}")
    data = payload['data']
    if data.get('bvid') != bvid:
        raise ValueError(f'B站视频编号不匹配: {bvid}')
    aid, cid = int(data.get('aid') or 0), int(data.get('cid') or 0)
    if aid <= 0 or cid <= 0:
        raise ValueError(f'B站视频缺少播放参数: {bvid}')
    return {'aid': aid, 'cid': cid, 'title': _plain_text(data.get('title'))}


def _protocol_registered() -> bool:
    if os.name != 'nt':
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'bilipc') as key:
            winreg.QueryValueEx(key, 'URL Protocol')
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'bilipc\shell\open\command') as key:
            return bool(winreg.QueryValueEx(key, '')[0])
    except (ImportError, OSError):
        return False


def _launch_local(uri: str) -> bool:
    try:
        if _protocol_registered():
            os.startfile(uri)
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
    if player_uri and local_launcher(player_uri):
        return 'app'
    browser(web_url, new=2)
    return 'browser'


def open_bilibili_search(
    title: str,
    original_title: str = '',
    year: str = '',
    *,
    browser: Callable[..., bool] = webbrowser.open,
) -> str:
    browser(search_web_url(title.strip() or original_title.strip()), new=2)
    return 'browser'


def open_bilibili_play(
    title: str,
    original_title: str = '',
    year: str = '',
    *,
    local_launcher: Callable[[str], bool] = _launch_local,
    browser: Callable[..., bool] = webbrowser.open,
    finder: Callable[[str, str, str], dict | None] = find_play_video,
) -> str:
    try:
        video = finder(title, original_title, year)
    except (OSError, TypeError, ValueError):
        video = None
    player_uri = video['player_uri'] if video else ''
    web_url = video['url'] if video else search_web_url(title.strip() or original_title.strip())
    return _open_with_fallback(player_uri, web_url,
                               local_launcher=local_launcher, browser=browser)


def _query_text(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [''])
    value = values[0].strip()
    if len(values) != 1 or len(value) > 200 or any(ord(character) < 32 for character in value):
        raise ValueError('B站链接搜索参数无效')
    return value


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
    keyword = _query_text(query, 'keyword')
    if not keyword:
        raise ValueError('B站搜索词无效')

    title = _query_text(query, 'title')
    if parsed.path == '/search':
        return open_bilibili_search(title or keyword, browser=browser)
    original_title = _query_text(query, 'original_title')
    year = _query_text(query, 'year')
    if not title:
        # 旧版网页只发送组合关键词，去除额外加上的年份和「电影」。
        title = keyword.removesuffix(' 电影')
        legacy_title, _, legacy_year = title.rpartition(' ')
        if legacy_title and re.fullmatch(r'\d{4}', legacy_year):
            title, year = legacy_title, legacy_year
    return open_bilibili_play(
        title, original_title, year,
        local_launcher=local_launcher, browser=browser, finder=finder,
    )
