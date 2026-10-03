"""
封面解析与刷新（契约 3.2：GET /games/{key}/cover、POST /games/{key}/cover/refresh）。

- `custom`：本地自定义封面 `{data_dir}/posters/{key}_custom.jpg`
- `grid`：Steam 竖版封面（`Game.get_cover_urls()` 候选链，服务器代理缓存）
- 默认（不传 variant）：custom → grid 逐级兜底，都没有则 404（前端画占位）

渲染统一走 `wall_common.images.render_image`，并复用桌面版 cover_loader 的
「智能模式」：源图宽高比 > 1.5 视为横图 → contain 居中 + 深灰底，否则 cover 裁切。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PIL import Image

from wall_common.images import ImageError, _cache_key, cached_remote, invalidate

from .store import custom_cover_path

logger = logging.getLogger("game_service.covers")

VARIANTS = ("custom", "grid")
LANDSCAPE_RATIO = 1.5
LANDSCAPE_BG = (30, 30, 30)


def resolve_cover_path(store, game, *, variant: Optional[str] = None,
                       refresh: bool = False) -> Path:
    """
    解析封面源文件路径。

    Raises:
        ImageError(404): 没有可用封面
        ImageError(502): refresh=True 且远程拉取失败（且无旧缓存可回退）
    """
    custom = custom_cover_path(store.data_dir, game.norm_key)
    if variant == "custom":
        if not custom.is_file():
            raise ImageError("该游戏没有自定义封面", status_code=404)
        return custom
    if variant == "grid":
        path = _resolve_grid(store, game, refresh=refresh)
        if path is None:
            raise ImageError("该游戏没有可用封面", status_code=404)
        return path

    # 默认链：自定义优先，其次 Steam 竖版
    if custom.is_file():
        return custom
    path = _resolve_grid(store, game, refresh=refresh)
    if path is None:
        raise ImageError("该游戏没有可用封面", status_code=404)
    return path


def _resolve_grid(store, game, *, refresh: bool) -> Optional[Path]:
    """按候选链取第一张可用的 Steam 封面；refresh=True 强制回源。"""
    urls: List[str] = [url for url in game.get_cover_urls() if url]
    if not urls:
        return None
    cache_dir = store.settings.cover_cache_dir

    if not refresh:
        for url in urls:
            try:
                return cached_remote(url, cache_dir)
            except ImageError as exc:
                logger.debug("封面候选不可用 %s: %s", url, exc)
        return None

    last: Optional[Exception] = None
    for url in urls:
        try:
            return cached_remote(url, cache_dir, refresh=True)
        except ImageError as exc:
            last = exc
    # 新图拉取失败时回退到已有缓存（哪怕已过期），保证前端还能显示旧图
    for url in urls:
        try:
            return cached_remote(url, cache_dir)
        except ImageError as exc:
            last = exc
    raise ImageError(f"封面拉取失败: {last}", status_code=502)


def smart_render_mode(source: Path) -> Tuple[str, Tuple[int, int, int]]:
    """智能渲染模式：横图（比例 > 1.5）contain + 深灰底，其余 cover 裁切。"""
    try:
        with Image.open(source) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001  损坏图片交给 render_image 报 404
        logger.debug("读取封面尺寸失败 %s: %s", source, exc)
        return "cover", (0, 0, 0)
    if height > 0 and width / height > LANDSCAPE_RATIO:
        return "contain", LANDSCAPE_BG
    return "cover", (0, 0, 0)


def drop_cover_cache(settings, urls: Iterable[str]) -> int:
    """
    丢弃指定 URL 的远程封面缓存与其缩略图渲染（appid/header_image 变更后调用）。

    旧图与新图都可能命中缓存，调用方应传入新旧 URL 的并集。
    返回删除的文件数。
    """
    removed = 0
    for url in {url for url in urls if url}:
        cached = Path(settings.cover_cache_dir) / f"{_cache_key(url)}.img"
        if cached.is_file():
            try:
                # 缩略图缓存文件名带源图哈希前缀，按缓存路径精确失效
                removed += invalidate(cached, settings.image_cache_dir)
                cached.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("删除封面缓存失败 %s: %s", cached, exc)
    return removed
