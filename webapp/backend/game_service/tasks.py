"""
游戏墙后台任务（Job 任务体）。

统一走 wall_common.jobs.JobManager：
- 任务体内定期 ctx.update(...) 上报进度、ctx.check_cancelled() 协作取消；
- 领域逻辑全部复用仓库现有模块（gamewall/），本模块只做编排。

编排语义复刻桌面版 enrichment_worker.py 的两阶段流水：
  stage=steam:  match→details→reviews（ThreadPool(3)，负缓存即时写入）
  stage=ratings: Gamersky/IGN 按设置开关串行
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

from .store import GameStore, StoreError

logger = logging.getLogger("game_service.tasks")

# 任务 kind 常量
EXCEL_DIFF_KIND = "excel.diff"
EXCEL_APPLY_KIND = "excel.apply"
ENRICH_KIND = "enrich"
LLM_CLASSIFY_KIND = "llm.classify"
SCAN_INSTALLED_KIND = "install.scan"

# 连续网络层失败熔断阈值（与桌面版 enrichment_worker.NET_FAIL_BREAKER 一致）
NET_FAIL_BREAKER = 10
STEAM_WORKERS = 3

_DETAIL_FIELDS = ("description", "release_date")


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    if isinstance(value, (int, float)):
        return value == 0
    return False


# ─────────────────── Excel 差分 / 应用 ───────────────────


def run_excel_diff(store: GameStore, ctx) -> Dict[str, Any]:
    """Excel 差分检查（kind=excel.diff）。"""
    from gamewall.excel_parser import parse_excel

    excel_path = store.excel_path()
    if not excel_path:
        raise StoreError("未配置 Excel 文件路径，请先在设置中指定")
    ctx.update(stage="解析 Excel", message=f"正在解析: {excel_path}")
    ctx.check_cancelled()
    games, meta = parse_excel(excel_path)
    ctx.update(stage="计算差异", message="正在与当前游戏库对比...")
    result = store.excel_diff(games, meta)
    ctx.update(
        stage="完成",
        message=(
            f"差分完成：新增 {result['counts']['added']} / "
            f"更新 {result['counts']['updated']} / "
            f"移除 {result['counts']['removed']}"
        ),
    )
    return result


def run_excel_apply(store: GameStore, ctx) -> Dict[str, Any]:
    """Excel 应用（kind=excel.apply）。"""
    from gamewall.excel_parser import parse_excel

    excel_path = store.excel_path()
    if not excel_path:
        raise StoreError("未配置 Excel 文件路径，请先在设置中指定")
    ctx.update(stage="解析 Excel", message=f"正在解析: {excel_path}")
    ctx.check_cancelled()
    games, meta = parse_excel(excel_path)
    ctx.update(stage="应用更新", message="正在写入缓存并重算分类...")
    result = store.excel_apply(games, meta)  # 含 reclassify
    ctx.update(
        stage="完成",
        message=(
            f"Excel 已应用：新增 {result['counts']['added']} / "
            f"更新 {result['counts']['updated']} / "
            f"移除 {result['counts']['removed']} / 共 {result.get('total', 0)} 款"
        ),
    )
    return result


# ─────────────────── 联网补全 ───────────────────


def _build_enrich_todo(
    store: GameStore,
    games: Sequence,
    *,
    scope: str,
    keys: Optional[List[str]],
    options: Dict[str, bool],
    force: bool,
) -> List[Dict[str, Any]]:
    """构建补全待办列表（语义同 enrichment_worker.__init__ 的 item 构建）。"""
    from gamewall import steam_client
    from gamewall.game_cache import GameCacheManager

    enable_steam = options.get("steam", True)
    enable_ratings = options.get("ratings", True)
    enable_gamersky, enable_ign = store.enrich_flags()

    todo: List[Dict[str, Any]] = []
    for g in games:
        item = {
            "norm_key": g.norm_key,
            "cn": g.title_cn or g.raw_name,
            "en": g.title_en,
            "appid": g.steam_appid,
            "have": {
                "description": bool(g.description),
                "release_date": bool(g.release_date),
                "reviews": g.steam_positive_pct > 0,
                "gamersky": g.gamersky_score > 0,
                "ign": g.ign_score > 0,
            },
            "missing_details": not bool(g.description) or not bool(g.release_date),
            "missing_reviews": g.steam_positive_pct <= 0,
            "missing_gamersky": g.gamersky_score <= 0,
            "missing_ign": g.ign_score <= 0,
        }
        if force:
            for k in item["have"]:
                item["have"][k] = False
            item["missing_details"] = True
            item["missing_reviews"] = True
            item["missing_gamersky"] = True
            item["missing_ign"] = True

        # 负缓存检查（仅非 force 模式）
        neg_steam = store.scraper_neg(g.norm_key, "steam_match") if not force else None
        neg_steam_detail = store.scraper_neg(g.norm_key, "steam") if not force else None

        steam_eligible = enable_steam and (
            not g.steam_appid or item["missing_details"] or item["missing_reviews"]
        )
        if steam_eligible and neg_steam and not force:
            if not steam_client.lookup_steam_alias([g.title_cn, g.title_en, g.raw_name]):
                steam_eligible = False

        item["steam_eligible"] = steam_eligible
        item["gamersky_eligible"] = enable_ratings and enable_gamersky and item["missing_gamersky"]
        item["ign_eligible"] = enable_ratings and enable_ign and item["missing_ign"]

        todo.append(item)
    return todo


def run_enrich(
    store: GameStore,
    ctx,
    *,
    scope: str = "all",
    keys: Optional[List[str]] = None,
    options: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """联网补全（kind=enrich）。

    复刻 enrichment_worker.py 的两阶段编排：
      stage=steam:  match→details→reviews，ThreadPool(3)，负缓存即时写入
      stage=ratings: Gamersky/IGN 串行
    """
    from gamewall import steam_client, rating_scrapers
    from gamewall.steam_client import SteamCancelled

    options = options or {}
    force = scope == "all" and options.get("force", False)

    # 选游戏
    all_games = store.games()
    if scope == "selected" and keys:
        from gamewall.name_utils import normalize_name
        key_set = {normalize_name(k) for k in keys}
        games = [g for g in all_games if g.norm_key in key_set]
    elif scope == "new":
        games = [g for g in all_games if GameCacheManager_needs_enrichment(g)]
    else:
        games = list(all_games)

    if not games:
        ctx.update(stage="完成", message="没有需要补全的游戏")
        return {"updated": 0, "skipped": 0, "failed": []}

    todo = _build_enrich_todo(store, games, scope=scope, keys=keys,
                              options=options, force=force)

    updated = 0
    skipped = 0
    failed: List[Dict[str, str]] = []
    consecutive_net_fail = 0
    fail_lock = __import__("threading").Lock()

    def _mark_net_fail(err: str) -> bool:
        nonlocal consecutive_net_fail
        if err.startswith("HTTP"):
            consecutive_net_fail = 0
            return False
        consecutive_net_fail += 1
        return consecutive_net_fail >= NET_FAIL_BREAKER

    # ── stage 1: Steam 全管线 ──
    steam_items = [t for t in todo if t["steam_eligible"]]
    total = len(steam_items)
    done = 0

    if steam_items:
        ctx.update(current=0, total=total, stage="steam",
                   message=f"Steam 补全 0/{total}")
        steam_client.set_cancel_check(lambda: ctx.cancelled)

        aborted = False
        try:
            with ThreadPoolExecutor(max_workers=STEAM_WORKERS) as pool:
                futures = {pool.submit(_fetch_steam_game, item, force): item
                           for item in steam_items}
                for fut in as_completed(futures):
                    if ctx.cancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    item = futures[fut]
                    negs: List[str] = []
                    try:
                        fields, err, negs = fut.result()
                    except SteamCancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.error("补全异常 %s: %s", item["norm_key"], exc)
                        fields, err = None, f"{type(exc).__name__}: {exc}"

                    if fields and any(not _is_empty(v) for v in fields.values()):
                        with fail_lock:
                            consecutive_net_fail = 0
                        game_obj, _applied = store.apply_fields(
                            item["norm_key"], fields, force=True)
                        if game_obj:
                            updated += 1
                            ctx.log(f"✓ {item['norm_key']}: Steam 资料已更新")
                    elif err:
                        with fail_lock:
                            trip = _mark_net_fail(err)
                        if trip:
                            ctx.log(f"网络熔断：连续 {NET_FAIL_BREAKER} 次失败，中止")
                            aborted = True
                            pool.shutdown(wait=False, cancel_futures=True)
                            break
                        failed.append({"key": item["norm_key"], "message": err})

                    if negs and not err:
                        with fail_lock:
                            consecutive_net_fail = 0
                        for source in negs:
                            store.record_negative(item["norm_key"], source)

                    done += 1
                    ctx.update(current=done, total=total, stage="steam",
                               message=f"Steam 补全 {done}/{total}")
                    if done % 25 == 0:
                        store.save()
        except SteamCancelled:
            pass
        finally:
            steam_client.set_cancel_check(None)

        if aborted:
            store.save()
            ctx.update(stage="error", message="网络异常，补全已中止")
            raise StoreError(f"网络连接异常，本轮联网补全中止（已完成 {updated} 款）")

    ctx.check_cancelled()

    # ── stage 2: 第三方评分（串行） ──
    rating_items = [
        t for t in todo
        if t["gamersky_eligible"] or t["ign_eligible"]
    ]
    if rating_items:
        enable_gamersky, enable_ign = store.enrich_flags()
        gamersky = rating_scrapers.GamerskyScraper() if enable_gamersky else None
        ign = rating_scrapers.IgnScraper() if enable_ign else None

        r_total = len(rating_items)
        r_done = 0
        ctx.update(current=0, total=r_total, stage="ratings",
                   message=f"补全第三方评分 0/{r_total}")

        for item in rating_items:
            ctx.check_cancelled()
            fields: Dict[str, Any] = {}
            key = item["norm_key"]

            if item["gamersky_eligible"] and gamersky:
                try:
                    score, err = gamersky.fetch_score(item["cn"])
                except Exception as exc:  # noqa: BLE001
                    score, err = 0, str(exc)
                if score:
                    fields["gamersky_score"] = score
                elif not err:
                    store.record_negative(key, "gamersky")

            if item["ign_eligible"] and ign:
                try:
                    score, err = ign.fetch_score(item["en"] or item["cn"])
                except Exception as exc:  # noqa: BLE001
                    score, err = 0, str(exc)
                if score:
                    fields["ign_score"] = score
                elif not err:
                    store.record_negative(key, "ign")

            if fields and any(not _is_empty(v) for v in fields.values()):
                game_obj, _applied = store.apply_fields(key, fields, force=True)
                if game_obj:
                    updated += 1
                    ctx.log(f"✓ {key}: 评分已更新")
            else:
                skipped += 1

            r_done += 1
            ctx.update(current=r_done, total=r_total, stage="ratings",
                       message=f"补全第三方评分 {r_done}/{r_total}")
            if r_done % 25 == 0:
                store.save()

    store.save()
    ctx.update(stage="完成",
               message=f"补全完成：更新 {updated} / 跳过 {skipped} / 失败 {len(failed)}")
    return {"updated": updated, "skipped": skipped, "failed": failed}


def _fetch_steam_game(item: Dict[str, Any], force: bool):
    """单游戏 Steam 全管线（语义同 enrichment_worker._fetch_steam_game）。"""
    from gamewall import steam_client

    fields: Dict[str, Any] = {}
    negs: List[str] = []
    appid = item["appid"]

    if not appid or force:
        matched, name, definitive = steam_client.match_appid([item["cn"], item["en"]])
        if not matched:
            if definitive:
                negs.append("steam_match")
                return fields, "", negs
            return fields, "Steam 搜索无响应", negs
        if matched != appid:
            fields["steam_appid"] = matched
            appid = matched
        if name:
            fields["steam_name"] = name

    if item["missing_details"]:
        d, err = steam_client.fetch_appdetails(appid)
        if err:
            return fields, err, negs
        fields.update(d or {})
        if not d:
            negs.append("steam")

    if item["missing_reviews"]:
        r, err = steam_client.fetch_appreviews(appid)
        if err:
            return fields, err, negs
        fields.update(r or {})
        if not r:
            negs.append("steam")

    return fields, "", negs


def GameCacheManager_needs_enrichment(game) -> bool:
    """委托 GameCacheManager.needs_enrichment（避免在模块顶层导入 game_cache）。"""
    from gamewall.game_cache import GameCacheManager
    return GameCacheManager.needs_enrichment(game)


# ─────────────────── LLM 分类 ───────────────────


def run_llm_classify(
    store: GameStore,
    ctx,
    *,
    scope: str = "all",
    keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """LLM 五档判定（kind=llm.classify）。"""
    from gamewall.llm_classifier import classify_with_llm

    base_url, api_key, model = store.llm_config()

    all_games = store.games()
    if scope == "selected" and keys:
        key_set = set(keys)
        games = [g for g in all_games if g.norm_key in key_set]
    elif scope == "new":
        games = [g for g in all_games if not g.aaa_llm_verdict]
    else:
        games = list(all_games)

    if not games:
        ctx.update(stage="完成", message="没有需要判定的游戏")
        return {"done": 0, "failed": 0}

    total = len(games)
    done_count = 0
    failed_count = 0
    ctx.update(current=0, total=total, stage="LLM 判定",
               message=f"LLM 判定 0/{total}")

    for game in games:
        ctx.check_cancelled()
        try:
            verdict = classify_with_llm(game, base_url, api_key, model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 判定异常 %s: %s", game.norm_key, exc)
            verdict = None

        if verdict is not None:
            store.set_llm_verdict(game.norm_key, verdict)
            done_count += 1
            ctx.log(
                f"✓ {game.display_title()}: {verdict.get('tier', '?')}"
                f"（置信度 {verdict.get('confidence', 'low')}）"
            )
        else:
            failed_count += 1
            ctx.log(f"✗ {game.display_title()}: LLM 判定失败")

        ctx.update(current=done_count + failed_count, total=total,
                   stage="LLM 判定",
                   message=f"LLM 判定 {done_count + failed_count}/{total}")

    ctx.update(stage="完成",
               message=f"LLM 判定完成：成功 {done_count} / 失败 {failed_count}")
    return {"done": done_count, "failed": failed_count}


# ─────────────────── 本地扫描 ───────────────────


def run_scan_installed(store: GameStore, ctx) -> Dict[str, Any]:
    """本地已安装游戏扫描（kind=install.scan）。"""
    from .scanner import scan_installed

    game_dirs = store.game_dirs()
    if not game_dirs:
        ctx.update(stage="完成", message="未配置游戏目录")
        return {"scanned": 0, "matched": 0}

    ctx.update(stage="扫描目录", message=f"正在扫描 {len(game_dirs)} 个游戏目录...")
    entries = scan_installed(game_dirs, cancelled=lambda: ctx.cancelled)
    ctx.check_cancelled()

    ctx.update(stage="匹配游戏库", message=f"正在匹配 {len(entries)} 个候选...")
    matched = store.mark_installed(entries)

    ctx.update(stage="完成",
               message=f"扫描完成：候选 {len(entries)} / 匹配 {matched}")
    return {"scanned": len(entries), "matched": matched}
