"""统一刮削的数据契约；本模块不依赖 Qt。"""
from __future__ import annotations

from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
        self.video_path = Path(self.video_path)
        self.nfo_path = Path(self.nfo_path)


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


class ScrapeError(ValueError):
    """可直接向用户展示的中文领域错误。"""
