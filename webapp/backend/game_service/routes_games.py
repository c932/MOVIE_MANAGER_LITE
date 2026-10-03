"""
游戏墙核心端点（契约 docs/web_api_contract.md 3.1–3.2 的同步部分）。

本文件只做 HTTP 适配与 DTO 转换：
- 数据读写统一经 GameStore（deps.get_store 懒初始化）；
- 网络调用（Steam/LLM）try/except，失败返回清晰中文错误；
- 错误一律 HTTPException + {"detail": 中文信息}。

⚠️ 路由顺序重要：所有不含 path 变量的静态路由（/games/steam/search 等）
以及含子路径的路由（/tier /cover /cover/refresh）必须定义在泛化的
/games/{key:path} GET/PUT 之前，否则 path 贪婪匹配会把 "steam/search"
或 "key/tier" 整体当 key 参数收掉。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from wall_common.images import ImageError, invalidate, render_image

from .covers import resolve_cover_path, smart_render_mode
from .deps import call_with_timeout, get_store, require_game
from .store import StoreError, custom_cover_path, decode_key, validate_edit_fields

logger = logging.getLogger("game_service.routes_games")

router = APIRouter()


# ─────────────────── 请求体模型 ───────────────────


class TierRequest(BaseModel):
    tier: Optional[str] = None


class CoverRefreshRequest(BaseModel):
    variant: str = "grid"


class SteamApplyRequest(BaseModel):
    key: str
    appid: int


class LLMMatchRequest(BaseModel):
    key: str


class LLMPosterRequest(BaseModel):
    key: str


def _parse_size(w: Optional[str], h: Optional[str], max_edge: int) -> Tuple[int, int]:
    """封面尺寸参数：非法或越界 → 400 中文（契约 1.2，默认 600x900）。"""
    def _one(raw: Optional[str], default: int) -> int:
        if raw is None or not str(raw).strip():
            return default
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"非法的图片尺寸参数: {raw}") from None
        if value <= 0:
            raise HTTPException(
                status_code=400, detail=f"图片尺寸必须为正整数: {raw}")
        return value

    width, height = _one(w, 600), _one(h, 900)
    if width > max_edge or height > max_edge:
        raise HTTPException(
            status_code=400, detail=f"图片尺寸上限 {max_edge}px: {width}x{height}")
    return width, height


# ─────────────────── 列表（静态路由）───────────────────


@router.get("/games")
def list_games(request: Request) -> Dict[str, Any]:
    """契约 3.2 的 GET /games：全量列表（元数据）。"""
    store = get_store(request)
    return store.list_dto()


# ─────────────────── Steam 搜索 / 应用（静态路由）────────


@router.get("/games/steam/search")
def steam_search(request: Request, q: str = Query("")) -> Dict[str, Any]:
    """Steam 手动搜索（同步，内部有限流）。results 含 definitive（名称与 q 归一化一致）。"""
    from gamewall import steam_client
    from gamewall.name_utils import normalize_name

    term = (q or "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="缺少搜索词 q")
    try:
        items, err = call_with_timeout(
            lambda: steam_client.search_steam(term), 20.0, "Steam 搜索")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Steam 搜索失败: {exc}") from exc
    if err and not items:
        raise HTTPException(status_code=502, detail=f"Steam 搜索失败: {err}")

    nq = normalize_name(term)
    results = []
    for item in items:
        name = str(item.get("name") or "")
        results.append({
            "appid": int(item.get("appid") or 0),
            "name": name,
            "definitive": bool(name) and normalize_name(name) == nq,
        })
    return {"results": results}


@router.post("/games/steam/apply")
def steam_apply(request: Request, payload: SteamApplyRequest) -> Dict[str, Any]:
    """拉取 appdetails + reviews 合并写缓存（复刻桌面 _apply_steam_update）。"""
    from gamewall import steam_client

    store = get_store(request)
    game = require_game(store, payload.key)

    def _pull() -> tuple:
        """详情 + 评价一次拉全（合同：同步 ≤15s，超时则整体不应用）。"""
        details, derr = steam_client.fetch_appdetails(payload.appid)
        if derr:
            return None, f"Steam 详情拉取失败: {derr}"
        reviews, rerr = steam_client.fetch_appreviews(payload.appid)
        if rerr:
            return None, f"Steam 评价拉取失败: {rerr}"
        merged: Dict[str, Any] = dict(details or {})
        merged.update(reviews or {})
        return merged, ""

    try:
        merged, err = call_with_timeout(_pull, 15.0, "Steam 数据拉取")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Steam 拉取异常: {exc}") from exc
    if err:
        raise HTTPException(status_code=502, detail=err)

    fields: Dict[str, Any] = {"steam_appid": payload.appid}
    fields.update(merged or {})
    game, _applied = store.apply_fields(payload.key, fields, force=True)
    if game is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {payload.key}")
    return store.dto(game, detail=True)


# ─────────────────── LLM 匹配 / 海报（静态路由）──────────


@router.post("/games/llm/match")
def llm_match(request: Request, payload: LLMMatchRequest) -> Dict[str, Any]:
    """LLM 建议 + Steam 校验（同步，≤60s）。"""
    from gamewall.llm_search import llm_match_and_fetch

    store = get_store(request)
    game = require_game(store, payload.key)
    try:
        base_url, api_key, model = store.llm_config()
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        fields, err = call_with_timeout(
            lambda: llm_match_and_fetch(game, base_url, api_key, model),
            60.0, "LLM 匹配")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 匹配异常: {exc}") from exc
    if err:
        raise HTTPException(status_code=502, detail=f"LLM 匹配失败: {err}")

    appid = int(fields.get("steam_appid") or 0)
    if not appid:
        raise HTTPException(status_code=502, detail="LLM 未找到匹配的 Steam 应用")

    game, _applied = store.apply_fields(payload.key, fields, force=True)
    if game is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {payload.key}")
    return {
        "game": store.dto(game, detail=True),
        "appid": appid,
        "verified": True,
    }


@router.post("/games/llm/poster")
def llm_poster(request: Request, payload: LLMPosterRequest) -> Dict[str, Any]:
    """LLM 重新获取竖版海报（复刻桌面 _llm_refetch_poster）。"""
    from gamewall.llm_search import llm_match_and_fetch

    st = request.app.state.settings
    store = get_store(request)
    game = require_game(store, payload.key)
    try:
        base_url, api_key, model = store.llm_config()
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        fields, err = call_with_timeout(
            lambda: llm_match_and_fetch(game, base_url, api_key, model),
            60.0, "LLM 海报匹配")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 海报匹配异常: {exc}") from exc
    if err:
        raise HTTPException(status_code=502, detail=f"LLM 海报匹配失败: {err}")

    appid = int(fields.get("steam_appid") or 0)
    if not appid:
        raise HTTPException(status_code=502, detail="LLM 未找到匹配的 Steam 应用")

    # 只保留 appid/name/header_image，重新拉竖版封面候选
    poster_fields = {
        k: v for k, v in fields.items()
        if k in ("steam_appid", "steam_name", "header_image")
    }
    game, _applied = store.apply_fields(payload.key, poster_fields, force=True)
    if game is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {payload.key}")

    # 失效封面缓存
    for url in game.get_cover_urls():
        invalidate(url, st.cover_cache_dir)

    return store.dto(game, detail=True)


# ─────────────────── 子路由（必须在 /games/{key:path} 之前）────


@router.put("/games/{key:path}/tier")
def put_tier(request: Request, key: str, payload: TierRequest) -> Dict[str, Any]:
    """标记档位 / null 恢复自动判断。"""
    store = get_store(request)
    real_key = decode_key(key)
    require_game(store, real_key)
    try:
        game = store.set_tier(real_key, payload.tier)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.dto(game, detail=True)


@router.get("/games/{key:path}/cover")
def get_cover(
    request: Request,
    key: str,
    w: Optional[str] = Query(None),
    h: Optional[str] = Query(None),
    variant: Optional[str] = Query(None),
) -> Response:
    """封面端点：不传 variant 按契约链 custom → grid → 404；带 ETag/304（契约 1.2）。"""
    st = request.app.state.settings
    store = get_store(request)
    real_key = decode_key(key)
    game = require_game(store, real_key)

    if variant not in (None, "", "custom", "grid"):
        raise HTTPException(status_code=400, detail=f"不支持的封面变体: {variant}")
    width, height = _parse_size(w, h, st.poster_max_edge)

    try:
        source = resolve_cover_path(store, game, variant=variant or None)
    except ImageError:
        raise                       # 状态码随 ImageError（404 无封面 / 400 参数）
    except Exception as exc:        # 拉取异常按「无可用封面」处理，前端画占位
        logger.debug("封面解析失败 %s: %s", real_key, exc)
        raise HTTPException(status_code=404, detail="该游戏没有可用的封面") from exc

    mode, bg = smart_render_mode(source)
    data = render_image(source, width, height, mode=mode,
                        cache_dir=st.image_cache_dir, bg=bg)
    etag = '"' + hashlib.md5(data).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=300"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/jpeg", headers=headers)


@router.post("/games/{key:path}/cover/refresh")
def refresh_cover(
    request: Request,
    key: str,
    payload: Optional[CoverRefreshRequest] = None,
) -> Dict[str, str]:
    """强制重新拉取封面（跳过缓存）。variant=custom 返回本地路径（无则 404）。"""
    store = get_store(request)
    real_key = decode_key(key)
    game = require_game(store, real_key)

    variant = (payload.variant if payload else "grid") or "grid"
    if variant == "custom":
        source = custom_cover_path(store.data_dir, real_key)
        if not source.is_file():
            raise HTTPException(status_code=404, detail="该游戏没有自定义封面")
        return {"path": str(source)}
    if variant != "grid":
        raise HTTPException(status_code=400, detail=f"不支持的封面变体: {variant}")

    try:
        path = call_with_timeout(
            lambda: resolve_cover_path(store, game, variant="grid", refresh=True),
            60.0, "封面拉取")
    except (HTTPException, ImageError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageError(f"封面拉取失败: {exc}", status_code=502) from exc
    return {"path": str(path)}


# ─────────────────── 详情 / 编辑（子路由之后）────────────


@router.get("/games/{key:path}")
def get_game(request: Request, key: str) -> Dict[str, Any]:
    """游戏详情（key 需 URL 编码，含 / 的 norm_key 用 {key:path} 匹配）。"""
    store = get_store(request)
    game = require_game(store, decode_key(key))
    return store.dto(game, detail=True)


@router.put("/games/{key:path}")
def put_game(
    request: Request,
    key: str,
    fields: Dict[str, Any] = Body(..., description="可编辑字段子集（契约 2.3 语义）"),
) -> Dict[str, Any]:
    """编辑简介与海报（description、header_image、genres、scores 等）。"""
    store = get_store(request)
    real_key = decode_key(key)
    require_game(store, real_key)
    try:
        checked = validate_edit_fields(fields)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game = store.put_fields(real_key, checked)
    return store.dto(game, detail=True)
