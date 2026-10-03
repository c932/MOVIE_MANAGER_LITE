"""
媒体库扫描（utils/library_scanner.py 的非 Qt 版本）。

扫描语义与桌面版 LibraryScanner 完全一致：
- 每个 movie_path 用 Path.rglob("*.nfo") 递归收集；
- 跳过黑名单文件夹（子串匹配）与黑名单文件名正则（pattern.match）；
- NFOParser.parse 后只有找到视频文件（video_path 非空）才算有效电影。

区别：不依赖 QThread，改成可被后台任务调用的纯函数，
进度与取消通过回调注入（对应桌面版的信号）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from models.movie import Movie
from parsers.nfo_parser import NFOParser

logger = logging.getLogger("movie_service.scanner")

# 进度回调: (current, total, message)
ProgressFn = Callable[[int, int, str], None]
# 取消检查: 抛出 JobCancelled（由调用方注入 wall_common.jobs 的 ctx.check_cancelled）
CancelFn = Callable[[], None]


def collect_nfo_files(
    movie_paths: Sequence[str],
    blacklist_folders: Sequence[str],
    blacklist_patterns: Sequence[str],
    *,
    check_cancelled: Optional[CancelFn] = None,
) -> List[Path]:
    """递归收集 NFO 文件（黑名单过滤规则与桌面版一致）。"""
    compiled = []
    for pattern in blacklist_patterns or []:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            logger.warning("黑名单正则非法，已忽略 %r: %s", pattern, exc)

    nfo_files: List[Path] = []
    for movie_path in movie_paths or []:
        if check_cancelled:
            check_cancelled()
        directory = Path(movie_path)
        if not directory.exists():
            logger.warning("电影目录不存在: %s", movie_path)
            continue
        try:
            for item in directory.rglob("*.nfo"):
                if check_cancelled:
                    check_cancelled()
                # 黑名单文件夹过滤（子串匹配）
                if any(folder in str(item) for folder in (blacklist_folders or [])):
                    logger.debug("跳过黑名单文件夹中的文件: %s", item)
                    continue
                # 黑名单文件名模式过滤
                if any(pattern.match(item.name) for pattern in compiled):
                    logger.debug("跳过黑名单文件: %s", item.name)
                    continue
                nfo_files.append(item)
        except PermissionError:
            logger.warning("无权限访问目录: %s", movie_path)
        except OSError as exc:
            logger.error("扫描目录时出错 [%s]: %s", movie_path, exc)

    return nfo_files


def scan_library(
    movie_paths: Sequence[str],
    blacklist_folders: Sequence[str],
    blacklist_patterns: Sequence[str],
    *,
    progress: Optional[ProgressFn] = None,
    check_cancelled: Optional[CancelFn] = None,
) -> List[Movie]:
    """收集 + 解析，返回有效电影列表（含视频文件的 NFO）。"""
    if progress:
        progress(0, 0, "正在收集 NFO 文件...")
    nfo_files = collect_nfo_files(
        movie_paths,
        blacklist_folders,
        blacklist_patterns,
        check_cancelled=check_cancelled,
    )
    total = len(nfo_files)
    logger.info("发现 %d 个 NFO 文件，开始解析", total)

    movies: List[Movie] = []
    for index, nfo_path in enumerate(nfo_files, 1):
        if check_cancelled:
            check_cancelled()
        movie = NFOParser.parse(str(nfo_path), include_user_rating=True)
        if movie and movie.video_path:  # 只有找到视频文件的才算有效
            movies.append(movie)
        if progress:
            progress(index, total, f"正在解析 {nfo_path.name}")

    logger.info("扫描完成，成功解析 %d 部电影", len(movies))
    return movies


def file_added_time(movie: Movie) -> float:
    """读取视频（缺失时 NFO）的磁盘 mtime 作为加入时间；读不到返回 0.0。"""
    stat_path = movie.video_path or movie.nfo_path
    if not stat_path:
        return 0.0
    try:
        return float(Path(stat_path).stat().st_mtime)
    except OSError:
        return 0.0
