"""榜单只读浏览和后台刷新。"""
from datetime import datetime
import re

from fastapi import APIRouter, HTTPException, Request

from . import discovery
from .deps import get_store
from .routes_fetch import _ranked_items
from scraper.douban_ranking import RankedMovie
from utils.library_sync import read_json

router = APIRouter()


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
