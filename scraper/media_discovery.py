"""只读视频发现；失败和取消抛出领域错误，不能解释为空影库。"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Callable, Iterable
import xml.etree.ElementTree as ET

from .scrape_models import ScrapeError, VideoTarget

VIDEO_EXTENSIONS = frozenset({'.mkv', '.mp4', '.avi', '.mov', '.m2ts', '.ts'})
_FRAGMENT = re.compile(r'(?:^|[\W_])(sample|extras?|trailers?|BDMV|VIDEO_TS)(?:$|[\W_])', re.I)
_TECH = re.compile(r'(?:^|[\W_])(?:480[pi]|720[pi]|1080[pi]|2160[pi]|4k|8k|'
                   r'bluray|blu-ray|bdrip|brrip|web[- .]?dl|webrip|hdtv|dvdrip|'
                   r'remux|[xh][ .-]?26[45]|hevc|avc|hdr10?\+?|dovi|ddp|dts|aac)(?:$|[\W_])', re.I)


def guess_title_year(name: str) -> tuple[str, str]:
    """从发布文件名提取可编辑的搜索建议，不作身份确认。"""
    text = Path(name).name
    if Path(text).suffix.lower() in VIDEO_EXTENSIONS:
        text = text[: -len(Path(text).suffix)]
    tech = _TECH.search(text)
    text = text[:tech.start()] if tech else text
    years = list(re.finditer(r'(?<!\d)(?:19|20)\d{2}(?!\d)', text))
    # 1917、2001 可以是片名，只有前方确有标题时才提取年份。
    valid = [match for match in years if text[:match.start()].strip(' ._-()[]{}')]
    year = valid[-1].group() if valid else ''
    if valid:
        text = text[:valid[-1].start()]
    text = re.sub(r'^[\[【][^\]】]*[\]】]\s*', '', text)
    text = re.sub(r'[._]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip(' -()[]{}'), year


def discover_videos(
    paths: Iterable[str | Path],
    blacklist_folders: Iterable[str] = (),
    blacklist_patterns: Iterable[str] = (),
    check_cancelled: Callable[[], object] | None = None,
) -> list[VideoTarget]:
    """发现视频并捕捉 NFO 指纹。只读，不修改缓存或媒体文件。

    check_cancelled 可抛出调用方取消异常，也可返回 True；扫描失败抛出
    ScrapeError，让调用方保留已有记录并展示错误，而非用不完整结果替换影库。
    """
    try:
        patterns = [re.compile(pattern, re.I) for pattern in blacklist_patterns]
    except re.error:
        raise ScrapeError('视频黑名单正则表达式无效') from None
    folders = tuple(str(value).casefold() for value in blacklist_folders if value)
    visited: set[Path] = set()
    videos: set[Path] = set()
    siblings: dict[Path, list[Path]] = {}

    def cancelled() -> None:
        if check_cancelled is not None and check_cancelled():
            raise ScrapeError('视频扫描已取消')

    def excluded(path: Path) -> bool:
        return (any(value in str(path).casefold() for value in folders)
                or any(_FRAGMENT.search(part) for part in path.parts)
                or any(pattern.search(path.name) for pattern in patterns))

    def entries(directory: Path) -> list[Path]:
        if directory not in siblings:
            cancelled()
            try:
                with os.scandir(directory) as iterator:
                    siblings[directory] = sorted(
                        (Path(entry.path) for entry in iterator), key=lambda p: p.name.casefold())
            except OSError:
                raise ScrapeError(f'无法访问视频目录：{directory}') from None
        return siblings[directory]

    def walk(path: Path) -> None:
        cancelled()
        if excluded(path):
            return
        try:
            path = path.resolve(strict=True)
            if path in visited:
                return
            visited.add(path)
            if path.is_dir():
                for child in entries(path):
                    # 不递归目录符号链接，避免环和媒体库外的意外遍历。
                    if child.is_symlink() and child.is_dir():
                        continue
                    walk(child)
            elif path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                videos.add(path)
        except OSError:
            raise ScrapeError(f'无法访问视频路径：{path}') from None

    for path in paths:
        walk(Path(path))
    targets: list[VideoTarget] = []
    for video in sorted(videos, key=lambda p: str(p).casefold()):
        cancelled()
        files = entries(video.parent)
        nfos = {p.name.casefold(): p for p in files if p.suffix.lower() == '.nfo'}
        nfo = nfos.get(video.with_suffix('.nfo').name.casefold())
        if nfo is None:
            count = sum(p.suffix.lower() in VIDEO_EXTENSIONS and p.is_file() and not excluded(p) for p in files)
            nfo = nfos.get('movie.nfo') if count == 1 else None
        title, year = guess_title_year(video.name)
        if title.casefold() in {'movie', 'video', 'main'} or title.isdecimal():
            title, year = guess_title_year(video.parent.name)
        target = VideoTarget(video, nfo or video.with_suffix('.nfo'), title=title, year=year,
                             existing=nfo is not None)
        if nfo is not None:
            try:
                stamp = nfo.stat()
                target.nfo_stamp = (stamp.st_mtime_ns, stamp.st_size)
                root = ET.parse(nfo).getroot()
                if root.tag != 'movie':
                    raise ValueError('root')
                target.title = root.findtext('title') or title
                target.year = root.findtext('year') or year
            except (ET.ParseError, ValueError, OSError):
                target.error = '原 NFO 损坏或无法读取，请先修复原文件'
        targets.append(target)
    return targets
