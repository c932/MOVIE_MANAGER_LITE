"""
电影墙长任务（Job 任务体）。

统一走 wall_common.jobs.JobManager：
- 任务体内定期 ctx.update(...) 上报进度、ctx.check_cancelled() 协作取消；
- 领域逻辑全部复用仓库现有模块（扫描/解析/刮削/榜单抓取），
  本模块只做编排（对应桌面版的 QThread 工作类）。
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

from scraper.scrape_settings import ScrapeSettings
from wall_common.jobs import JobContext

from .scanner import file_added_time, scan_library
from .store import MovieStore, normalize

logger = logging.getLogger("movie_service.tasks")

REFRESH_KIND = "library.refresh"
SCRAPE_KIND = "scrape.batch"
RANKINGS_KIND = "rankings.fetch"
NEWMOVIES_KIND = "newmovies.fetch"

# 两次刮削之间的节制延时（秒）。桌面版为 1.5s，这里可调小以加速批量任务。
SCRAPE_INTERVAL = 0.5

RANKING_SOURCES: Sequence[str] = ("top250", "chart", "imdb_top250")
NEW_MOVIE_SOURCES: Sequence[str] = ("nowplaying", "coming")


# ─────────────────── 媒体库刷新 ───────────────────


def run_library_refresh(store: MovieStore, ctx: JobContext, *, force: bool = False) -> Dict[str, Any]:
    """
    媒体库刷新（force=False 增量刷新，force=True 全量重建）。

    语义与桌面版 refresh_library() + LibraryScanner + on_scan_completed 一致：
    - 缓存路径校验由 store.ensure_loaded() → CacheManager.load_cache(当前路径) 完成；
    - 增量模式保留 unchanged 电影的 added_time（新电影读磁盘 mtime）；
    - 统计 added / removed / unchanged；
    - 清理失效的本地记录（观看历史 / 收藏 / 上次打开）。
    """
    started = time.time()
    cfg = store.config()
    movie_paths = [str(p) for p in cfg.get_movie_paths()]
    if not movie_paths:
        raise RuntimeError("未配置电影目录，请先在设置中添加电影目录")

    incremental = not force
    from .nas import NASPaths
    mapper = NASPaths(store.settings.data_dir)
    from utils.library_sync import read_json
    nas_libraries = read_json(mapper.file, {}).get('libraries', [])
    if nas_libraries:
        from .nas import NASManager
        nas_status = NASManager(store.settings.data_dir).status()
        connected = {item['id'] for item in nas_status['connections'] if item['connected']}
        if any(item['connection_id'] not in connected for item in nas_libraries):
            raise RuntimeError('部分 NAS 共享未连接或不可达，请在设置中连接后重试；原电影库未修改')
    scan_paths = []
    for path in movie_paths:
        try:
            if Path(path).is_dir():
                scan_paths.append(path)
            else:
                ctx.log('目录不可访问，保留该目录原有电影：' + path)
        except OSError:
            ctx.log('目录不可访问，保留该目录原有电影：' + path)
    old_by_nfo = {normalize(m.nfo_path): m for m in store.snapshot() if m.nfo_path}
    ctx.log(
        f"{'增量刷新' if incremental else '全量重建'}：旧数据 {len(old_by_nfo)} 部，"
        f"扫描目录 {len(movie_paths)} 个"
    )

    def _progress(current: int, total: int, message: str) -> None:
        ctx.update(current=current, total=total, stage="解析 NFO", message=message)

    movies = scan_library(
        scan_paths,
        cfg.get_blacklist_folders(),
        cfg.get_blacklist_patterns(),
        progress=_progress,
        check_cancelled=ctx.check_cancelled,
    )

    ctx.check_cancelled()
    ctx.update(stage="写入缓存", message="正在统计差异...")

    # added_time：增量模式沿用旧值；全量重建（或全新电影）读磁盘 mtime
    posters_cached, poster_errors = 0, 0
    for index, movie in enumerate(movies, 1):
        ctx.check_cancelled()
        physical_poster = movie.poster_path
        physical_time = file_added_time(movie)
        mapper.movie(movie)
        if physical_poster and movie.poster_path != physical_poster:
            try:
                from .media_assets import cache_source_poster
                from .store import movie_id
                posters_cached += int(cache_source_poster(store.settings.data_dir, movie_id(movie.nfo_path), physical_poster))
            except (OSError, ValueError) as exc:
                poster_errors += 1
                ctx.log(f'海报副本更新失败，保留已有缓存：{movie.title}：{exc}')
        ctx.update(current=index, total=len(movies), stage='读取媒体资料与海报', message=movie.nfo_path)
        old = old_by_nfo.get(normalize(movie.nfo_path))
        if incremental and old is not None and old.added_time:
            movie.added_time = old.added_time
        else:
            movie.added_time = physical_time or (old.added_time if old else 0.0)

    store.apply_watched(movies)

    new_paths = {normalize(m.nfo_path) for m in movies if m.nfo_path}
    old_paths = set(old_by_nfo)
    added = len(new_paths - old_paths)
    removed = 0
    unchanged = len(new_paths & old_paths)

    if movies:
        with store.lock:
            latest = store.snapshot()
            latest_by_path = {normalize(item.nfo_path): item for item in latest}
            for movie in movies:
                old = latest_by_path.get(normalize(movie.nfo_path))
                if old:
                    if incremental and old.added_time:
                        movie.added_time = old.added_time
                    if 'user' in old.ratings:
                        movie.ratings['user'] = old.ratings['user']
            # 只更新扫描覆盖的目录，不能把其他客户端或其他共享的电影删掉。
            outside = [item for item in latest if not mapper.contains(item.nfo_path, scan_paths)]
            unparsed = []
            for item in latest:
                if mapper.contains(item.nfo_path, scan_paths) and normalize(item.nfo_path) not in new_paths:
                    try:
                        if Path(mapper.source(item.nfo_path)).is_file():
                            unparsed.append(item)
                            ctx.log('NFO 本次未解析成功，保留原资料：' + item.nfo_path)
                    except OSError as exc:
                        raise RuntimeError('NAS 文件读取中断，原电影库未修改') from exc
            kept = new_paths | {normalize(item.nfo_path) for item in unparsed}
            removed = len({normalize(item.nfo_path) for item in latest if mapper.contains(item.nfo_path, scan_paths)} - kept)
            combined = movies + outside + unparsed
            store.apply_watched(combined)
            store.prune_stale_records({normalize(item.nfo_path) for item in combined if item.nfo_path})
            store.replace_all(combined)
    else:
        # 扫描结果为空（目录不可达等）时不清库，避免误删用户本地记录
        ctx.log("本次扫描未发现任何电影，跳过失效记录清理")
        removed = 0

    duration = round(time.time() - started, 2)
    message = f"刷新完成：新增 {added}，移除 {removed}，未变化 {unchanged}，共 {len(movies)} 部"
    ctx.update(current=len(movies), total=len(movies), stage="完成", message=message)
    ctx.log(message)
    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "total": len(movies),
        "duration": duration,
        "posters_cached": posters_cached,
        "poster_errors": poster_errors,
    }


# ─────────────────── 豆瓣刮削 ───────────────────


def run_scrape(store: MovieStore, ctx: JobContext, ids: Sequence[str]) -> Dict[str, Any]:
    """
    批量刮削豆瓣评分（kind=scrape.batch）。

    result: {"succeeded": [id…], "failed": [{"id","message"}…], "skipped": [id…]}
    """
    from scraper.douban_cli import scrape_single_movie

    if shutil.which("npx") is None:
        raise RuntimeError(
            "服务端未检测到 Node.js（找不到 npx 命令），无法调用豆瓣刮削。"
            "请先在服务器上安装 Node.js 后重试。"
        )

    ids = [str(i) for i in (ids or [])]
    total = len(ids)
    succeeded: List[str] = []
    failed: List[Dict[str, str]] = []
    skipped: List[str] = []

    for index, mid in enumerate(ids, 1):
        ctx.check_cancelled()
        movie = store.get(mid)
        if movie is None:
            skipped.append(mid)
            ctx.log(f"[{index}/{total}] 电影不存在，跳过: {mid}")
            continue
        if not movie.nfo_path or not movie.title:
            skipped.append(mid)
            ctx.log(f"[{index}/{total}] 缺少 NFO 路径或标题，跳过: {movie.title or mid}")
            continue

        ctx.update(current=index, total=total, stage="刮削豆瓣", message=f"正在刮削: {movie.title}")
        try:
            result = scrape_single_movie(
                movie.nfo_path,
                movie.title,
                movie.original_title or "",
                movie.year or "",
            )
        except Exception as exc:  # noqa: BLE001
            result = {"success": False, "message": f"异常: {exc}"}

        if result.get("success"):
            succeeded.append(mid)
            ctx.log(f"[{index}/{total}] ✓ {movie.title}: {result.get('message', '')}")
            if store.reparse(movie) is None:
                ctx.log(f"[{index}/{total}] 刮削成功但重新解析 NFO 失败: {movie.title}")
        else:
            message = str(result.get("message") or "未知错误")
            failed.append({"id": mid, "message": message})
            ctx.log(f"[{index}/{total}] ✗ {movie.title}: {message}")

        if index < total and SCRAPE_INTERVAL > 0:
            time.sleep(SCRAPE_INTERVAL)

    ctx.update(current=total, total=total, stage="完成",
               message=f"刮削完成：成功 {len(succeeded)}，失败 {len(failed)}，跳过 {len(skipped)}")
    return {"succeeded": succeeded, "failed": failed, "skipped": skipped}


# ─────────────────── 榜单抓取 ───────────────────


def run_rankings_fetch(
    store: MovieStore,
    ctx: JobContext,
    *,
    sources: Sequence[str],
    use_cache: bool = True,
    settings: ScrapeSettings | None = None,
) -> Dict[str, Any]:
    """
    榜单抓取（kind=rankings.fetch）。

    编排逻辑与 scraper/qt_tasks.py 的 RankingFetcher 一致（含缓存优先 /
    use_cache=False 的增量分支），进度改为 ctx.update / ctx.log。
    """
    from scraper.douban_ranking import (
        HEADERS,
        compare_with_local,
        fetch_douban_chart,
        fetch_douban_top250,
        fetch_imdb_top250,
        load_imdb_cache,
        load_ranking_cache,
        save_ranking_cache,
    )

    cache_path = store.ranking_cache_file
    sources = [s for s in sources if s in RANKING_SOURCES]
    local_movies = store.snapshot()
    stale_sources: list[str] = []
    coverage: dict[str, dict[str, int]] = {}

    def _finish(items: List[Any], from_cache: bool) -> Dict[str, Any]:
        ctx.update(current=len(items), total=len(items), stage="对比本地库",
                   message="正在与本地电影库对比...")
        ctx.log(f"榜单合计: {len(items)} 部电影")
        owned, missing = compare_with_local(items, local_movies)
        ctx.log(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
        ctx.update(stage="完成", message=f"抓取完成：本地已有 {len(owned)} 部，缺失 {len(missing)} 部")
        return {
            "sources": sources,
            "from_cache": from_cache,
            "total": len(items),
            "owned": len(owned),
            "missing": len(missing),
            "stale_sources": stale_sources,
            "coverage": coverage,
        }

    # 1) 缓存优先（use_cache=True 且缓存存在时直接复用，不发网络请求）
    if use_cache:
        cached_top250, cached_chart = load_ranking_cache(cache_path)
        cached_imdb = load_imdb_cache(cache_path) if "imdb_top250" in sources else []
        picked: List[Any] = []
        ctx.log("从本地缓存加载榜单数据...")
        if "top250" in sources and cached_top250:
            picked.extend(cached_top250)
            ctx.log(f"  豆瓣Top250: {len(cached_top250)} 部电影（缓存）")
        if "chart" in sources and cached_chart:
            picked.extend(cached_chart)
            ctx.log(f"  豆瓣热门: {len(cached_chart)} 部电影（缓存）")
        if "imdb_top250" in sources and cached_imdb:
            picked.extend(cached_imdb)
            ctx.log(f"  IMDB Top250: {len(cached_imdb)} 部电影（缓存）")
        if picked:
            return _finish(picked, True)

    # 2) 缓存不可用或强制刷新：从网络抓取（增量模式带旧缓存合并详情）
    old_top250, old_chart = load_ranking_cache(cache_path)
    old_imdb = load_imdb_cache(cache_path) if "imdb_top250" in sources else []
    all_cached = old_top250 + old_chart + old_imdb
    settings = settings or ScrapeSettings()

    top250: List[Any] = []
    chart: List[Any] = []
    imdb_top250: List[Any] = []

    if "top250" in sources:
        ctx.update(stage="抓取榜单", message="正在抓取豆瓣 Top250 榜单...")
        ctx.check_cancelled()
        if settings.proxy:
            from scraper.scrape_http import HttpClient
            http = HttpClient(settings, retries=0)
            top250 = fetch_douban_top250(cached_movies=all_cached, fetch_page=lambda url:
                http.get_bytes(url, headers=HEADERS).decode('utf-8', errors='replace'))
        else:
            top250 = fetch_douban_top250(cached_movies=all_cached)
        ctx.log(f"  Top250 获取完成: {len(top250)} 部电影")

    if "chart" in sources:
        ctx.update(stage="抓取榜单", message="正在抓取豆瓣近期热门榜单...")
        ctx.check_cancelled()
        chart = fetch_douban_chart(cached_movies=all_cached, fetch_details=True)
        ctx.log(f"  热门榜单获取完成: {len(chart)} 部电影")

    if "imdb_top250" in sources:
        ctx.update(stage="抓取榜单", message="正在抓取 IMDB Top250 榜单...")
        ctx.check_cancelled()
        imdb_top250 = fetch_imdb_top250(cached_movies=all_cached)
        ctx.log(f"  IMDB Top250 获取完成: {len(imdb_top250)} 部电影")

    ctx.check_cancelled()

    # 保留完整旧榜单时仍补查资料，且不推进排名更新时间。
    from .browse_cache import enrich_top250, warm_browse

    def refresh_top(source, rows, old):
        if source not in sources:
            return rows
        if old and (not rows or (len(old) == 250 and {row.rank for row in rows} != set(range(1, 251)))):
            stale_sources.append(source)
            rows = old
        if rows:
            coverage[source] = enrich_top250(store.settings.data_dir, store.settings.cover_cache_dir,
                                             rows, old, local_movies, settings, ctx)
        return rows

    top250 = refresh_top('top250', top250, old_top250)
    imdb_top250 = refresh_top('imdb_top250', imdb_top250, old_imdb)
    if any(not items for source, items in (("top250", top250), ("chart", chart), ("imdb_top250", imdb_top250))
           if source in sources):
        raise ValueError('榜单来源未返回有效资料，请稍后重试；旧缓存已保留。')

    if chart:
        warm_browse(store.settings.data_dir, store.settings.cover_cache_dir, (
            {'poster_url': item.poster_url, 'douban_id': item.douban_id, 'plot': item.plot} for item in chart
        ), ctx)
    with store.lock:
        if not save_ranking_cache(top250, chart, imdb_top250 or None, cache_path=cache_path,
                                  preserve_timestamps=frozenset(stale_sources)):
            raise OSError('榜单缓存保存失败，请稍后重试。')
    result = _finish(top250 + chart + imdb_top250, False)
    if coverage:
        totals = [sum(stats[key] for stats in coverage.values()) for key in ('ratings', 'plots', 'posters')]
        prefix = '来源暂不可用或返回不完整，已保留部分榜单的原排名。' if stale_sources else '排名已更新。'
        result['summary'] = f'{prefix}已有评分 {totals[0]} 部、简介 {totals[1]} 部、海报 {totals[2]} 部。'
    return result


# ─────────────────── 新片抓取 ───────────────────


def run_newmovies_fetch(
    store: MovieStore,
    ctx: JobContext,
    *,
    sources: Sequence[str],
    use_cache: bool = True,
) -> Dict[str, Any]:
    """新片抓取（kind=newmovies.fetch），编排同 scraper/qt_tasks.NewMovieFetcher。"""
    from scraper.new_movie_checker import (
        compare_with_local as compare_new_with_local,
        fetch_coming_soon,
        fetch_nowplaying,
        load_new_movie_cache,
        save_new_movie_cache,
    )

    cache_path = store.new_movie_cache_file
    sources = [s for s in sources if s in NEW_MOVIE_SOURCES]
    local_movies = store.snapshot()

    def _finish(items: List[Any], from_cache: bool) -> Dict[str, Any]:
        ctx.update(current=len(items), total=len(items), stage="对比本地库",
                   message="正在与本地电影库对比...")
        ctx.log(f"新片合计: {len(items)} 部电影")
        owned, missing = compare_new_with_local(items, local_movies)
        ctx.log(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
        ctx.update(stage="完成", message=f"获取完成：本地已有 {len(owned)} 部，缺失 {len(missing)} 部")
        return {
            "sources": sources,
            "from_cache": from_cache,
            "total": len(items),
            "owned": len(owned),
            "missing": len(missing),
        }

    if use_cache:
        cached_nowplaying, cached_coming = load_new_movie_cache(cache_path)
        picked: List[Any] = []
        ctx.log("从本地缓存加载新片数据...")
        if "nowplaying" in sources and cached_nowplaying:
            picked.extend(cached_nowplaying)
            ctx.log(f"  正在热映: {len(cached_nowplaying)} 部（缓存）")
        if "coming" in sources and cached_coming:
            picked.extend(cached_coming)
            ctx.log(f"  即将上映: {len(cached_coming)} 部（缓存）")
        if picked:
            return _finish(picked, True)

    cached_nowplaying, cached_coming = (
        load_new_movie_cache(cache_path) if not use_cache else ([], [])
    )
    all_cached = list(cached_nowplaying) + list(cached_coming)

    nowplaying: List[Any] = []
    coming: List[Any] = []
    if "nowplaying" in sources:
        ctx.update(stage="抓取新片", message="正在获取豆瓣正在热映...")
        ctx.check_cancelled()
        nowplaying = fetch_nowplaying(cached_movies=all_cached)
        ctx.log(f"  正在热映: {len(nowplaying)} 部")

    if "coming" in sources:
        ctx.update(stage="抓取新片", message="正在获取豆瓣即将上映...")
        ctx.check_cancelled()
        coming = fetch_coming_soon(cached_movies=all_cached)
        ctx.log(f"  即将上映: {len(coming)} 部")

    ctx.check_cancelled()

    # 保存缓存（合并：未请求的来源保留旧缓存）
    save_nowplaying = nowplaying or (cached_nowplaying if not use_cache else [])
    save_coming = coming or (cached_coming if not use_cache else [])

    from .browse_cache import warm_browse
    warm_browse(store.settings.data_dir, store.settings.cover_cache_dir, (
        {'poster_url': item.poster_url, 'douban_id': item.douban_id} for item in nowplaying + coming
    ), ctx)
    if save_nowplaying or save_coming:
        with store.lock:
            save_new_movie_cache(save_nowplaying, save_coming, cache_path=cache_path)
    return _finish(nowplaying + coming, False)
