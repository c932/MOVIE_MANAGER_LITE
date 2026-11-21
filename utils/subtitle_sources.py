"""公开字幕站搜索和下载。遇到站方验证时把原始页面交还用户。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from email.message import Message
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from utils.subtitles import MAX_PACKAGE, SubtitleError, archive_subtitles, language_from_name

SOURCES = {
    'zimuku': ('字幕库', 'https://zimuku.org', r'/detail/(\d+)\.html'),
    'subhd': ('SubHD', 'https://subhdtw.com', r'/a/([A-Za-z0-9]{1,20})'),
    'assrt': ('伪射手网', 'https://assrt.net', r'/xml/sub/(\d+/\d+)\.xml'),
}
_SITE_HOSTS = {'zimuku.org', 'www.zimuku.org', 'subhdtw.com', 'assrt.net', 'www.assrt.net'}
_ASSRT_FILES = re.compile(r'file\d{1,2}\.assrt\.net')
_CHALLENGE = re.compile(r'YunsuoAutoJump|cf-chl-|g-recaptcha|id=["\']captcha|人[機机][驗验][證证]|验证码|驗證碼', re.I)


class SiteCheck(SubtitleError):
    pass


def _allowed(url: str) -> bool:
    value = urlsplit(url)
    host = value.hostname or ''
    if (value.username is not None or value.password is not None
            or value.netloc.casefold() != host):
        return False
    if host in _SITE_HOSTS:
        return value.scheme == 'https'
    # 伪射手官网的公开文件节点当前仍提供 HTTP 下载。
    return bool(_ASSRT_FILES.fullmatch(host) and value.scheme in {'https', 'http'}
                and value.path.startswith('/download/'))


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise SiteCheck('下载跳转需在原站浏览器中完成')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Session:
    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), _Redirect())

    def read(self, url: str, limit: int, *, referer: str = '', body: dict | None = None):
        if not _allowed(url):
            raise SiteCheck('此地址需要在原站浏览器中打开')
        headers = {'User-Agent': 'LocalMovieWall/3.7 (+subtitle search)',
                   'Accept': '*/*', 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7'}
        if referer and urlsplit(url).scheme == 'https':
            headers['Referer'] = referer
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                            'Origin': SOURCES['subhd'][1]})
        request = Request(url, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=10) as response:
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise SubtitleError('来源文件超过大小限制')
                return data, response.headers, response.geturl()
        except HTTPError as exc:
            with exc:
                blocked = exc.code in {401, 403, 429} or bool(_CHALLENGE.search(exc.read(8192).decode('utf-8', 'replace')))
            if blocked:
                raise SiteCheck('网站要求验证或限制当前连接，请在浏览器打开原站') from None
            raise SubtitleError(f'字幕站返回 HTTP {exc.code}') from None
        except (OSError, URLError) as exc:
            raise SubtitleError('暂时无法连接字幕站') from exc

    def page(self, url: str) -> str:
        data, headers, _ = self.read(url, 3 * 1024 * 1024)
        try:
            return data.decode(headers.get_content_charset() or 'utf-8', 'replace')
        except LookupError:
            return data.decode('utf-8', 'replace')


@dataclass(frozen=True)
class Candidate:
    source: str
    id: str
    title: str
    release: str
    language: str
    page: str
    score: int


class _Links(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[dict[str, str], str, int]] = []
        self.lines = [0]
        self.lines.extend(match.end() for match in re.finditer('\n', html))
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            row, column = self.getpos()
            self.current = (dict(attrs), [], self.lines[row - 1] + column)

    def handle_data(self, data):
        if self.current:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            attrs, parts, position = self.current
            self.links.append((attrs, ' '.join(''.join(parts).split()), position))
            self.current = None


def search_url(source: str, query: str) -> str:
    base = SOURCES[source][1]
    if source == 'assrt':
        return base + '/sub/?' + urlencode({'searchword': query})
    if source == 'zimuku':
        return base + '/search?' + urlencode({'q': query})
    return base + '/search/' + quote(query, safe='')


def candidate_url(source: str, identifier: str) -> str:
    if source not in SOURCES:
        raise SubtitleError('未知字幕源')
    _, base, pattern = SOURCES[source]
    path = re.sub(r'\([^)]*\)', lambda _: identifier, pattern).replace(r'\.', '.')
    if not re.fullmatch(pattern, path):
        raise SubtitleError('无效字幕候选')
    return base + path


def _words(value: str) -> list[str]:
    return re.findall(r'[^\W_]+', value.casefold())


def match_score(filename: str, release: str) -> int:
    target = _words(filename)
    candidate = _words(release)
    if not target or not candidate:
        return 0
    actual = ' '.join(target)
    other = ' '.join(candidate)
    if actual == other or f' {actual} ' in f' {other} ':
        return 100
    common = set(target) & set(candidate)
    score = round(90 * len(common) / len(set(target) | set(candidate)))
    versions = (r'\b(?:480|720|1080|1440|2160|4320)p\b', r'\b(?:blu\s?ray|web\s?dl|webrip|hdtv|bdrip|remux)\b',
                r'\b(?:19|20)\d{2}\b')
    for pattern in versions:
        left, right = re.search(pattern, actual), re.search(pattern, other)
        if left and right:
            score += 8 if left[0] == right[0] else -20
    return min(99, max(0, score))


def parse_candidates(source: str, html: str, filename: str) -> list[Candidate]:
    matches = []
    _, base, pattern = SOURCES[source]
    for attrs, text, offset in _Links(html).links:
        path = urljoin(base, attrs.get('href') or '')
        parsed = urlsplit(path)
        match = re.fullmatch(pattern, parsed.path)
        if not match or not text or parsed.hostname != urlsplit(base).hostname:
            continue
        if source == 'assrt' and 'introtitle' not in (attrs.get('class') or '').split():
            continue
        matches.append((match[1], attrs, text, offset))
    results = {}
    for index, (identifier, attrs, text, offset) in enumerate(matches):
        end = matches[index + 1][3] if index + 1 < len(matches) else len(html)
        block = html[offset:min(end, offset + 2600)]
        release = attrs.get('title') or text
        if source == 'assrt':
            version = re.search(r'版本：\s*<b>(.*?)</b>', block, re.S)
            if version:
                release = re.sub(r'<[^>]+>', '', version[1]).strip()
            language = re.search(r'语言：([^<]+)', block)
            raw = language[1].replace('简', ' 简体 ').replace('繁', ' 繁体 ').replace('英', ' English ') if language else ''
        else:
            raw = ' '.join(re.findall(r'>\s*(双语|雙語|简体|繁体|簡體|繁體|英语|英語|中文|English)\s*<', block))
            raw = raw.replace('英语', ' English ').replace('英語', ' English ')
        existing = results.get(identifier)
        if existing and len(existing.release) >= len(release):
            continue
        score = match_score(filename, release)
        results[identifier] = Candidate(source, identifier, existing.title if existing else text, release[:500],
                                        language_from_name(raw or release), candidate_url(source, identifier), score)
    return list(results.values())


def search_subtitles(query: str, filename: str, original_title: str = '') -> dict:
    def search(source: str) -> tuple[list[Candidate], dict]:
        url = search_url(source, query)
        status = {'source': source, 'name': SOURCES[source][0], 'url': url, 'message': ''}
        session = _Session()
        try:
            found = []
            for term in dict.fromkeys(filter(None, (query, original_title))):
                html = session.page(search_url(source, term))
                found = parse_candidates(source, html, filename)
                if found:
                    break
                if _CHALLENGE.search(html):
                    raise SiteCheck('网站需要验证，请打开原站完成操作')
            return sorted(found, key=lambda item: -item.score)[:50], status
        except SubtitleError as exc:
            status['message'] = str(exc)
            return [], status

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as executor:
        groups = list(executor.map(search, SOURCES))
    items = sorted((item for found, _ in groups for item in found), key=lambda item: -item.score)
    return {'items': [asdict(item) for item in items], 'sources': [status for _, status in groups]}


def _download_link(source: str, session: _Session, page: str, identifier: str) -> str:
    html = session.page(page)
    if source == 'subhd':
        data, _, _ = session.read(SOURCES['subhd'][1] + '/api/sub/prepare-download', 65536,
                                  referer=page, body={'sid': identifier})
        try:
            response = json.loads(data)
            if response.get('success') and str(response.get('url', '')).startswith('/down/'):
                return urljoin(page, response['url'])
        except (ValueError, AttributeError, TypeError):
            pass
    else:
        for attrs, _, _ in _Links(html).links:
            url = urljoin(page, attrs.get('href') or '')
            path = urlsplit(url).path
            if _allowed(url) and path.startswith('/download/'):
                if source == 'zimuku' or path.startswith('/download/' + identifier.split('/')[-1] + '/'):
                    return url
    raise SiteCheck('此字幕需要在原站完成验证或下载，请打开字幕原页')


def download_subtitles(source: str, identifier: str, hint: str = ''):
    page = candidate_url(source, identifier)
    session = _Session()
    url = _download_link(source, session, page, identifier)
    data, headers, actual = session.read(url, MAX_PACKAGE, referer=page)
    if headers.get_content_type() in {'text/html', 'application/json'}:
        raise SiteCheck('网站返回了验证或下载页面，请在浏览器中下载并导入')
    disposition = Message()
    if headers.get('Content-Disposition'):
        disposition['Content-Disposition'] = headers['Content-Disposition']
    filename = disposition.get_filename() or unquote(urlsplit(actual).path.rsplit('/', 1)[-1])
    return archive_subtitles(filename, data, hint)
