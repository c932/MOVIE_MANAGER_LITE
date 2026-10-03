"""
服务端图片处理（替代桌面版 QPixmap 缩略图缓存）。

- render_image(): 按请求尺寸从源图生成缩略图，磁盘缓存按 (源路径, mtime, 尺寸, 模式) 失效
- fetch_remote(): 拉取远程图片（Steam CDN / 豆瓣榜单海报等）并缓存
- ImageError:    由 factory 转成 HTTP 响应
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("wall_common.images")

# 允许加载超大图（电影海报原图常见 2000px+），但保留 Pillow 的解压炸弹保护
Image.MAX_IMAGE_PIXELS = 120_000_000

USER_AGENT = "LocalMovieWall-Web/1.0"

DEFAULT_QUALITY = 82
MAX_REQUEST_EDGE = 1400
REMOTE_TTL = 7 * 24 * 3600  # 远程封面缓存有效期（秒），过期后下次访问重新校验


class ImageError(Exception):
    """图片不可用（源文件缺失/损坏/尺寸非法）。"""

    def __init__(self, message: str, status_code: int = 404):
        super().__init__(message)
        self.status_code = status_code


def _cache_key(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()


def render_image(
    source: Union[str, Path],
    width: int,
    height: int,
    *,
    mode: str = "cover",
    cache_dir: Union[str, Path],
    quality: int = DEFAULT_QUALITY,
    bg: tuple = (0, 0, 0),
) -> bytes:
    """
    把源图渲染为固定尺寸的 JPEG 字节。

    Args:
        source:  源图片路径（本地文件）
        width:   目标宽（1..MAX_REQUEST_EDGE）
        height:  目标高（1..MAX_REQUEST_EDGE）
        mode:    cover = 裁剪填满（海报墙）；contain = 等比缩放留黑边（游戏封面）
        cache_dir: 缩略图缓存目录
        quality: JPEG 质量
        bg:      contain 模式的底色
    """
    if not (0 < width <= MAX_REQUEST_EDGE and 0 < height <= MAX_REQUEST_EDGE):
        raise ImageError(f"非法的图片尺寸 {width}x{height}", status_code=400)
    if mode not in ("cover", "contain"):
        raise ImageError(f"非法的图片模式 {mode!r}", status_code=400)

    src = Path(source) if source else None
    if not src or not src.is_file():
        raise ImageError("源图片不存在")

    try:
        mtime = int(src.stat().st_mtime)
    except OSError as exc:
        raise ImageError("无法读取源图片") from exc

    cache_dir = Path(cache_dir)
    # 缓存文件名 = 源图哈希前缀 + 渲染参数哈希：
    # 前缀支持按源图精确失效（invalidate），后缀 (含 mtime) 支持源图变化自动失效
    src_key = _cache_key(src)
    param_key = _cache_key(mtime, width, height, mode, quality, bg)
    cache_file = cache_dir / f"{src_key}_{param_key}.jpg"
    if cache_file.is_file():
        return cache_file.read_bytes()

    try:
        with Image.open(src) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            rendered = _fit(img, width, height, mode, bg)
            if rendered.mode != "RGB":
                rendered = rendered.convert("RGB")
            buf = io.BytesIO()
            rendered.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageError("源图片无法解码") from exc

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir / f"{src_key}_{param_key}.{os.getpid()}.tmp"
        tmp.write_bytes(data)
        tmp.replace(cache_file)
    except OSError as exc:  # 缓存写失败不阻断响应
        logger.warning("缩略图缓存写入失败 %s: %s", cache_file, exc)

    return data


def _fit(img: Image.Image, width: int, height: int, mode: str, bg: tuple) -> Image.Image:
    if mode == "cover":
        # 纵向海报略偏上取景（人物面部多在上半部）
        return ImageOps.fit(img, (width, height), method=Image.LANCZOS,
                            centering=(0.5, 0.4))
    canvas = Image.new("RGB", (width, height), bg)
    fitted = img.copy()
    fitted.thumbnail((width, height), Image.LANCZOS)
    if fitted.mode != "RGB":
        # 透明图先合成到底色上
        base = Image.new("RGB", fitted.size, bg)
        alpha = fitted.convert("RGBA")
        base.paste(alpha, mask=alpha.getchannel("A"))
        fitted = base
    left = (width - fitted.width) // 2
    top = (height - fitted.height) // 2
    canvas.paste(fitted, (left, top))
    return canvas


def fetch_remote(url: str, timeout: float = 12.0, max_bytes: int = 30 * 1024 * 1024) -> bytes:
    """拉取远程图片字节（带 UA、大小上限）。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ImageError("远程图片超出大小限制", status_code=502)
            data = resp.read(max_bytes + 1)
    except ImageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageError(f"远程图片获取失败: {exc}", status_code=502) from exc
    if len(data) > max_bytes:
        raise ImageError("远程图片超出大小限制", status_code=502)
    return data


def cached_remote(
    url: str,
    cache_dir: Union[str, Path],
    *,
    filename: Optional[str] = None,
    refresh: bool = False,
    ttl: float = REMOTE_TTL,
    timeout: float = 12.0,
) -> Path:
    """
    返回远程图片的本地缓存路径；不存在或过期(refresh=True/ttl到期)时重新拉取。
    命中且未过期时直接返回缓存。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = filename or _cache_key(url)
    dest = cache_dir / f"{name}.img"

    if dest.is_file() and not refresh:
        age = time.time() - dest.stat().st_mtime
        if age < ttl:
            return dest

    data = fetch_remote(url, timeout=timeout)
    try:
        # 校验确实是图片
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as exc:  # noqa: BLE001
        if dest.is_file():
            return dest  # 新内容损坏但旧缓存可用
        raise ImageError("远程图片内容无效", status_code=502) from exc

    tmp = cache_dir / f"{name}.{os.getpid()}.tmp"
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def invalidate(source: Union[str, Path], cache_dir: Union[str, Path]) -> int:
    """失效某源图的全部缩略图缓存（缓存文件名带源图哈希前缀），返回删除数量。"""
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return 0
    prefix = _cache_key(Path(source)) + "_"
    removed = 0
    for f in cache_dir.glob(f"{prefix}*.jpg"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed
