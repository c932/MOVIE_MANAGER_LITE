"""榜单只读浏览和后台刷新。"""
from datetime import datetime
import re

from fastapi import APIRouter, HTTPException, Query, Request

from . import discovery
from .deps import get_store
from .routes_fetch import _ranked_items
from .routes_scrape_workspace import get_workspace
from .series import group_series, refresh_series, series_listing
from scraper.douban_ranking import RankedMovie
from utils.library_sync import read_json

router = APIRouter()


@router.get('/discovery/series')
def series(request: Request, name: str | None = Query(default=None, min_length=1, max_length=300)):
    store = get_store(request)
    library = store.snapshot()
    if name is None:
        # 列表读取本地快照和已有片单，避免打开页面时逐个查询 TMDB。
        return {'groups': [series_listing(store.settings.data_dir, key, members, library)
                           for key, members in group_series(library).items()]}
    members = [movie for movie in library if movie.set_name == name]
    if not members:
        raise HTTPException(404, '媒体库中没有该系列')
    return series_listing(store.settings.data_dir, name, members, library)


@router.post('/discovery/series/refresh')
def start_series_refresh(request: Request):
    store = get_store(request)
    settings = get_workspace(request).settings()
    job = request.app.state.jobs.submit('discovery.series.refresh',
        lambda ctx: refresh_series(store, settings, ctx), unique=True)
    return {'job_id': job.id}


def validate_year(year: int) -> None:
    if not 2014 <= year <= datetime.now().year - 1:
        raise HTTPException(400, '请选择已结束的年度')


@router.get('/discovery/annual/{year}')
def annual(request: Request, year: int):
    validate_year(year)
    data = read_json(discovery.annual_path(request.app.state.settings.data_dir, year),
                     {'year': year, 'fetched_at': 0, 'categories': []})
    store = get_store(request)
    for category in data['categories']:
        ranked = [RankedMovie(title=m['title'], year=m['year'], rating=m['rating'],
                  douban_id=m['douban_id'], rank=m['rank'], source='annual', poster_url=m['poster_url'])
                  for m in category['items']]
        category['items'] = _ranked_items(store, ranked)
    return data


@router.post('/discovery/annual/{year}/refresh')
def refresh_annual(request: Request, year: int):
    validate_year(year)
    job = request.app.state.jobs.submit(f'discovery.annual.{year}',
        lambda ctx: discovery.refresh_annual(request.app.state.settings.data_dir, year, ctx), unique=True)
    return {'job_id': job.id}


@router.post('/discovery/subject/{did}')
def subject(request: Request, did: str):
    if not re.fullmatch(r'\d{1,12}', did):
        raise HTTPException(400, '豆瓣条目 ID 无效')
    job = request.app.state.jobs.submit(f'discovery.subject.{did}',
        lambda ctx: discovery.subject_detail(request.app.state.settings.data_dir, did, ctx), unique=True)
    return {'job_id': job.id}
