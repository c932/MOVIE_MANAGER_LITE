"""
刮削 / 榜单 / 新片 / 图片代理端点（契约 2.2 的 /scrape、2.5、2.6 与 /proxy/image）。

- 同步快速端点（/rankings/{kind}、/newmovies/{kind}）只读本地缓存 + 与本地库对比；
- 抓取类端点提交 Job，结果由通用 /jobs 轮询；
- 所有网络调用都发生在 Job 任务体或 cached_remote 内，便于测试 monkeypatch。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from wall_common.images import ImageError, cached_remote

from .browse_cache import allowed_poster, cached_browse, cached_plot
from .deps import get_store
from .routes_scrape_workspace import get_workspace
from .store import movie_id
from .tasks import (
    NEWMOVIES_KIND,
    NEW_MOVIE_SOURCES,
    RANKINGS_KIND,
    RANKING_SOURCES,
    SCRAPE_KIND,
    run_newmovies_fetch,
    run_rankings_fetch,
    run_scrape,
)

logger = logging.getLogger("movie_service.routes_fetch")

router = APIRouter()

RANKING_KINDS: Sequence[str] = ("top250", "chart", "imdb_top250")
NEW_MOVIE_KINDS: Sequence[str] = ("nowplaying", "coming")

class ScrapeRequest(BaseModel):
    ids: List[str]


class RankingsFetchRequest(BaseModel):
    sources: List[str] = list(RANKING_SOURCES)
    use_cache: bool = True


class NewMoviesFetchRequest(BaseModel):
    sources: List[str] = list(NEW_MOVIE_SOURCES)
    use_cache: bool = True


def _cache_timestamp(path: Path, source: str = '') -> float:
    """读缓存 JSON 的 timestamp（ISO 文本）转 Unix 秒；读不到返回 0.0。"""
    try:
        if not path.is_file():
            return 0.0
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = (data.get('source_timestamps', {}).get(source) if source else data.get('timestamp')) or ''
        if not stamp:
            return 0.0
        return float(datetime.fromisoformat(stamp).timestamp())
    except (OSError, ValueError, TypeError):  # JSON/时间格式异常一律视为无缓存
        logger.debug("榜单缓存时间戳不可用: %s", path)
        return 0.0


def _validated_sources(sources: Optional[Sequence[str]], allowed: Sequence[str]) -> List[str]:
    requested = [str(s) for s in (sources or [])]
    unknown = [s for s in requested if s not in allowed]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"未知的抓取来源: {', '.join(unknown)}"
        )
    # 保持契约默认顺序
    return [s for s in allowed if s in requested]


# ─────────────────── 豆瓣刮削 ───────────────────


@router.post("/scrape")
def start_scrape(request: Request, payload: ScrapeRequest) -> Dict[str, str]:
    """提交批量刮削任务（kind=scrape.batch）。"""
    store = get_store(request)
    ids = [str(i) for i in (payload.ids or [])]
    job = request.app.state.jobs.submit(
        SCRAPE_KIND,
        lambda ctx: run_scrape(store, ctx, ids),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── 榜单 ───────────────────


def _ranked_items(store, ranked: List[Any]) -> List[Dict[str, Any]]:
    """榜单条目 DTO（title/original_title 见契约 2.5 与最终报告说明）。"""
    from scraper.douban_ranking import _find_local_match, _get_title_aliases

    local = store.snapshot()
    items: List[Dict[str, Any]] = []
    for rm in ranked:
        matched = _find_local_match(rm, local) if local else None
        is_owned = matched is not None
        cached = cached_browse(store.settings.data_dir, rm.douban_id)
        if getattr(rm, "source", "") == "imdb_top250":
            # IMDB 榜单标题为原文：优先本地中文名，其次翻译表别名
            aliases = [a for a in (_get_title_aliases(rm.title) or []) if a]
            title = (matched.title if matched else "") or (aliases[0] if aliases else rm.title)
            original_title = rm.title
        else:
            title = rm.title
            original_title = (matched.original_title if matched else "") or ""
        external = {} if is_owned else cached
        items.append(
            {
                "rank": int(rm.rank or 0),
                "title": title,
                "original_title": external.get("original_title") or original_title,
                "year": str(rm.year or ""),
                "rating": float(rm.rating or 0.0),
                "poster_url": cached.get('poster_url') or rm.poster_url or "",
                "plot": (matched.plot if matched else '') or rm.plot or external.get('plot', ''),
                "premiered": rm.premiered or external.get('premiered', ''),
                "rating_source": 'imdb' if rm.source == 'imdb_top250' else 'douban',
                "douban_id": rm.douban_id if rm.source != 'imdb_top250' else '',
                "imdb_id": external.get('imdb_id', ''),
                "tmdb_id": external.get('tmdb_id', ''),
                "ratings": external.get('ratings', {}),
                "genres": external.get('genres', []),
                "countries": external.get('countries', []),
                "directors": external.get('directors', []),
                "actors": external.get('actors', []),
                "enrichment_note": external.get('enrichment_note', ''),
                "douban_url": f'https://movie.douban.com/subject/{rm.douban_id}/' if rm.douban_id and rm.source != 'imdb_top250' else '',
                "owned": is_owned,
                "movie_id": movie_id(matched.nfo_path) if is_owned else None,
                "in_library": is_owned,
            }
        )
    return items


@router.get("/rankings/{kind}")
def get_rankings(request: Request, kind: str) -> Dict[str, Any]:
    """读榜单缓存并与本地库对比（同步快速；无缓存时 fetched_at=0、items=[]）。"""
    if kind not in RANKING_KINDS:
        raise HTTPException(status_code=400, detail=f"未知的榜单类型: {kind}")

    from scraper.douban_ranking import load_imdb_cache, load_ranking_cache

    store = get_store(request)
    cache_path = store.ranking_cache_file
    fetched_at = _cache_timestamp(cache_path, kind)
    if not cache_path.is_file():
        return {"kind": kind, "fetched_at": 0.0, "items": [], "owned_count": 0, "missing_count": 0}

    if kind == "imdb_top250":
        ranked = load_imdb_cache(cache_path=cache_path)
    else:
        top250, chart = load_ranking_cache(cache_path=cache_path)
        ranked = top250 if kind == "top250" else chart

    items = _ranked_items(store, ranked)
    owned_count = sum(1 for it in items if it["owned"])
    return {
        "kind": kind,
        "fetched_at": fetched_at,
        "items": items,
        "owned_count": owned_count,
        "missing_count": len(items) - owned_count,
    }


@router.post("/rankings/fetch")
def fetch_rankings(request: Request, payload: RankingsFetchRequest) -> Dict[str, str]:
    """提交榜单抓取任务（kind=rankings.fetch）。"""
    store = get_store(request)
    sources = _validated_sources(payload.sources, RANKING_SOURCES)
    job = request.app.state.jobs.submit(
        RANKINGS_KIND + ('.' + sources[0] if len(sources) == 1 else ''),
        lambda ctx: run_rankings_fetch(
            store, ctx, sources=sources, use_cache=bool(payload.use_cache),
            settings=get_workspace(request).settings() if set(sources) & {'top250', 'imdb_top250'} else None,
        ),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── 新片 ───────────────────


@router.get("/newmovies/{kind}")
def get_newmovies(request: Request, kind: str) -> Dict[str, Any]:
    """读新片缓存并与本地库对比（结构见契约 2.6）。"""
    if kind not in NEW_MOVIE_KINDS:
        raise HTTPException(status_code=400, detail=f"未知的新片类型: {kind}")

    from scraper.new_movie_checker import load_new_movie_cache
    from scraper.douban_ranking import _find_local_match

    store = get_store(request)
    cache_path = store.new_movie_cache_file
    fetched_at = _cache_timestamp(cache_path)
    if fetched_at <= 0.0:
        return {"kind": kind, "fetched_at": 0.0, "items": [], "owned_count": 0, "missing_count": 0}

    nowplaying, coming = load_new_movie_cache(cache_path=cache_path)
    source_list = nowplaying if kind == "nowplaying" else coming

    local = store.snapshot()
    items: List[Dict[str, Any]] = []
    for nm in source_list:
        matched = _find_local_match(nm, local) if local else None
        is_owned = matched is not None
        items.append(
            {
                "title": nm.title,
                "douban_id": nm.douban_id,
                "year": str(nm.year or ""),
                "genre": " / ".join(nm.genres or []),
                "release_date": nm.premiered or "",
                "plot": (matched.plot if matched else '') or cached_plot(store.settings.data_dir, nm.douban_id),
                "poster_url": nm.poster_url or "",
                "douban_url": (
                    f"https://movie.douban.com/subject/{nm.douban_id}/"
                    if nm.douban_id
                    else ""
                ),
                "rating": float(nm.rating or 0.0),
                "in_library": is_owned,
                "movie_id": movie_id(matched.nfo_path) if is_owned else None,
            }
        )
    owned_count = sum(1 for it in items if it["in_library"])
    return {
        "kind": kind,
        "fetched_at": fetched_at,
        "items": items,
        "owned_count": owned_count,
        "missing_count": len(items) - owned_count,
    }


@router.post("/newmovies/fetch")
def fetch_newmovies(request: Request, payload: NewMoviesFetchRequest) -> Dict[str, str]:
    """提交新片抓取任务（kind=newmovies.fetch）。"""
    store = get_store(request)
    sources = _validated_sources(payload.sources, NEW_MOVIE_SOURCES)
    job = request.app.state.jobs.submit(
        NEWMOVIES_KIND,
        lambda ctx: run_newmovies_fetch(
            store, ctx, sources=sources, use_cache=bool(payload.use_cache)
        ),
        unique=True,
    )
    return {"job_id": job.id}


# ─────────────────── 图片代理 ───────────────────

_IMAGE_SIGNATURES = (
    (b"\x89PNG", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"\xff\xd8", "image/jpeg"),
)


def _sniff_media_type(data: bytes) -> str:
    for prefix, media_type in _IMAGE_SIGNATURES:
        if data.startswith(prefix):
            return media_type
    return "image/jpeg"


@router.get("/proxy/image")
def proxy_image(request: Request, url: str = Query(...), prefer_cache: bool = False) -> Response:
    """代理外网图片（仅白名单 host；缓存到本数据目录）。"""
    st = request.app.state.settings
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(400, "图片地址格式无效") from exc
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 图片地址")

    hostname = (parsed.hostname or "").lower()
    if not allowed_poster(url):
        raise HTTPException(status_code=400, detail=f"不允许的图片来源: {hostname or url}")

    try:
        cached = (cached_remote(url, st.cover_cache_dir, ttl=float('inf')) if prefer_cache
                  else cached_remote(url, st.cover_cache_dir))
        data = cached.read_bytes()
    except ImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"读取图片缓存失败: {exc}") from exc

    return Response(
        content=data,
        media_type=_sniff_media_type(data),
        headers={"Cache-Control": "private, max-age=86400"},
    )
