"""
电影墙核心端点（契约 docs/web_api_contract.md 2.1–2.3）。

本文件只做 HTTP 适配与 DTO 转换：
- 有状态数据（缓存/观看历史/收藏）统一经 MovieStore 读写（deps.get_store 懒初始化）；
- NFO 写入统一走 parsers/nfo_writer（原子替换，失败原文件不变）；
- 错误一律 HTTPException + {"detail": 中文信息}。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from parsers.nfo_writer import NFOWriteError, write_fields, write_xml
from wall_common.images import invalidate, render_image

from .deps import detail_dto, get_store, require_movie

logger = logging.getLogger("movie_service.routes_movies")

router = APIRouter()

# ─────────────────── 请求体模型 ───────────────────


class WatchedRequest(BaseModel):
    watched: bool


class FavoriteRequest(BaseModel):
    favorite: bool


class RatingRequest(BaseModel):
    rating: float


class NFOUpdateRequest(BaseModel):
    xml: str


# GET /movies 支持的排序键（契约未规定，属扩展；缺省保持缓存原顺序）
_SORT_KEYS = ("title", "year", "rating", "user_rating", "added_time")


def _sort_key(name: str):
    if name == "title":
        return lambda d: (d.get("title") or "").casefold()
    if name == "year":
        return lambda d: str(d.get("year") or "")
    if name == "rating":
        return lambda d: float(d.get("rating") or 0.0)
    if name == "user_rating":
        return lambda d: float(d.get("user_rating") or 0.0)
    if name == "added_time":
        return lambda d: float(d.get("added_time") or 0.0)
    raise HTTPException(status_code=400, detail=f"不支持的排序字段: {name}")


def _contains(values: Optional[List[str]], needle: Optional[str]) -> bool:
    """needle 为空视为不过滤；否则要求任一值包含它（不区分大小写）。"""
    if not needle:
        return True
    key = needle.casefold()
    return any(key in str(v or "").casefold() for v in (values or []))


def _match(
    dto: Dict[str, Any],
    *,
    q: Optional[str],
    genre: Optional[str],
    country: Optional[str],
    actor: Optional[str],
    director: Optional[str],
    tag: Optional[str],
    year: Optional[str],
    resolution: Optional[str],
    watched: Optional[bool],
    favorite: Optional[bool],
    min_rating: Optional[float],
) -> bool:
    if q:
        key = q.casefold()
        hit = key in (dto.get("title") or "").casefold()
        hit = hit or key in (dto.get("original_title") or "").casefold()
        hit = hit or any(key in str(d or "").casefold() for d in dto.get("directors") or [])
        hit = hit or any(
            key in str(a.get("name") or "").casefold() for a in dto.get("actors") or []
        )
        if not hit:
            return False
    if not _contains(dto.get("genres"), genre):
        return False
    if not _contains(dto.get("countries"), country):
        return False
    if not _contains(dto.get("tags"), tag):
        return False
    if actor and not any(
        actor.casefold() in str(a.get("name") or "").casefold() for a in dto.get("actors") or []
    ):
        return False
    if not _contains(dto.get("directors"), director):
        return False
    if year and str(dto.get("year") or "") != year:
        return False
    if resolution and resolution.casefold() not in (dto.get("resolution") or "").casefold():
        return False
    if watched is not None and bool(dto.get("watched")) != watched:
        return False
    if favorite is not None and bool(dto.get("favorite")) != favorite:
        return False
    if min_rating is not None and float(dto.get("rating") or 0.0) < min_rating:
        return False
    return True


# ─────────────────── 电影列表 / 详情 ───────────────────


@router.get("/movies")
def list_movies(
    request: Request,
    q: Optional[str] = Query(None, description="片名/原名/导演/演员关键字"),
    genre: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    director: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    year: Optional[str] = Query(None),
    resolution: Optional[str] = Query(None),
    watched: Optional[bool] = Query(None),
    favorite: Optional[bool] = Query(None),
    min_rating: Optional[float] = Query(None, ge=0, le=10),
    sort: Optional[str] = Query(None),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(0, ge=0, description="0=不截断"),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """
    全量电影列表（元数据）。

    - 默认不带筛选/排序参数时返回缓存里的全部电影；
    - 列表项 plot 截断 200 字符、actors 截断 8 人（契约 2.1）；
    - 筛选/排序/分页参数为契约外扩展，total 为筛选后的匹配数量。
    """
    store = get_store(request)
    lookups = store.rank_lookups()
    dtos = [
        store.dto(movie, detail=False, rank_lookups=lookups)
        for movie in store.snapshot()
    ]

    matched = [
        d
        for d in dtos
        if _match(
            d,
            q=q,
            genre=genre,
            country=country,
            actor=actor,
            director=director,
            tag=tag,
            year=year,
            resolution=resolution,
            watched=watched,
            favorite=favorite,
            min_rating=min_rating,
        )
    ]

    if sort:
        matched.sort(key=_sort_key(sort), reverse=(order == "desc"))

    total = len(matched)
    page = matched[offset:] if not limit else matched[offset : offset + limit]
    return {"total": total, "movies": page, "cache_info": store.cache_info()}


@router.get("/movies/{movie_id}")
def get_movie(request: Request, movie_id: str) -> Dict[str, Any]:
    """电影详情（plot/actors 不截断）。"""
    store = get_store(request)
    return detail_dto(store, require_movie(store, movie_id))


# ─────────────────── 状态写入 ───────────────────


@router.post("/movies/{movie_id}/watched")
def set_watched(request: Request, movie_id: str, payload: WatchedRequest) -> Dict[str, Any]:
    """写观看状态（WatchHistoryManager + 缓存）。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    store.set_watched(movie, bool(payload.watched))
    return detail_dto(store, movie)


@router.post("/movies/{movie_id}/favorite")
def set_favorite(request: Request, movie_id: str, payload: FavoriteRequest) -> Dict[str, Any]:
    """写收藏状态（FavoriteManager + 缓存）。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    store.set_favorite(movie, bool(payload.favorite))
    return detail_dto(store, movie)


@router.put("/movies/{movie_id}/rating")
def put_rating(request: Request, movie_id: str, payload: RatingRequest) -> Dict[str, Any]:
    """写用户评分到 NFO 的 <ratings><rating name="user">（0-10）。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    try:
        store.set_user_rating(movie, float(payload.rating))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    updated = store.get(movie_id)
    if updated is None:  # pragma: no cover - reparse 成功后必然还在缓存里
        raise HTTPException(status_code=500, detail="评分写入后电影丢失")
    return detail_dto(store, updated)


@router.delete("/movies/{movie_id}")
def delete_movie(request: Request, movie_id: str) -> Dict[str, bool]:
    """仅删本地记录（缓存 + 观看历史 + 收藏 + 失败记录），不动媒体文件。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    store.remove(movie)
    return {"removed": True}


@router.post("/movies/{movie_id}/reparse")
def reparse_movie(request: Request, movie_id: str) -> Dict[str, Any]:
    """重新解析 NFO 并刷新缓存（桌面版右键「更新NFO」）。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    updated = store.reparse(movie)
    if updated is None:
        raise HTTPException(status_code=500, detail="NFO 重新解析失败")
    return detail_dto(store, updated)


# ─────────────────── 海报 ───────────────────


def _poster_source(movie) -> str:
    return movie.poster_path or ""


@router.get("/movies/{movie_id}/poster")
def get_poster(
    request: Request,
    movie_id: str,
    w: int = Query(200),
    h: int = Query(300),
    mode: str = Query("cover"),
) -> Response:
    """按需生成海报缩略图（mode: cover|contain；源图缺失 404）。"""
    st = request.app.state.settings
    store = get_store(request)
    movie = require_movie(store, movie_id)

    source = _poster_source(movie)
    shared = st.data_dir / 'shared_posters' / f'{movie_id}.jpg'
    if shared.is_file():
        source = str(shared)
    if not source:
        raise HTTPException(status_code=404, detail="该电影没有海报")
    if not Path(source).is_file():
        raise HTTPException(status_code=404, detail="海报文件不存在")

    # 尺寸/模式非法时 render_image 抛 ImageError(400)，由工厂统一转响应
    data = render_image(source, w, h, mode=mode, cache_dir=st.image_cache_dir)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/movies/{movie_id}/poster/invalidate")
def invalidate_poster(request: Request, movie_id: str) -> Dict[str, int]:
    """失效该海报的服务端缩略图缓存。"""
    st = request.app.state.settings
    store = get_store(request)
    movie = require_movie(store, movie_id)
    source = _poster_source(movie)
    shared = st.data_dir / 'shared_posters' / f'{movie_id}.jpg'
    if shared.is_file():
        source = str(shared)
    if not source:
        return {"removed": 0}
    return {"removed": invalidate(source, st.image_cache_dir)}


# ─────────────────── NFO 读写 ───────────────────


@router.get("/movies/{movie_id}/nfo")
def get_nfo(request: Request, movie_id: str) -> Dict[str, str]:
    """原始 NFO XML 文本。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    if not movie.nfo_path:
        raise HTTPException(status_code=404, detail="该电影没有 NFO 路径")
    path = Path(movie.nfo_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="NFO 文件不存在")
    try:
        return {"xml": path.read_text(encoding="utf-8"), "path": str(path)}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"读取 NFO 失败: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=500, detail="NFO 不是 UTF-8 文本") from exc


@router.put("/movies/{movie_id}/nfo")
def put_nfo(request: Request, movie_id: str, payload: NFOUpdateRequest) -> Dict[str, Any]:
    """校验后整体覆盖 NFO（根元素必须是 <movie>），成功后刷新缓存。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    if not movie.nfo_path:
        raise HTTPException(status_code=404, detail="该电影没有 NFO 路径")
    try:
        write_xml(movie.nfo_path, payload.xml)
    except NFOWriteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = store.reparse(movie)
    if updated is None:
        raise HTTPException(status_code=500, detail="NFO 写入后重新解析失败")
    return detail_dto(store, updated)


@router.put("/movies/{movie_id}/fields")
def put_fields(
    request: Request,
    movie_id: str,
    fields: Dict[str, Any] = Body(..., description="契约 2.3 的部分字段"),
) -> Dict[str, Any]:
    """结构化字段编辑（等价桌面版 NFO 编辑器保存逻辑）。"""
    store = get_store(request)
    movie = require_movie(store, movie_id)
    if not movie.nfo_path:
        raise HTTPException(status_code=404, detail="该电影没有 NFO 路径")
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    try:
        write_fields(movie.nfo_path, fields)
    except NFOWriteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = store.reparse(movie)
    if updated is None:
        raise HTTPException(status_code=500, detail="字段写入后重新解析 NFO 失败")
    return detail_dto(store, updated)
