"""只读榜单发现：官方年度分类、按需简介，不写电影库或 NAS。"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

from utils.library_sync import atomic_json, read_json


def fetch_text(url: str) -> str:
    from scraper.douban_ranking import HEADERS
    headers = {**HEADERS, 'Referer': 'https://movie.douban.com/'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
            return response.read(8 * 1024 * 1024).decode('utf-8')
    except Exception as exc:
        raise ValueError('豆瓣暂时无法访问，请稍后重试；已缓存的榜单会保留。') from exc


def parse_annual(data: dict, year: int) -> dict:
    categories = []
    for widget in data.get('widgets', []):
        source = widget.get('source_data') or {}
        sources = source if isinstance(source, list) else [source]
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            collection = source.get('subject_collection') or {}
            if collection.get('subject_type') != 'movie':
                continue
            items = []
            for subject in source.get('subject_collection_items', []):
                did = str(subject.get('id') or '')
                if not did.isdigit() or not subject.get('title'):
                    continue
                subtitle = str(subject.get('card_subtitle') or '')
                matched = re.match(r'(\d{4})', subtitle)
                items.append({
                    'rank': len(items) + 1, 'title': subject['title'],
                    'original_title': '', 'year': matched.group(1) if matched else '',
                    'rating': float((subject.get('rating') or {}).get('value') or 0),
                    'poster_url': subject.get('cover_url') or '', 'douban_id': did,
                    'douban_url': f'https://movie.douban.com/subject/{did}/',
                })
            if items:
                categories.append({'id': f"{widget['id']}-{index}", 'title': collection.get('title') or widget.get('title'), 'items': items})
    if not categories:
        raise ValueError('该年度暂未提供可读取的电影分类，请选择其他年份。')
    return {'year': year, 'source_url': f'https://movie.douban.com/annual/{year}/',
            'categories': categories, 'fetched_at': time.time()}


def annual_path(data_dir: Path, year: int) -> Path:
    return data_dir / 'discovery' / f'annual-{year}.json'


def normalize_legacy(data: dict) -> dict:
    """2017–2022 官方活动页以嵌套 widgets/subjects 提供分类。"""
    widgets = []
    def walk(entries: list) -> None:
        for widget in entries:
            payload = widget.get('payload') or {}
            walk(payload.get('widgets') or [])
            title = str(payload.get('title') or '')
            if not re.search(r'电影|佳片|片$', title) or re.search(r'剧集|新剧|续订剧|综艺', title):
                continue
            subjects = widget.get('subjects') or []
            items = [{'id': subject.get('id'), 'title': subject.get('title'),
                      'card_subtitle': str(subject.get('year') or ''),
                      'cover_url': subject.get('cover'),
                      'rating': {'value': subject.get('rating') or 0}}
                     for subject in subjects]
            widgets.append({'id': widget['id'], 'source_data': {
                'subject_collection': {'subject_type': 'movie', 'title': f"{payload.get('subtitle') or ''} {title}".strip()},
                'subject_collection_items': items}})
    walk(data.get('widgets') or [])
    return {'widgets': widgets}


def refresh_annual(data_dir: Path, year: int, ctx) -> dict:
    ctx.update(message=f'正在获取豆瓣 {year} 年度电影榜单…')
    html = fetch_text(f'https://movie.douban.com/annual/{year}/')
    page = re.search(r"page\s*:\s*\{\s*['\"]id['\"]\s*:\s*(\d+)", html)
    ctx.check_cancelled()
    if page:
        data = json.loads(fetch_text(f'https://movie.douban.com/j/neu/page/{page.group(1)}/'))
        if data.get('alias') and data['alias'] != f'movie_{year}':
            raise ValueError('官方返回的榜单年份不符，旧缓存已保留。')
    else:
        legacy = re.search(r'<meta\s+name="url_name"\s+content="(movie_annual\d{4})"', html)
        if not legacy:
            raise ValueError('该年度官方页面暂无法读取，请选择其他年份。')
        response = json.loads(fetch_text(f'https://movie.douban.com/ithil_j/activity/{legacy.group(1)}?with_widgets=1'))
        data = normalize_legacy(response.get('res') or {})
    result = parse_annual(data, year)
    ctx.check_cancelled()
    atomic_json(annual_path(data_dir, year), result)
    return {'year': year, 'categories': len(result['categories'])}


def subject_detail(data_dir: Path, did: str, ctx) -> dict:
    path = data_dir / 'discovery' / f'subject-{did}.json'
    cached = read_json(path, {})
    if cached.get('plot') and time.time() - cached.get('fetched_at', 0) < 86400:
        return cached
    ctx.update(message='正在读取电影简介…')
    from scraper.douban_cli import get_movie_detail
    data = get_movie_detail(did)
    if not isinstance(data, dict) or not data.get('summary'):
        raise ValueError('豆瓣暂未返回电影简介，可稍后重试或打开豆瓣条目。')
    if data.get('id') and str(data['id']) != did:
        raise ValueError('豆瓣返回的条目不匹配，请重试。')
    result = {'title': str(data.get('title') or ''), 'plot': str(data['summary']),
              'douban_id': did, 'fetched_at': time.time()}
    ctx.check_cancelled()
    atomic_json(path, result)
    return result
