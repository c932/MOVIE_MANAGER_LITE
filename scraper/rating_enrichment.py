"""人工确认后按明确站点 ID 补齐评分，不修改候选的片名、简介和海报。"""
from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import re

from .metadata_sources import OmdbProvider, ProviderError, TmdbProvider, _imdb_id
from .scrape_http import HttpClient
from .scrape_models import Metadata, ScrapeError
from .scrape_settings import ScrapeSettings


class _DoubanInfo(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.text: list[str] = []
        self.identities: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.depth or attrs.get('id') == 'info':
                self.depth += 1
        if tag == 'link' and 'canonical' in (attrs.get('rel') or '').split():
            self.identities.append(attrs.get('href') or '')
        elif tag == 'meta' and attrs.get('property') == 'og:url':
            self.identities.append(attrs.get('content') or '')

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.text.append(data)


def douban_imdb_id(subject_id: str, settings: ScrapeSettings) -> str:
    if not re.fullmatch(r'\d+', subject_id):
        raise ProviderError('豆瓣条目 ID 无效')
    payload = HttpClient(settings).get_bytes(f'https://movie.douban.com/subject/{subject_id}/',
        max_bytes=2 * 1024 * 1024, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-CN,zh;q=0.9'})
    parser = _DoubanInfo()
    parser.feed(payload.decode('utf-8'))
    if not parser.identities:
        raise ProviderError('豆瓣页面未提供可核验的条目身份，不能关联 IMDb')
    expected = f'https://movie.douban.com/subject/{subject_id}'
    if any(url.rstrip('/') != expected for url in parser.identities):
        raise ProviderError('豆瓣页面返回了不同条目，身份关联已停止')
    match = re.search(r'IMDb\s*[:：]\s*(tt\d+)\b', ' '.join(parser.text), re.IGNORECASE)
    return match.group(1).lower() if match else ''


def enrich_ratings(metadata: Metadata, settings: ScrapeSettings) -> Metadata:
    result = deepcopy(metadata)
    imdb = _imdb_id(result.ids.get('imdb', ''))
    if not imdb and result.source == 'douban':
        try:
            imdb = douban_imdb_id(result.id, settings)
        except (ScrapeError, OSError, ValueError) as exc:
            result.warnings.append('跨站评分关联未完成：' + str(exc))
    if not imdb:
        result.warnings.append('缺少可核验的 IMDb ID，未猜测跨站电影；可手动选择并确认 TMDB 候选补充评分')
        return result
    result.ids['imdb'] = imdb
    if 'tmdb' not in result.ratings:
        if settings.tmdb_api_key or settings.tmdb_token:
            try:
                identity, score, votes = TmdbProvider(settings).rating_by_imdb(imdb)
                if result.ids.get('tmdb') and result.ids['tmdb'] != identity:
                    raise ProviderError('TMDB 关联 ID 冲突')
                result.ids['tmdb'] = identity
                if score is not None:
                    result.ratings['tmdb'] = score
                    if votes:
                        result.votes['tmdb'] = votes
                else:
                    result.warnings.append('TMDB 条目暂无有效评分')
            except (ScrapeError, OSError, ValueError) as exc:
                result.warnings.append('TMDB 评分未取得：' + str(exc))
        else:
            result.warnings.append('TMDB 评分未取得：请配置 TMDB API Key 或 Token')
    if 'imdb' not in result.ratings:
        score, votes = None, None
        if settings.omdb_api_key:
            try:
                score, votes = OmdbProvider(settings).rating(imdb)
            except (ScrapeError, OSError, ValueError):
                pass  # 可选 OMDb 不可用时仍尝试无需 Key 的 IMDb 来源。
        if score is None:
            from .imdb_provider import ImdbProvider
            try:
                score, votes = ImdbProvider(settings).rating(imdb)
            except (ScrapeError, OSError, ValueError) as exc:
                result.warnings.append('IMDb 评分未取得：' + str(exc))
        if score is not None:
            result.ratings['imdb'] = score
            if votes:
                result.votes['imdb'] = votes
        elif not any(w.startswith('IMDb 评分未取得') for w in result.warnings):
            result.warnings.append('IMDb 条目暂无有效评分')
    return result
