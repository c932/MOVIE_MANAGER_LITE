"""
Steam 联网补全工作线程

Steam 侧为「每游戏全管线」并发流水（单游戏内 匹配→详情→好评率 一次完成，
信息按顺序渐进完整出现；全局限速器约束总请求率，429/5xx 自动退避）：
1. Steam 全管线 —— 无 appid 先匹配；有 appid 随即补详情与好评率（3 线程）
2. 第三方 —— 缺游民星空/IGN 评分的游戏（尽力而为，串行温和执行）

线程安全约定：
- worker 不直接修改 Game 对象与缓存，仅通过信号交回主线程合并
- 每个 item 只由一个任务线程处理，attempted/have 标志无竞争
- 确定性负结果（HTTP 层成功但确认无数据）随条目完成即时经 negative_recorded
  发出，由主线程写入 scraper_neg（7 天内跳过重试）——中途关闭程序也不丢进度
- 网络层失败的条目不记负结果，避免把断网误判为无数据
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

from gamewall import rating_scrapers
from gamewall import steam_client
from gamewall.steam_client import SteamCancelled

logger = logging.getLogger(__name__)

# 连续网络层失败熔断阈值（断网时避免全量空转）
NET_FAIL_BREAKER = 10
# Steam 管线并发线程数（全局限速器约束总请求率）
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


class EnrichmentWorker(QThread):
    progress_updated = pyqtSignal(int, int)      # (done, total)
    stage_changed = pyqtSignal(str)
    game_enriched = pyqtSignal(str, dict)        # (norm_key, fields)
    negative_recorded = pyqtSignal(str, str)     # (norm_key, source)
    finished_with = pyqtSignal(str)              # 汇总信息（不用内置 finished，避免遮蔽）
    failed = pyqtSignal(str)

    def __init__(self, games, parent=None, enable_steam: bool = True,
                 enable_gamersky: bool = True, enable_ign: bool = False,
                 steam_candidates=None, gamersky_candidates=None, ign_candidates=None):
        super().__init__(parent)
        self._enable_steam = enable_steam
        self._enable_gamersky = enable_gamersky
        self._enable_ign = enable_ign
        self._gamersky = rating_scrapers.GamerskyScraper() if enable_gamersky else None
        self._ign = rating_scrapers.IgnScraper() if enable_ign else None
        steam_keys = set(steam_candidates) if steam_candidates is not None else None
        gamersky_keys = set(gamersky_candidates) if gamersky_candidates is not None else None
        ign_keys = set(ign_candidates) if ign_candidates is not None else None
        # 只读快照：worker 线程内不触碰 Game 对象本身
        self._todo = []
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
                "attempted_match": False,
                "attempted_details": False,
                "attempted_reviews": False,
                "attempted_gamersky": False,
                "attempted_ign": False,
            }
            item["missing_details"] = any(not item["have"][f] for f in _DETAIL_FIELDS)
            item["missing_reviews"] = not item["have"]["reviews"]
            item["missing_gamersky"] = not item["have"]["gamersky"]
            item["missing_ign"] = not item["have"]["ign"]
            item["steam_eligible"] = self._enable_steam and (
                g.norm_key in steam_keys if steam_keys is not None
                else (not item["appid"] or item["missing_details"] or item["missing_reviews"]))
            item["gamersky_eligible"] = self._enable_gamersky and (
                g.norm_key in gamersky_keys if gamersky_keys is not None
                else item["missing_gamersky"])
            item["ign_eligible"] = self._enable_ign and (
                g.norm_key in ign_keys if ign_keys is not None else item["missing_ign"])
            self._todo.append(item)
        self._cancelled = False
        self._abort = False
        self._consecutive_net_fail = 0
        self._fail_lock = threading.Lock()
        self._done = 0
        self._total = 0

    def cancel(self):
        self._cancelled = True

    # ── 内部工具 ──
    def _mark_net_fail(self, err: str) -> bool:
        """记录失败；网络层错误连续达到阈值返回 True（要求中止本轮）"""
        if err.startswith("HTTP"):
            self._consecutive_net_fail = 0
            return False
        self._consecutive_net_fail += 1
        return self._consecutive_net_fail >= NET_FAIL_BREAKER

    def run(self):
        steam_client.set_cancel_check(lambda: self._cancelled)
        started = time.time()
        aborted = False
        cancelled = False
        try:
            steam_items = [t for t in self._todo if t["steam_eligible"]]
            if steam_items:
                aborted = self._run_steam_pipeline(steam_items)

            if not aborted and not self._cancelled:
                rating_items = [
                    t for t in self._todo
                    if ((t["gamersky_eligible"] and t["missing_gamersky"])
                        or (t["ign_eligible"] and t["missing_ign"]))
                ]

                def fetch_ratings(item):
                    fields = {}
                    if item["gamersky_eligible"] and item["missing_gamersky"]:
                        item["attempted_gamersky"] = True
                        score, err = self._gamersky.fetch_score(item["cn"])
                        if score:
                            fields["gamersky_score"] = score
                        else:
                            # 尽力而为数据源：未得分即记负（与原整轮补记语义一致）
                            self.negative_recorded.emit(item["norm_key"], "gamersky")
                            if err:
                                logger.debug(f"游民星空评分失败 {item['norm_key']}: {err}")
                    if item["ign_eligible"] and item["missing_ign"]:
                        item["attempted_ign"] = True
                        score, err = self._ign.fetch_score(item["en"] or item["cn"])
                        if score:
                            fields["ign_score"] = score
                        else:
                            self.negative_recorded.emit(item["norm_key"], "ign")
                            if err:
                                logger.debug(f"IGN 评分失败 {item['norm_key']}: {err}")
                    return fields, ""

                def on_ratings(item, fields):
                    if not _is_empty(fields.get("gamersky_score")):
                        item["have"]["gamersky"] = True
                        item["missing_gamersky"] = False
                    if not _is_empty(fields.get("ign_score")):
                        item["have"]["ign"] = True
                        item["missing_ign"] = False

                self._run_pass_with(
                    rating_items, "attempted_ratings", on_ratings, fetch_ratings,
                    "补全第三方评分")
        except SteamCancelled:
            cancelled = True
        finally:
            elapsed = time.time() - started
            logger.info(f"联网补全结束: 用时 {elapsed:.0f}s, cancelled={cancelled or self._cancelled}")

        if cancelled or self._cancelled:
            self.finished_with.emit("已取消联网补全")
        elif aborted:
            pass  # failed 信号已发出
        else:
            self.finished_with.emit(f"联网补全完成（用时 {time.time() - started:.0f} 秒）")

    # ── Steam 每游戏全管线（并发） ──
    def _run_steam_pipeline(self, items) -> bool:
        """匹配→详情→好评率 一气呵成；返回 True 表示网络熔断中止"""
        if not items:
            return False
        self.stage_changed.emit("补全 Steam 数据")
        self._total += len(items)
        self.progress_updated.emit(self._done, self._total)
        with ThreadPoolExecutor(max_workers=STEAM_WORKERS) as pool:
            futures = {pool.submit(self._fetch_steam_game, item): item
                       for item in items}
            for fut in as_completed(futures):
                if self._cancelled or self._abort:
                    pool.shutdown(wait=False, cancel_futures=True)
                    return self._abort
                item = futures[fut]
                negs = []
                try:
                    fields, err, negs = fut.result()
                except SteamCancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    return False
                except Exception as e:
                    logger.error(f"补全异常 {item['norm_key']}: {e}")
                    fields, err = None, f"{type(e).__name__}: {e}"
                if fields and any(not _is_empty(v) for v in fields.values()):
                    with self._fail_lock:
                        self._consecutive_net_fail = 0
                    self._on_steam_fields(item, fields)
                    self.game_enriched.emit(item["norm_key"], fields)
                elif err:
                    logger.debug(f"补全失败 {item['norm_key']}: {err}")
                    with self._fail_lock:
                        trip = self._mark_net_fail(err)
                    if trip:
                        self._abort = True
                        self.failed.emit(f"网络连接异常（{err}），本轮联网补全中止")
                        pool.shutdown(wait=False, cancel_futures=True)
                        return True
                if negs:
                    # 确定性无数据（HTTP 层成功），即时落负结果，进度单调递减；
                    # 同条目后续请求网络失败时不重置熔断计数
                    if not err:
                        with self._fail_lock:
                            self._consecutive_net_fail = 0
                    for source in negs:
                        self.negative_recorded.emit(item["norm_key"], source)
                self._done += 1
                self.progress_updated.emit(self._done, self._total)
        return False

    def _fetch_steam_game(self, item):
        """单游戏全管线：无 appid 先匹配，随即补详情与好评率。
        返回 (fields, err, negs)；negs 为确定性负结果来源（err 非空时恒为空）"""
        fields = {}
        negs = []
        if not item["appid"]:
            item["attempted_match"] = True
            appid, name, definitive = steam_client.match_appid([item["cn"], item["en"]])
            if not appid:
                if definitive:
                    negs.append("steam_match")
                    return fields, "", negs
                return fields, "Steam 搜索无响应", negs
            fields["steam_appid"] = appid
            if name:
                fields["steam_name"] = name
            item["appid"] = appid
        if item["missing_details"]:
            item["attempted_details"] = True
            d, err = steam_client.fetch_appdetails(item["appid"])
            if err:
                return fields, err, negs
            fields.update(d or {})
            if not d:
                negs.append("steam")   # 商店页不存在（下架/地区锁等）
        if item["missing_reviews"]:
            item["attempted_reviews"] = True
            r, err = steam_client.fetch_appreviews(item["appid"])
            if err:
                return fields, err, negs
            fields.update(r or {})
            if not r:
                negs.append("steam")   # 0 条评价
        return fields, "", negs

    @staticmethod
    def _on_steam_fields(item, fields):
        """发信号前同步 worker 侧 have/missing 状态"""
        if fields.get("steam_appid"):
            item["appid"] = fields["steam_appid"]
        for f in _DETAIL_FIELDS:
            if f in fields and not _is_empty(fields[f]):
                item["have"][f] = True
        item["missing_details"] = any(not item["have"][f] for f in _DETAIL_FIELDS)
        if not _is_empty(fields.get("steam_positive_pct")):
            item["have"]["reviews"] = True
            item["missing_reviews"] = False

    # ── 第三方评分（串行温和执行） ──
    def _run_pass_with(self, items, attempt_flag, on_fields, fetch_fn, stage_label) -> bool:
        """执行一个串行补全阶段；on_fields(item, fields) 在发信号前同步 worker 侧状态"""
        if not items:
            return False
        self.stage_changed.emit(stage_label)
        self._total += len(items)
        self.progress_updated.emit(self._done, self._total)
        for item in items:
            if self._cancelled or self._abort:
                return self._abort
            key = item["norm_key"]
            try:
                fields, err = fetch_fn(item)
            except SteamCancelled:
                return False
            except Exception as e:
                logger.error(f"补全异常 {key}: {e}")
                fields, err = None, f"{type(e).__name__}: {e}"
            item[attempt_flag] = True
            if fields and any(not _is_empty(v) for v in fields.values()):
                self._consecutive_net_fail = 0
                on_fields(item, fields)
                self.game_enriched.emit(key, fields)
            elif err:
                logger.debug(f"补全失败 {key}: {err}")
                if self._mark_net_fail(err):
                    self._abort = True
                    self.failed.emit(f"网络连接异常（{err}），本轮联网补全中止")
                    return True
            self._done += 1
            self.progress_updated.emit(self._done, self._total)
        return False
