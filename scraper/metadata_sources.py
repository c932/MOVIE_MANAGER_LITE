"""电影元数据提供者：保持来源身份、评分与人工候选边界。"""
from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from utils.countries import localize_country

from .scrape_http import HttpClient, HttpError
from .scrape_models import Artwork, Candidate, Metadata, ScrapeError
from .scrape_settings import ScrapeSettings


class ProviderError(ScrapeError):
    """可显示给用户的数据源错误，不携带原始响应或凭据。"""


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def _score(value: Any) -> float | None:
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) and 0 <= number <= 10 else None
    except (ValueError, TypeError):
        return None


def _votes(value: Any) -> int | None:
    text = _text(value).replace(',', '')
    return int(text) if re.fullmatch(r'\d+', text) else None


def _page(page: int) -> int:
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 500:
        raise ProviderError('搜索页码应为 1–500')
    return page


def _numeric_id(query: str, source: str) -> str:
    if re.fullmatch(r'\d+', query):
        return query
    try:
        parsed = urlsplit(query)
    except ValueError:
        raise ProviderError('电影链接格式无效') from None
    hosts = {'tmdb': {'themoviedb.org', 'www.themoviedb.org'},
             'douban': {'movie.douban.com', 'www.douban.com', 'douban.com', 'm.douban.com'}}
    if parsed.hostname in hosts[source]:
        pattern = r'/movie/(\d+)(?:[-/]|$)' if source == 'tmdb' else r'/(?:movie/)?subject/(\d+)(?:/|$)'
        match = re.search(pattern, parsed.path)
        if match:
            return match.group(1)
    return ''


def _imdb_id(query: str) -> str:
    if re.fullmatch(r'tt\d+', query):
        return query
    try:
        parsed = urlsplit(query)
    except ValueError:
        raise ProviderError('IMDb 链接格式无效') from None
    if parsed.hostname in {'imdb.com', 'www.imdb.com', 'm.imdb.com'}:
        match = re.fullmatch(r'/title/(tt\d+)/?', parsed.path)
        if match:
            return match.group(1)
    return ''


def _items(data: dict, key: str, source: str, *, required: bool = False) -> list[dict]:
    value = data.get(key, None if required else [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ProviderError(f'{source} 响应格式异常：{key}')
    return value


def _image(path: Any, size: str = 'original') -> str:
    text = _text(path)
    return f'https://image.tmdb.org/t/p/{size}{text}' if text.startswith('/') else ''


class TmdbProvider:
    def __init__(self, settings: ScrapeSettings) -> None:
        self.settings = settings
        self.http = HttpClient(settings)

    def _get(self, path: str, **params: Any) -> dict:
        if not (self.settings.tmdb_api_key or self.settings.tmdb_token):
            raise ProviderError('未配置 TMDB API Key 或访问令牌')
        headers = {}
        params = {'language': self.settings.language, **params}
        if self.settings.tmdb_token:
            headers['Authorization'] = f'Bearer {self.settings.tmdb_token}'
        else:
            params['api_key'] = self.settings.tmdb_api_key
        try:
            data = self.http.get_json(f'https://api.themoviedb.org/3/{path}', params, headers=headers)
        except HttpError as exc:
            raise ProviderError(f'TMDB：{exc}') from None
        if not isinstance(data, dict):
            raise ProviderError('TMDB 响应格式异常')
        if data.get('success') is False:
            raise ProviderError('TMDB 请求被拒绝，请检查凭据、权限或条目 ID')
        return data

    @staticmethod
    def _candidate(item: dict) -> Candidate:
        identity, title = _text(item.get('id')), _text(item.get('title'))
        if not re.fullmatch(r'\d+', identity) or not title:
            raise ProviderError('TMDB 电影条目格式异常，缺少有效 ID 或片名')
        return Candidate('tmdb', identity, title, _text(item.get('original_title')),
                         _text(item.get('release_date'))[:4], _text(item.get('overview')),
                         _image(item.get('poster_path')))

    def search(self, query: str, year: str = '', page: int = 1) -> list[Candidate]:
        page = _page(page)
        query = query.strip()
        if not query:
            raise ProviderError('请输入电影名称或 ID')
        identity = _numeric_id(query, 'tmdb')
        if identity:
            return [self._candidate(self._get(f'movie/{identity}'))]
        imdb = _imdb_id(query)
        if imdb:
            data = self._get(f'find/{imdb}', external_source='imdb_id')
            return [self._candidate(item) for item in _items(data, 'movie_results', 'TMDB', required=True)]
        if '://' in query:
            raise ProviderError('无法识别的 TMDB 或 IMDb 电影链接')
        params: dict[str, Any] = {'query': query, 'page': page, 'include_adult': 'false'}
        if year:
            params['year'] = year
        data = self._get('search/movie', **params)
        return [self._candidate(item) for item in _items(data, 'results', 'TMDB', required=True)]

    def details(self, candidate: Candidate) -> Metadata:
        if candidate.source != 'tmdb' or not re.fullmatch(r'\d+', candidate.id) or candidate.media_type != 'movie':
            raise ProviderError('请选择有效的 TMDB 电影候选')
        identity = candidate.id
        data = self._get(f'movie/{identity}')
        if self._candidate(data).id != identity:
            raise ProviderError('TMDB 返回了不同的电影 ID')
        external = self._get(f'movie/{identity}/external_ids')
        if 'imdb_id' not in external:
            raise ProviderError('TMDB 外部 ID 响应格式变化')
        credits = self._get(f'movie/{identity}/credits')
        images = self._get(f'movie/{identity}/images', include_image_language='zh,null,en')
        cast = _items(credits, 'cast', 'TMDB', required=True)
        crew = _items(credits, 'crew', 'TMDB', required=True)
        posters = _items(images, 'posters', 'TMDB', required=True)
        fields: dict[str, Any] = {
            'title': _text(data.get('title')), 'original_title': _text(data.get('original_title')),
            'year': _text(data.get('release_date'))[:4], 'premiered': _text(data.get('release_date')),
            'plot': _text(data.get('overview')), 'tagline': _text(data.get('tagline')),
            'runtime': _text(data.get('runtime')),
            'genres': [_text(item.get('name')) for item in _items(data, 'genres', 'TMDB')],
            'countries': [localize_country(_text(item.get('name')), _text(item.get('iso_3166_1')))
                          for item in _items(data, 'production_countries', 'TMDB')],
            'directors': [_text(item.get('name')) for item in crew if item.get('job') == 'Director'],
            'actors': [{'name': _text(item.get('name')), 'role': _text(item.get('character')),
                        'thumb': _image(item.get('profile_path'), 'w185')}
                       for item in cast],
        }
        collection = data.get('belongs_to_collection')
        if isinstance(collection, dict):
            fields['set_name'] = _text(collection.get('name'))
        result = Metadata('tmdb', identity, fields=fields, ids={'tmdb': identity})
        imdb = _imdb_id(_text(external.get('imdb_id')) or _text(data.get('imdb_id')))
        if imdb:
            result.ids['imdb'] = imdb
        score, votes = _score(data.get('vote_average')), _votes(data.get('vote_count'))
        if score is not None and votes is not None and votes > 0:
            result.ratings['tmdb'] = score
            result.votes['tmdb'] = votes
        for item in posters:
            url = _image(item.get('file_path'))
            if url:
                result.artwork.append(Artwork(url, _image(item.get('file_path'), 'w342'),
                    language=_text(item.get('iso_639_1')), width=_votes(item.get('width')) or 0,
                    height=_votes(item.get('height')) or 0, source='tmdb'))
        if not result.artwork and _image(data.get('poster_path')):
            result.artwork.append(Artwork(_image(data['poster_path']), source='tmdb'))
        result.artwork.sort(key=lambda a: ({'zh': 0, 'zh-CN': 0, '': 1, 'en': 2}.get(a.language, 3), -a.width * a.height))
        if not fields['plot']:
            result.warnings.append('TMDB 未提供所选语言的简介')
        return result

    def rating_by_imdb(self, imdb_id: str) -> tuple[str, float | None, int | None]:
        identity = _imdb_id(imdb_id)
        if not identity:
            raise ProviderError('IMDb ID 格式无效')
        results = _items(self._get(f'find/{identity}', external_source='imdb_id'), 'movie_results', 'TMDB', required=True)
        matches = {_text(item.get('id')) for item in results if re.fullmatch(r'\d+', _text(item.get('id')))}
        if len(matches) != 1:
            raise ProviderError('TMDB 未找到唯一的 IMDb 电影关联')
        tmdb_id = matches.pop()
        movie = self._get(f'movie/{tmdb_id}')
        if _text(movie.get('id')) != tmdb_id or _imdb_id(_text(movie.get('imdb_id'))) != identity:
            raise ProviderError('TMDB 返回不同的电影，IMDb 关联冲突')
        score, votes = _score(movie.get('vote_average')), _votes(movie.get('vote_count'))
        return tmdb_id, score if votes and votes > 0 else None, votes


class OmdbProvider:
    def __init__(self, settings: ScrapeSettings) -> None:
        self.settings = settings
        self.http = HttpClient(settings)

    def rating(self, imdb_id: str) -> tuple[float | None, int | None]:
        if not self.settings.omdb_api_key:
            raise ProviderError('未配置 OMDb API Key，无法获取 IMDb 评分')
        identity = _imdb_id(imdb_id)
        if not identity:
            raise ProviderError('IMDb ID 格式无效')
        try:
            data = self.http.get_json('https://www.omdbapi.com/', {'apikey': self.settings.omdb_api_key, 'i': identity})
        except HttpError as exc:
            raise ProviderError(f'OMDb：{exc}') from None
        if not isinstance(data, dict) or data.get('Response') not in {'True', 'False'}:
            raise ProviderError('OMDb 响应格式异常')
        if data['Response'] == 'False':
            raise ProviderError('OMDb 未能获取评分，请检查凭据、配额或 IMDb ID')
        if data.get('imdbID') and data['imdbID'] != identity:
            raise ProviderError('OMDb 返回了不同的 IMDb ID')
        if 'imdbRating' not in data or 'imdbVotes' not in data:
            raise ProviderError('OMDb 评分响应格式已变化')
        return _score(data['imdbRating']), _votes(data['imdbVotes'])


_douban_lock = threading.Lock()
_douban_last_request = 0.0


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.split('/')
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item.get('name') if isinstance(item, dict) else item))]


class DoubanProvider:
    def __init__(self, settings: ScrapeSettings) -> None:
        self.settings = settings
        settings.validate()

    def _call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        global _douban_last_request
        with _douban_lock:
            wait = self.settings.douban_delay - (time.monotonic() - _douban_last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                return fn(*args, **kwargs)
            except Exception:
                raise ProviderError('豆瓣请求失败，请检查 Node、网络、登录状态或访问限制') from None
            finally:
                _douban_last_request = time.monotonic()

    @staticmethod
    def _candidate(item: dict) -> Candidate:
        identity, title = _text(item.get('id')), _text(item.get('title'))
        if not re.fullmatch(r'\d+', identity) or not title:
            raise ProviderError('豆瓣电影条目格式异常，缺少有效 ID 或片名')
        return Candidate('douban', identity, title, _text(item.get('original_title')),
                         _text(item.get('year')), _text(item.get('summary')), _text(item.get('cover')),
                         media_type=_text(item.get('type')) or 'movie')

    def search(self, query: str, year: str = '', page: int = 1) -> list[Candidate]:
        page = _page(page)
        query = query.strip()
        if not query:
            raise ProviderError('请输入电影名称或豆瓣 ID')
        identity = _numeric_id(query, 'douban')
        if identity:
            data = self._detail(identity)
            return [self._candidate({**data, 'id': identity})]
        if '://' in query:
            raise ProviderError('无法识别的豆瓣电影链接')
        return self._search_title(query, page)

    def _search_title(self, query: str, page: int = 1) -> list[Candidate]:
        from .douban_cli import run_douban_cli
        data = self._call(run_douban_cli, 'search', query, '--start', str((page - 1) * 20),
                          '--limit', '20', timeout=self.settings.timeout)
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ProviderError('豆瓣搜索失败或响应格式变化，请检查网络与访问限制')
        return [self._candidate(item) for item in data if item.get('type', 'movie') == 'movie']

    def _detail(self, identity: str) -> dict:
        from .douban_cli import get_movie_detail
        data = self._call(get_movie_detail, identity)
        if not isinstance(data, dict) or not _text(data.get('title')):
            raise ProviderError('豆瓣详情失败或响应格式变化，请检查网络与访问限制')
        if data.get('type', 'movie') != 'movie':
            raise ProviderError('该豆瓣条目是剧集，请选择电影')
        if data.get('id') is not None and _text(data['id']) != identity:
            raise ProviderError('豆瓣返回了不同的电影 ID')
        return data

    def by_id(self, identity: str) -> Metadata:
        if not re.fullmatch(r'\d+', identity):
            raise ProviderError('豆瓣 ID 格式无效')
        return self.details(Candidate('douban', identity, ''))

    def details(self, candidate: Candidate) -> Metadata:
        if candidate.source != 'douban' or not re.fullmatch(r'\d+', candidate.id) or candidate.media_type != 'movie':
            raise ProviderError('请选择有效的豆瓣电影候选')
        data = self._detail(candidate.id)
        fields: dict[str, Any] = {
            'title': _text(data.get('title')), 'original_title': _text(data.get('original_title')),
            'year': _text(data.get('year')), 'plot': _text(data.get('summary')),
            'genres': _names(data.get('genres')), 'countries': _names(data.get('countries')),
            'directors': _names(data.get('directors')),
            'actors': [{'name': name, 'role': '', 'thumb': ''} for name in _names(data.get('actors'))],
        }
        durations = _names(data.get('durations'))
        runtime = re.search(r'\d+', durations[0]) if durations else None
        if runtime:
            fields['runtime'] = runtime.group()
        dates = _names(data.get('pubdate'))
        for date in dates:
            match = re.match(r'\d{4}-\d{2}-\d{2}', date)
            if match:
                fields['premiered'] = match.group()
                break
        result = Metadata('douban', candidate.id, fields=fields, ids={'douban': candidate.id})
        imdb = _imdb_id(_text(data.get('imdb_id')))
        if imdb:
            result.ids['imdb'] = imdb
        score = _score(data.get('rating'))
        # CLI 0.7.0 将未评分表示为 '-'；旧响应中的 0 同样表示缺失。
        if score is not None and score > 0:
            result.ratings['douban'] = score
            votes = _votes(data.get('rating_count'))
            if votes is not None:
                result.votes['douban'] = votes
        cover = candidate.poster_url or _text(data.get('cover'))
        if not cover:
            try:
                matches = self._search_title(fields['title'])
                cover = next((item.poster_url for item in matches if item.id == candidate.id), '')
            except ProviderError:
                result.warnings.append('豆瓣海报补查失败，可仅保存元数据')
        if cover:
            result.artwork.append(Artwork(cover, preview_url=cover, source='douban'))
        else:
            result.warnings.append('豆瓣未提供该 ID 的海报')
        if self.settings.proxy:
            result.warnings.append('豆瓣由 douban-cli 请求，未验证其支持本应用的代理设置')
        return result
