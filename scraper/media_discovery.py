"""只读视频发现；失败和取消抛出领域错误，不能解释为空影库。"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Callable, Iterable
from parsers.nfo_parser import NFOParser

from .nfo_inspection import inspect_nfo
from .scrape_models import ScanProgress, ScrapeError, VideoTarget

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
    progress: Callable[[ScanProgress], None] | None = None,
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
    scanned_directories = 0

    def report(stage: str, current: int, total: int, directory: Path | str) -> None:
        if progress is not None:
            progress(ScanProgress(stage, current, total, str(directory), len(videos)))

    def cancelled() -> None:
        if check_cancelled is not None and check_cancelled():
            raise ScrapeError('视频扫描已取消')

    def excluded(path: Path) -> bool:
        return (any(value in str(path).casefold() for value in folders)
                or any(_FRAGMENT.search(part) for part in path.parts)
                or any(pattern.search(path.name) for pattern in patterns))

    def entries(directory: Path) -> list[Path]:
        nonlocal scanned_directories
        if directory not in siblings:
            cancelled()
            try:
                with os.scandir(directory) as iterator:
                    siblings[directory] = sorted(
                        (Path(entry.path) for entry in iterator), key=lambda p: p.name.casefold())
            except OSError:
                raise ScrapeError(f'无法访问视频目录：{directory}') from None
            scanned_directories += 1
            report('扫描目录', scanned_directories, 0, directory)
        return siblings[directory]

    def walk(path: Path, boundary: Path | None = None) -> None:
        cancelled()
        if excluded(path):
            return
        try:
            path = path.resolve(strict=True)
            # Windows junction 在 Py3.11 下 is_symlink() 为 False，必须按
            # 解析后的路径约束递归边界；显式根目录自身可以是联接或网络库。
            if boundary is not None and not path.is_relative_to(boundary):
                return
            if boundary is None:
                boundary = path if path.is_dir() else path.parent
            if path in visited:
                return
            visited.add(path)
            is_directory = path.is_dir()
            is_video = path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        except OSError:
            raise ScrapeError(f'无法访问视频路径：{path}') from None
        # 回调与递归放在文件系统异常处理之外；调用方异常必须原样传播。
        if is_directory:
            for child in entries(path):
                if child.is_symlink() and child.is_dir():
                    continue
                walk(child, boundary)
        elif is_video:
            videos.add(path)

    for path in paths:
        walk(Path(path))
    # 显式传入视频时，也先读取父目录，保证所有扫描事件先于解析事件。
    for directory in sorted({video.parent for video in videos}, key=str):
        entries(directory)
    targets: list[VideoTarget] = []
    for video in sorted(videos, key=lambda p: str(p).casefold()):
        cancelled()
        files = entries(video.parent)
        directory_videos = [p for p in files if p.suffix.lower() in VIDEO_EXTENSIONS
                            and p.is_file() and not excluded(p)]
        same_stem = sum(p.stem.casefold() == video.stem.casefold() for p in directory_videos)
        nfos = {p.name.casefold(): p for p in files if p.suffix.lower() == '.nfo'}
        nfo = nfos.get(video.with_suffix('.nfo').name.casefold())
        if nfo is None:
            nfo = nfos.get('movie.nfo') if len(directory_videos) == 1 else None
        title, year = guess_title_year(video.name)
        if title.casefold() in {'movie', 'video', 'main'} or title.isdecimal():
            title, year = guess_title_year(video.parent.name)
        target = VideoTarget(video, nfo or video.with_suffix('.nfo'), title=title, year=year,
                             existing=nfo is not None)
        if nfo is not None:
            root = inspect_nfo(target)
            if root is not None:
                target.title = root.findtext('title') or title
                target.year = root.findtext('year') or year
                target.douban_complete = NFOParser.has_complete_douban(root)
        if same_stem > 1:
            conflict = 'NFO 路径冲突：同目录存在多个同名视频，请先区分视频文件名后再保存'
            target.error = f'{target.error}；{conflict}' if target.error else conflict
            target.error_kind = 'path_conflict'
            target.error_detail = target.error
        targets.append(target)
        report('解析 NFO', len(targets), len(videos), video.parent)
    cancelled()
    report('扫描完成', len(targets), len(videos), targets[-1].video_path.parent if targets else '')
    return targets
