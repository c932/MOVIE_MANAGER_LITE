"""直接解析 IMDb 标题页；遇访问挑战时使用官方免费评分数据集。"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import math
import re
from typing import Any, Iterator
from urllib.parse import urlsplit

from .imdb_ratings import ImdbRatings
from .metadata_sources import ProviderError
from .scrape_http import HttpClient, HttpError
from .scrape_settings import ScrapeSettings


_MAX_HTML_BYTES = 8 * 1024 * 1024
_TITLE_TYPES = {'Movie', 'TVSeries', 'TVEpisode', 'TVMiniSeries', 'VideoObject'}


class _AccessError(ProviderError):
    """IMDb 明确阻止页面访问，可以退回官方数据集。"""


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[str, str]] = []
        self.canonicals: list[str] = []
        self.visible: list[str] = []
        self.challenge = False
        self._script: tuple[str, list[str]] | None = None
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == 'link' and 'canonical' in (values.get('rel') or '').lower().split():
            self.canonicals.append(values.get('href') or '')
        if tag == 'script':
            self._in_script = True
            src = (values.get('src') or '').lower()
            if any(marker in src for marker in ('awswaf', '/challenge.js', '/captcha/')):
                self.challenge = True
            kind = ('next' if values.get('id') == '__NEXT_DATA__' else
                    'ld' if (values.get('type') or '').lower().split(';')[0].strip() == 'application/ld+json' else '')
            self._script = (kind, []) if kind else None

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script[1].append(data)
        elif not self._in_script:
            self.visible.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script':
            if self._script is not None:
                self.scripts.append((self._script[0], ''.join(self._script[1])))
            self._script = None
            self._in_script = False


def _url_id(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.netloc and (parsed.hostname not in {'www.imdb.com', 'imdb.com', 'm.imdb.com'}
                              or parsed.username or parsed.password or parsed.port):
            return ''
        if parsed.scheme and parsed.scheme not in {'https', 'http'}:
            return ''
        match = re.fullmatch(r'/title/(tt[0-9]+)/?', parsed.path)
        return match.group(1) if match else ''
    except ValueError:
        return ''


def _ld_titles(data: Any) -> Iterator[dict]:
    """只遍历根数组和 @graph；不向推荐、评论等任意嵌套对象搜索评分。"""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            kinds = node.get('@type', [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if isinstance(kinds, list) and any(isinstance(kind, str) and kind in _TITLE_TYPES for kind in kinds):
                yield node
            graph = node.get('@graph')
            if isinstance(graph, (dict, list)):
                stack.append(graph)


def _pair(score: Any, count: Any, best: Any = 10) -> tuple[float | None, int | None]:
    try:
        if isinstance(score, bool) or isinstance(count, bool) or isinstance(best, bool):
            return None, None
        number = float(score)
        if not math.isfinite(number) or not 0 < number <= 10 or float(best) != 10:
            return None, None
        text = str(count)
        if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', text):
            return None, None
        votes = int(text.replace(',', ''))
        return (number, votes) if votes > 0 else (None, None)
    except (ValueError, TypeError, OverflowError):
        return None, None


def _parse_page(content: bytes, identity: str) -> tuple[float | None, int | None]:
    page = _Page()
    try:
        page.feed(content.decode('utf-8-sig'))
        page.close()
    except (UnicodeError, ValueError, RecursionError):
        raise ProviderError('IMDb 页面编码或 HTML 格式无效') from None
    text = ' '.join(page.visible).lower()
    if page.challenge or any(marker in text for marker in (
            'verify you are human', 'robot check', 'just a moment', 'pardon our interruption',
            'please enable javascript', 'enable javascript and cookies')):
        raise _AccessError('IMDb 网页访问受限或需要人机验证')
    if any(_url_id(url) != identity for url in page.canonicals):
        raise ProviderError('IMDb 页面身份与请求的 tt ID 不一致')
    identified = False
    candidates: list[tuple[float | None, int | None]] = []
    for kind, raw in page.scripts:
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if kind == 'ld':
            for node in _ld_titles(data):
                ids = [_url_id(node[key]) for key in ('url', '@id') if node.get(key) is not None]
                if not ids or any(value != identity for value in ids):
                    continue
                identified = True
                aggregate = node.get('aggregateRating')
                if isinstance(aggregate, dict):
                    candidates.append(_pair(aggregate.get('ratingValue'), aggregate.get('ratingCount'),
                                            aggregate.get('bestRating', 10)))
        elif kind == 'next' and isinstance(data, dict):
            props = data.get('props')
            page_props = props.get('pageProps') if isinstance(props, dict) else None
            if not isinstance(page_props, dict):
                continue
            for key in ('aboveTheFoldData', 'mainColumnData'):
                node = page_props.get(key)
                if not isinstance(node, dict):
                    continue
                if node.get('id') is not None and node['id'] != identity:
                    raise ProviderError('IMDb 页面返回了不同的 tt ID')
                if node.get('id') != identity:
                    continue
                identified = True
                summary = node.get('ratingsSummary')
                if isinstance(summary, dict):
                    candidates.append(_pair(summary.get('aggregateRating'), summary.get('voteCount')))
    if not identified:
        raise ProviderError('IMDb 页面缺少可核验的目标 tt ID 或页面格式已变化')
    return next((pair for pair in candidates if pair[0] is not None), (None, None))


class ImdbProvider:
    def __init__(self, settings: ScrapeSettings) -> None:
        self.settings = settings
        self.http = HttpClient(settings)

    def rating(self, imdb_id: str) -> tuple[float | None, int | None]:
        if not isinstance(imdb_id, str) or not re.fullmatch(r'tt[0-9]+', imdb_id):
            raise ProviderError('IMDb ID 格式无效')
        try:
            try:
                content = self.http.get_bytes(f'https://www.imdb.com/title/{imdb_id}/', max_bytes=_MAX_HTML_BYTES)
            except HttpError as exc:
                if exc.status in {202, 403}:
                    raise _AccessError(f'IMDb 网页访问受限（HTTP {exc.status}）') from None
                if exc.status is None:
                    raise _AccessError(f'IMDb 网页获取失败：{exc}') from None
                raise ProviderError(f'IMDb：{exc}') from None
            return _parse_page(content, imdb_id)
        except _AccessError as exc:
            try:
                return ImdbRatings(self.settings).rating(imdb_id)
            except ProviderError as fallback:
                raise ProviderError(f'{exc}；{fallback}') from None
