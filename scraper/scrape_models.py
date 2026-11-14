"""统一刮削的数据契约；本模块不依赖 Qt。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import os
from pathlib import Path
from typing import Any


@dataclass
class Candidate:
    source: str
    id: str
    title: str
    original_title: str = ""
    year: str = ""
    overview: str = ""
    poster_url: str = ""
    media_type: str = "movie"


@dataclass
class Artwork:
    url: str
    preview_url: str = ""
    language: str = ""
    width: int = 0
    height: int = 0
    source: str = "tmdb"


@dataclass
class Metadata:
    source: str
    id: str
    fields: dict[str, Any] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)
    ratings: dict[str, float] = field(default_factory=dict)
    votes: dict[str, int] = field(default_factory=dict)
    artwork: list[Artwork] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class VideoTarget:
    video_path: Path
    nfo_path: Path
    title: str = ""
    year: str = ""
    existing: bool = False
    error: str = ""
    nfo_stamp: tuple[int, int] | None = None
    nfo_fingerprint: str | None = None
    version_captured: bool = False
    error_kind: str = ""
    error_detail: str = ""

    def __post_init__(self) -> None:
        self.video_path = Path(self.video_path)
        self.nfo_path = Path(self.nfo_path)


def can_rebuild_nfo(target: VideoTarget) -> bool:
    """只有可读取的说明文件或异常 XML 可经用户授权备份重建。"""
    return target.error_kind in {"not_metadata", "invalid_xml"}


@dataclass
class ScanProgress:
    stage: str
    current: int
    total: int
    directory: str
    found: int = 0


@dataclass
class ScrapeDraft:
    target: VideoTarget
    fields: dict[str, Any] = field(default_factory=dict)
    artwork: list[Artwork] = field(default_factory=list)
    poster: Artwork | None = None
    confirmed: bool = False
    replace_identity: bool = False
    warnings: list[str] = field(default_factory=list)
    expected_files: dict[str, str | None] = field(default_factory=dict)
    votes: dict[str, int] = field(default_factory=dict)
    rebuild_nfo: bool = False


class ScrapeError(ValueError):
    """可直接向用户展示的中文领域错误。"""


def _nfo_version(path: Path) -> tuple[tuple[int, int] | None, str | None]:
    """读取同一文件版本；不存在是有效版本，读取错误不是不存在。"""
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise ScrapeError("无法读取 NFO 版本，请检查文件权限或网络") from exc
    try:
        with stream:
            before = os.fstat(stream.fileno())
            digest = hashlib.sha256(stream.read()).hexdigest()
            after = os.fstat(stream.fileno())
        current = path.stat()
    except OSError as exc:
        raise ScrapeError("NFO 在读取版本时已改变或暂时无法访问，请重新加载") from exc
    stamps = {(s.st_mtime_ns, s.st_size, s.st_ino) for s in (before, after, current)}
    if len(stamps) != 1:
        raise ScrapeError("NFO 在读取版本时已改变，请重新加载")
    return (current.st_mtime_ns, current.st_size), digest


def validate_target_version(target: VideoTarget) -> None:
    if not target.version_captured and target.nfo_stamp is None:
        return
    stamp, digest = _nfo_version(target.nfo_path)
    if (target.nfo_stamp is not None and stamp != target.nfo_stamp
            or target.version_captured and digest != target.nfo_fingerprint):
        raise ScrapeError("NFO 自请求开始后已改变，存在保存冲突，请重新加载")


def capture_target_version(target: VideoTarget) -> VideoTarget:
    """后台请求前捕获 NFO；兼容只提供扫描时间戳的旧调用方。"""
    if target.version_captured:
        validate_target_version(target)
        return replace(target)
    stamp, digest = _nfo_version(target.nfo_path)
    if target.nfo_stamp is not None and stamp != target.nfo_stamp:
        raise ScrapeError("NFO 自扫描后已改变，请重新加载")
    return replace(target, nfo_stamp=stamp, nfo_fingerprint=digest, version_captured=True)
