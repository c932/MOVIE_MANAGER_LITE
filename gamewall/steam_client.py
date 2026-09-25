"""
Steam 商店数据客户端（免费公开接口，无需 API Key）

可用接口（2026-09 实测）：
- storesearch:  store.steampowered.com/api/storesearch/?term=X&cc=CN&l=schinese（中文名+Metascore）
- appdetails:   store.steampowered.com/api/appdetails?appids=X&l=schinese（简介/发售日/类型/头图/Metacritic）
- appreviews:   store.steampowered.com/appreviews/X?json=1（好评率）
- SearchApps:   steamcommunity.com/actions/SearchApps/X（英文名搜索）

注：ISteamApps/GetAppList 全量列表接口已被 Steam 下线（404），
    故采用逐条搜索匹配，匹配结果由 game_cache.json 持久化以支持增量续跑。
"""
import difflib
import gzip
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from gamewall.name_utils import normalize_name

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalGameWall/1.0"
REQUEST_INTERVAL = 0.2   # 全局请求间隔，约 5 req/s（429 时自动退避）
BACKOFF_SECONDS = 30     # 429/5xx 退避时长
MAX_RETRY = 3
HTTP_TIMEOUT = 8
MATCH_MIN_RATIO = 0.6    # 搜索结果相似度下限（防短名误匹配）

# schinese 发售日「2022 年 2 月 24 日」→ ISO
_RELEASE_CN_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')


class SteamCancelled(Exception):
    """用户取消补全"""


class _RateLimiter:
    """跨线程全局限速器"""

    def __init__(self, interval: float):
        self._interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delay = self._last + self._interval - now
            self._last = max(now, self._last + self._interval)
        if delay > 0:
            _sleep(delay)


_rate_limiter = _RateLimiter(REQUEST_INTERVAL)
_cancel_check = None


def set_cancel_check(fn):
    """注册取消检查回调（由 EnrichmentWorker 注入），sleep/请求前抛 SteamCancelled"""
    global _cancel_check
    _cancel_check = fn


def _raise_if_cancelled():
    if _cancel_check and _cancel_check():
        raise SteamCancelled()


def _sleep(seconds: float):
    deadline = time.monotonic() + seconds
    while True:
        _raise_if_cancelled()
        remain = deadline - time.monotonic()
        if remain <= 0:
            return
        time.sleep(min(0.25, remain))


def _http_get_json(url: str, timeout: float = HTTP_TIMEOUT,
                   max_retry: int = MAX_RETRY, backoff: float = BACKOFF_SECONDS):
    """
    GET 并解析 JSON。返回 (data, None) 或 (None, err_str)。
    err_str 以 "HTTP " 开头为 HTTP 状态错误，否则为网络层错误（用于熔断判断）。
    """
    last_err = ""
    for attempt in range(max_retry):
        _raise_if_cancelled()
        _rate_limiter.wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if "gzip" in (resp.headers.get("Content-Encoding") or ""):
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace")), None
        except SteamCancelled:
            raise
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retry - 1:
                logger.warning(f"Steam 请求被限流/服务异常({e.code})，{backoff:.0f}s 后重试")
                _sleep(backoff)
                continue
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            break
    return None, last_err


# ── 搜索匹配 ──

# Steam 改名/搜索接口盲区的知名游戏：归一化名 → appid（精确维护，不做模糊猜测）
_STEAM_APP_ALIASES = {
    "hitman3": 1659040,   # HITMAN 3 已改名 HITMAN World of Assassination，storesearch 搜不到本体
    "杀手3": 1659040,
}


def lookup_steam_alias(queries) -> int:
    """按归一化名查询内置别名表；命中返回 appid，否则 0。只允许别名键是查询名的子串。"""
    for query in queries:
        nq = normalize_name(query or "")
        if not nq:
            continue
        for key, appid in _STEAM_APP_ALIASES.items():
            if nq == key or key in nq:
                return appid
    return 0


def _pick_best(items, queries) -> tuple:
    """在搜索结果 top10 中挑选相似度最高且达标的条目，返回 (appid, steam_name)"""
    nqs = []
    for q in queries:
        nq = normalize_name(q)
        if nq and nq not in nqs:
            nqs.append(nq)
    best_appid, best_name, best_score = 0, "", 0.0
    for it in items[:10]:
        try:
            appid = int(it.get("id") or it.get("appid") or 0)
        except (TypeError, ValueError):
            continue
        name = it.get("name", "")
        nname = normalize_name(name)
        if not appid or not nname:
            continue
        for nq in nqs:
            ratio = min(len(nq), len(nname)) / max(len(nq), len(nname))
            if nq == nname:
                score = 1.0
            elif (nq in nname or nname in nq) and ratio >= MATCH_MIN_RATIO:
                score = 0.8 + 0.2 * ratio
            else:
                if ratio < MATCH_MIN_RATIO:
                    continue
                score = difflib.SequenceMatcher(None, nq, nname).ratio()
            if score > best_score and score >= MATCH_MIN_RATIO:
                best_appid, best_name, best_score = appid, name, score
    return best_appid, best_name


def _search_store(term: str) -> tuple:
    url = ("https://store.steampowered.com/api/storesearch/?term="
           + urllib.parse.quote(term) + "&cc=CN&l=schinese")
    data, err = _http_get_json(url)
    if err or not isinstance(data, dict):
        return [], err
    return data.get("items") or [], ""


def _search_community(term: str) -> tuple:
    url = "https://steamcommunity.com/actions/SearchApps/" + urllib.parse.quote(term)
    data, err = _http_get_json(url)
    return (data if isinstance(data, list) else []), err


def match_appid(queries) -> tuple:
    """
    逐条搜索匹配 appid，返回 (appid, steam_name, definitive)。
    - 别名命中或任一搜索 HTTP 层成功：definitive=True
    - 未匹配且所有搜索都网络失败：返回 (0, "", False)，不可据此记负缓存
    先查内置改名别名表，再尝试：storesearch(中文名) → SearchApps(英文名)
    → storesearch(英文名) → SearchApps(中文名)
    """
    alias = lookup_steam_alias(queries)
    if alias:
        return alias, "", True
    cn = (queries[0] or "").strip() if queries else ""
    en = (queries[1] or "").strip() if len(queries) > 1 else ""
    attempts = [(cn, _search_store), (en, _search_community),
                (en, _search_store), (cn, _search_community)]
    reached_server = False
    for term, fn in attempts:
        if not term:
            continue
        _raise_if_cancelled()
        items, err = fn(term)
        if not err:
            reached_server = True
        if items:
            appid, name = _pick_best(items, queries)
            if appid:
                return appid, name, True
    return 0, "", reached_server


# ── 详情与评价 ──

def _normalize_release_date(text: str) -> str:
    if not text:
        return ""
    m = _RELEASE_CN_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text.strip()


def fetch_appdetails(appid: int) -> tuple:
    """
    获取商店详情。返回 (fields, err)：
    - (fields_dict, "")：成功或确认无商店页（fields 可能为空 dict）
    - (None, err)：请求失败
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese"
    data, err = _http_get_json(url, timeout=12)
    if err:
        return None, err
    info = (data or {}).get(str(appid)) or {}
    if not info.get("success"):
        return {}, ""   # 商店无此应用页（下架/地区锁等），非错误
    d = info.get("data") or {}
    fields = {}
    if d.get("name"):
        fields["steam_name"] = d["name"]
    if d.get("short_description"):
        fields["description"] = d["short_description"][:2000]
    if d.get("header_image"):
        fields["header_image"] = d["header_image"]
    devs = [str(x).strip() for x in d.get("developers") or [] if str(x).strip()]
    if devs:
        fields["developer"] = "、".join(devs[:2])
    publishers = [str(x).strip() for x in d.get("publishers") or [] if str(x).strip()]
    if publishers:
        fields["publishers"] = publishers
    platform_data = d.get("platforms") or {}
    if isinstance(platform_data, dict):
        platforms = [str(name).strip() for name, supported in platform_data.items()
                     if supported and str(name).strip()]
        if platforms:
            fields["platforms"] = platforms
    categories = [str(category.get("description", "")).strip()
                  for category in d.get("categories") or []
                  if isinstance(category, dict) and category.get("description")]
    if categories:
        fields["steam_categories"] = categories
    genres = [g.get("description", "") for g in d.get("genres") or [] if g.get("description")]
    if genres:
        fields["genres"] = genres
    rd = d.get("release_date") or {}
    date_text = (rd.get("date") or "").strip()
    if date_text:
        fields["release_date"] = _normalize_release_date(date_text)
    mc = d.get("metacritic") or {}
    if mc.get("score"):
        fields["metacritic"] = float(mc["score"])
    return fields, ""


def fetch_appreviews(appid: int) -> tuple:
    """获取好评率。返回 (fields, err)，fields 为空 dict 表示 0 条评价。"""
    url = (f"https://store.steampowered.com/appreviews/{appid}"
           "?json=1&num_per_page=0&language=all&purchase_type=all")
    data, err = _http_get_json(url)
    if err:
        return None, err
    qs = (data or {}).get("query_summary") or {}
    total = int(qs.get("total_reviews") or 0)
    positive = int(qs.get("total_positive") or 0)
    if total <= 0:
        return {}, ""   # 0 条评价，视为暂无数据
    pct = round(positive * 100.0 / total, 1)
    return {"steam_positive_pct": pct, "steam_review_total": total}, ""
