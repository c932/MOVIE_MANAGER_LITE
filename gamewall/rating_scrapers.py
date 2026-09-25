"""
第三方评分刮削（尽力而为：任何失败静默返回 None，评分留空）

实测约束（2026-09，用户网络）：
- 游民星空 so.gamersky.com 搜索可用，但专题页评分由 JS 从 dbapi.gamersky.com
  异步加载，该域名 DNS 不通且静态 HTML 中评分恒为 0 → 仅当静态含非零评分才有结果
- IGN 主站被墙不可达 → IgnScraper 默认关闭（config.enable_ign_scraper=false）

负结果由 EnrichmentWorker 记入 scraper_neg（7 天内跳过重试）；
每个刮削器内部独立熔断：连续 20 次网络层失败后本轮直接返回 None 不再发请求
（搜索无结果属正常负结果，不计入熔断）。
"""
import gzip
import logging
import re
import urllib.parse
import urllib.request

from gamewall import steam_client
from gamewall.steam_client import SteamCancelled

logger = logging.getLogger(__name__)

_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BREAKER_THRESHOLD = 20

# 游民星空专题页评分控件（静态值 > 0 才有效，JS 异步填充的页面初始为 0）
_GS_SCORE_RE = re.compile(r'scoreAvg"[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*<')
_GS_ZONE_RE = re.compile(r'href="(https?://(?:www\.)?gamersky\.com/z/[^"\'<>]+)"')
# IGN 评分（尽力而为，仅覆盖 data-score 标记格式）
_IGN_SCORE_RE = re.compile(r'data-score="([0-9]+(?:\.[0-9]+)?)"')


def _http_get_text(url: str, timeout: float = 8):
    """GET HTML 文本（复用全局限速与取消检查），返回 (text, err)"""
    steam_client._raise_if_cancelled()
    steam_client._rate_limiter.wait()
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA_BROWSER, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if "gzip" in (resp.headers.get("Content-Encoding") or ""):
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace"), None
    except SteamCancelled:
        raise
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


class _CircuitBreaker:
    """连续网络层失败熔断（阈值 20）"""

    def __init__(self, threshold: int = BREAKER_THRESHOLD):
        self._threshold = threshold
        self._consecutive = 0
        self._open = False

    def record(self, network_ok: bool):
        if network_ok:
            self._consecutive = 0
            return
        self._consecutive += 1
        if self._consecutive >= self._threshold:
            self._open = True
            logger.warning("刮削器连续失败 %d 次，本轮熔断", self._consecutive)

    @property
    def open(self) -> bool:
        return self._open


class GamerskyScraper:
    """游民星空：so 搜索 → 游戏专题页 → 解析静态评分（0-10）"""

    def __init__(self):
        self._breaker = _CircuitBreaker()

    def fetch_score(self, title: str):
        """返回 (score|None, err)；用中文名搜索"""
        if not title or self._breaker.open:
            return None, ""
        try:
            return self._fetch(title)
        except SteamCancelled:
            raise
        except Exception as e:
            self._breaker.record(False)
            logger.debug("游民星空刮削异常 %s: %s", title, e)
            return None, str(e)

    def _fetch(self, title: str):
        search_url = "https://so.gamersky.com/?s=" + urllib.parse.quote(title)
        text, err = _http_get_text(search_url)
        if err:
            self._breaker.record(False)
            return None, err
        m = _GS_ZONE_RE.search(text)
        if not m:
            self._breaker.record(True)   # 正常响应但无游戏专题 → 负结果
            return None, ""
        zone_html, err2 = _http_get_text(m.group(1))
        if err2:
            self._breaker.record(False)
            return None, err2
        self._breaker.record(True)
        sm = _GS_SCORE_RE.search(zone_html)
        if not sm:
            return None, ""
        score = float(sm.group(1))
        return (score, "") if 0 < score <= 10 else (None, "")


class IgnScraper:
    """IGN：搜索页 → 评测页 → 解析评分（0-10；被墙环境下全部失败留空）"""

    def __init__(self):
        self._breaker = _CircuitBreaker()
        self._link_re = re.compile(
            r'href="(https?://(?:www\.)?ign\.com/(?:articles|reviews|wikis)/[^"\'<>]+)"')

    def fetch_score(self, title: str):
        if not title or self._breaker.open:
            return None, ""
        try:
            return self._fetch(title)
        except SteamCancelled:
            raise
        except Exception as e:
            self._breaker.record(False)
            logger.debug("IGN 刮削异常 %s: %s", title, e)
            return None, str(e)

    def _fetch(self, title: str):
        search_url = "https://www.ign.com/search?q=" + urllib.parse.quote(title)
        text, err = _http_get_text(search_url, timeout=12)
        if err:
            self._breaker.record(False)
            return None, err
        m = self._link_re.search(text)
        if not m:
            self._breaker.record(True)
            return None, ""
        page, err2 = _http_get_text(m.group(1), timeout=12)
        if err2:
            self._breaker.record(False)
            return None, err2
        self._breaker.record(True)
        sm = _IGN_SCORE_RE.search(page)
        if not sm:
            return None, ""
        score = float(sm.group(1))
        return (score, "") if 0 < score <= 10 else (None, "")
