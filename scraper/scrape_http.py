"""urllib 有界传输。绝不在用户可见异常中回显 URL、响应正文或凭据。"""
from __future__ import annotations

import http.client
import json
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from .scrape_models import ScrapeError
from .scrape_settings import ScrapeSettings


class HttpError(ScrapeError):
    """脱敏传输错误；status 可供提供者分类，错误正文不透传。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise HttpError('请求重定向到不安全的地址')
        redirect = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirect is not None and urllib.parse.urlsplit(req.full_url).netloc != parsed.netloc:
            redirect.remove_header('Authorization')
        return redirect


class HttpClient:
    def __init__(self, settings: ScrapeSettings | None = None, retries: int = 2) -> None:
        self.settings = settings or ScrapeSettings()
        self.settings.validate()
        self.retries = min(3, max(0, int(retries)))
        proxy = self.settings.proxy
        proxies = {'http': proxy, 'https': proxy} if proxy else {}
        # 空配置明确直连，不继承系统代理及其可能的认证信息。
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), _HttpsRedirect())

    def get_bytes(self, url: str, max_bytes: int = 15 * 1024 * 1024,
                  *, headers: Mapping[str, str] | None = None) -> bytes:
        try:
            parsed = urllib.parse.urlsplit(url)
            valid = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise HttpError('请求地址必须是有效的 HTTPS 地址')
        if max_bytes <= 0:
            raise HttpError('下载大小上限必须大于零')
        request = urllib.request.Request(url, headers={'User-Agent': 'MovieManagerLite/1.0', **(headers or {})})
        for attempt in range(self.retries + 1):
            try:
                with self._opener.open(request, timeout=self.settings.timeout) as response:
                    status = response.status
                    if status != 200:
                        raise HttpError(f'服务器响应异常（HTTP {status}）', status)
                    declared = response.headers.get('Content-Length')
                    if declared is not None:
                        try:
                            length = int(declared)
                        except ValueError:
                            raise HttpError('服务器响应长度格式异常') from None
                        if length < 0 or length > max_bytes:
                            raise HttpError('下载内容超出大小上限')
                    data = response.read(max_bytes + 1)
                    if not data:
                        raise HttpError('服务器返回空内容，未取得有效数据', status)
                    if len(data) > max_bytes:
                        raise HttpError('下载内容超出大小上限')
                    if declared is not None and len(data) != length:
                        raise HttpError('服务器响应不完整，请重试')
                    return data
            except urllib.error.HTTPError as exc:
                status = exc.code
                exc.close()
                retryable = status in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt == self.retries:
                    message = ('认证失败，请检查数据源凭据' if status in {401, 403} else
                               '请求受限，请稍后重试' if status == 429 else '服务器请求失败')
                    raise HttpError(f'{message}（HTTP {status}）', status) from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if attempt == self.retries:
                    raise HttpError('网络请求失败或超时，请检查网络与代理设置') from None
            time.sleep(min(0.1 * (2 ** attempt), 0.4))
        raise HttpError('网络请求失败')  # pragma: no cover

    def get_json(self, url: str, params: Mapping[str, Any] | None = None,
                 *, headers: Mapping[str, str] | None = None,
                 max_bytes: int = 2 * 1024 * 1024) -> dict | list:
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        data = self.get_bytes(url, max_bytes=max_bytes, headers=headers)
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise HttpError('服务器响应格式异常，未取得有效 JSON 数据') from None
        if not isinstance(result, (dict, list)):
            raise HttpError('服务器响应格式异常，应为 JSON 对象或数组')
        return result
