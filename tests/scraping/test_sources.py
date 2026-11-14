import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

import pytest

from scraper.scrape_models import Candidate, ScrapeError
from scraper.scrape_settings import ScrapeSettings


class Response(io.BytesIO):
    def __init__(self, body=b'{}', status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def transport(monkeypatch, replies):
    """Only replace the external urllib boundary; providers and HTTP parsing stay real."""
    import urllib.request
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, Response):
                return reply
            return Response(json.dumps(reply).encode('utf-8'))
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Opener())
    return calls


def movie_record(id=1, title='重名电影'):
    return {'id': id, 'title': title, 'original_title': 'Film',
            'release_date': '2024-03-01', 'overview': '简介', 'poster_path': '/poster.jpg'}


def test_tmdb_search_retains_same_title_and_unrated_candidates(monkeypatch):
    from scraper.metadata_sources import TmdbProvider
    calls = transport(monkeypatch, [{'results': [movie_record(1), movie_record(2)]}])
    result = TmdbProvider(ScrapeSettings(tmdb_token='test-token', timeout=7)).search('重名电影', '2024', 2)
    assert [c.id for c in result] == ['1', '2']
    assert result[0].poster_url == 'https://image.tmdb.org/t/p/original/poster.jpg'
    request, timeout = calls[0]
    assert request.get_header('Authorization') == 'Bearer test-token'
    assert timeout == 7
    assert urlsplit(request.full_url).path == '/3/search/movie'
    params = parse_qs(urlsplit(request.full_url).query)
    assert params['year'] == ['2024'] and params['page'] == ['2']
    assert params['language'] == ['zh-CN']


@pytest.mark.parametrize('query', ['17', 'https://www.themoviedb.org/movie/17-film'])
def test_tmdb_direct_id_does_not_do_title_search(monkeypatch, query):
    from scraper.metadata_sources import TmdbProvider
    calls = transport(monkeypatch, [movie_record(17)])
    assert TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).search(query)[0].id == '17'
    assert urlsplit(calls[0][0].full_url).path == '/3/movie/17'


@pytest.mark.parametrize('query', ['tt0111161', 'https://www.imdb.com/title/tt0111161/'])
def test_tmdb_imdb_find_uses_only_movie_results(monkeypatch, query):
    from scraper.metadata_sources import TmdbProvider
    calls = transport(monkeypatch, [{'movie_results': [movie_record(17)], 'tv_results': [{'id': 99}]}])
    assert TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).search(query)[0].id == '17'
    assert urlsplit(calls[0][0].full_url).path == '/3/find/tt0111161'
    assert parse_qs(urlsplit(calls[0][0].full_url).query)['external_source'] == ['imdb_id']


def test_tmdb_details_map_writer_fields_and_sort_chinese_artwork(monkeypatch):
    from scraper.metadata_sources import TmdbProvider
    from parsers.nfo_writer import apply_fields
    record = dict(movie_record(17), runtime=123, tagline='标语',
                  genres=[{'id': 1, 'name': '科幻'}], production_countries=[{'name': '中国'}],
                  belongs_to_collection={'name': '系列'}, vote_average=8.1, vote_count=234)
    transport(monkeypatch, [record, {'imdb_id': 'tt0111161'},
        {'cast': [{'name': '演员', 'character': '角色', 'profile_path': '/actor.jpg'}],
         'crew': [{'name': '导演', 'job': 'Director'}, {'name': '编剧', 'job': 'Writer'}]},
        {'posters': [
            {'file_path': '/en.jpg', 'iso_639_1': 'en', 'width': 1000, 'height': 1500},
            {'file_path': '/none.jpg', 'iso_639_1': None},
            {'file_path': '/zh.jpg', 'iso_639_1': 'zh', 'width': 800, 'height': 1200}]}])
    metadata = TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).details(Candidate('tmdb', '17', '片名'))
    assert metadata.ids == {'tmdb': '17', 'imdb': 'tt0111161'}
    assert metadata.ratings == {'tmdb': 8.1} and metadata.votes == {'tmdb': 234}
    assert metadata.fields['runtime'] == '123'
    assert metadata.fields['genres'] == ['科幻']
    assert metadata.fields['directors'] == ['导演']
    assert metadata.fields['actors'][0]['role'] == '角色'
    assert metadata.fields['set_name'] == '系列'
    assert [a.language for a in metadata.artwork] == ['zh', '', 'en']
    apply_fields(ET.Element('movie'), metadata.fields)


def test_tmdb_zero_votes_does_not_fabricate_zero_rating(monkeypatch):
    from scraper.metadata_sources import TmdbProvider
    transport(monkeypatch, [dict(movie_record(), vote_average=0, vote_count=0), {'imdb_id': None},
                           {'cast': [], 'crew': []}, {'posters': []}])
    metadata = TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).details(Candidate('tmdb', '1', '片名'))
    assert metadata.ratings == {} and metadata.votes == {}


def test_missing_credentials_and_wrong_response_are_visible(monkeypatch):
    from scraper.metadata_sources import TmdbProvider, OmdbProvider, ProviderError
    assert issubclass(ProviderError, ScrapeError)
    with pytest.raises(ProviderError):
        TmdbProvider(ScrapeSettings()).search('movie')
    with pytest.raises(ProviderError):
        OmdbProvider(ScrapeSettings()).rating('tt0111161')
    transport(monkeypatch, [{'results': 'changed format'}])
    with pytest.raises(ProviderError):
        TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).search('movie')


@pytest.mark.parametrize(('rating', 'votes', 'expected'), [
    ('8.8', '1,234,567', (8.8, 1234567)), ('N/A', 'N/A', (None, None)),
    ('NaN', '13', (None, 13)), ('11', '-1', (None, None)),
])
def test_omdb_https_independent_imdb_rating(monkeypatch, rating, votes, expected):
    from scraper.metadata_sources import OmdbProvider
    calls = transport(monkeypatch, [{'Response': 'True', 'imdbRating': rating, 'imdbVotes': votes}])
    assert OmdbProvider(ScrapeSettings(omdb_api_key='fake-key')).rating('tt0111161') == expected
    assert calls[0][0].full_url.startswith('https://www.omdbapi.com/')


def test_omdb_errors_never_expose_key(monkeypatch):
    from scraper.metadata_sources import OmdbProvider, ProviderError
    transport(monkeypatch, [{'Response': 'False', 'Error': 'Invalid API key: secret-test-key'}])
    with pytest.raises(ProviderError) as error:
        OmdbProvider(ScrapeSettings(omdb_api_key='secret-test-key')).rating('tt0111161')
    assert 'secret-test-key' not in str(error.value)


def test_douban_search_retains_unrated_covers_and_filters_tv(monkeypatch):
    from scraper.metadata_sources import DoubanProvider
    import scraper.douban_cli as cli
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return [{'id': '1', 'title': '同名', 'type': 'movie', 'year': '2026', 'rating': '', 'cover': 'https://img/1.jpg'},
                {'id': '2', 'title': '同名', 'type': 'movie', 'year': '2000', 'rating': 8},
                {'id': '3', 'title': '同名', 'type': 'tv', 'rating': 9}]
    monkeypatch.setattr(cli, 'run_douban_cli', run)
    candidates = DoubanProvider(ScrapeSettings(douban_delay=0)).search('同名', '2026', 2)
    assert [c.id for c in candidates] == ['1', '2']
    assert candidates[0].poster_url == 'https://img/1.jpg'
    assert '--start' in calls[0][0] and '20' in calls[0][0]


def test_douban_real_070_structure_no_guessed_imdb_or_comment_votes(monkeypatch):
    from scraper.metadata_sources import DoubanProvider
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {
        'id': id, 'title': '电影', 'type': 'movie', 'year': '2026', 'rating': '-',
        'summary': '真实简介', 'actors': ['张三', '李四'], 'directors': ['王五'],
        'genres': ['剧情'], 'countries': ['中国大陆'], 'durations': ['123分钟'], 'comment_count': 200})
    metadata = DoubanProvider(ScrapeSettings(douban_delay=0)).details(
        Candidate('douban', '1', '电影', poster_url='https://img/1.jpg'))
    assert metadata.fields['plot'] == '真实简介'
    assert metadata.fields['actors'][0]['name'] == '张三'
    assert metadata.fields['directors'] == ['王五'] and metadata.fields['runtime'] == '123'
    assert metadata.ids == {'douban': '1'}
    assert metadata.ratings == {} and metadata.votes == {}
    assert metadata.artwork[0].url == 'https://img/1.jpg'


def test_douban_link_locates_id_and_cover_by_exact_id_only(monkeypatch):
    from scraper.metadata_sources import DoubanProvider
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {'id': id, 'title': '同名', 'summary': '简介', 'rating': 8.2, 'rating_count': 10, 'comment_count': 999})
    monkeypatch.setattr(cli, 'run_douban_cli', lambda *args, **kw: [
        {'id': '2', 'title': '同名', 'type': 'movie', 'cover': 'https://img/wrong.jpg'},
        {'id': '1', 'title': '同名', 'type': 'movie', 'cover': 'https://img/right.jpg'}])
    provider = DoubanProvider(ScrapeSettings(douban_delay=0))
    candidate = provider.search('https://movie.douban.com/subject/1/')[0]
    assert candidate.id == '1'
    metadata = provider.details(candidate)
    assert metadata.artwork[0].url == 'https://img/right.jpg'
    assert metadata.votes == {'douban': 10}


def test_douban_missing_cover_never_uses_other_identity(monkeypatch):
    from scraper.metadata_sources import DoubanProvider
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {'title': '同名'})
    monkeypatch.setattr(cli, 'run_douban_cli', lambda *a, **k: [{'id': '2', 'title': '同名', 'cover': 'https://img/wrong.jpg', 'type': 'movie'}])
    metadata = DoubanProvider(ScrapeSettings(douban_delay=0)).details(Candidate('douban', '1', '同名'))
    assert not metadata.artwork and metadata.warnings


@pytest.mark.parametrize('payload', [None, {}, {'error': 'blocked'}, 'changed'])
def test_douban_invalid_search_is_not_empty_success(monkeypatch, payload):
    from scraper.metadata_sources import DoubanProvider, ProviderError
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'run_douban_cli', lambda *a, **k: payload)
    with pytest.raises(ProviderError):
        DoubanProvider(ScrapeSettings(douban_delay=0)).search('电影')


@pytest.mark.parametrize('status', [202, 204])
def test_http_empty_response_is_error(monkeypatch, status):
    from scraper.scrape_http import HttpClient
    transport(monkeypatch, [Response(b'', status)])
    with pytest.raises(ScrapeError):
        HttpClient(ScrapeSettings()).get_json('https://example.invalid/test')


def test_http_bounds_bytes_and_rejects_malformed_json(monkeypatch):
    from scraper.scrape_http import HttpClient
    transport(monkeypatch, [Response(b'123456'), Response(b'<html>challenge</html>')])
    client = HttpClient(ScrapeSettings())
    with pytest.raises(ScrapeError):
        client.get_bytes('https://example.invalid/image', max_bytes=5)
    with pytest.raises(ScrapeError):
        client.get_json('https://example.invalid/test')


@pytest.mark.parametrize('status', [401, 403, 429, 503])
def test_http_errors_sanitized_and_retry_bounded(monkeypatch, status):
    from scraper.scrape_http import HttpClient
    url = 'https://example.invalid/?apikey=secret-test'
    errors = [HTTPError(url, status, url, {}, None) for _ in range(3)]
    calls = transport(monkeypatch, errors)
    with pytest.raises(ScrapeError) as error:
        HttpClient(ScrapeSettings(), retries=1).get_json(url)
    assert 'secret-test' not in str(error.value)
    assert len(calls) == (2 if status in (429, 503) else 1)


def test_http_network_retry_then_success_and_proxy_timeout(monkeypatch):
    from scraper.scrape_http import HttpClient
    import urllib.request
    calls = transport(monkeypatch, [URLError('secret-test'), {'ok': True}])
    original = urllib.request.build_opener
    handlers_seen = []
    def opener(*handlers):
        handlers_seen.extend(handlers)
        return original(*handlers)
    monkeypatch.setattr(urllib.request, 'build_opener', opener)
    client = HttpClient(ScrapeSettings(proxy='http://127.0.0.1:8888', timeout=3), retries=1)
    assert client.get_json('https://example.invalid/') == {'ok': True}
    assert len(calls) == 2 and calls[0][1] == 3
    assert any(getattr(h, 'proxies', {}) == {'http': 'http://127.0.0.1:8888', 'https': 'http://127.0.0.1:8888'} for h in handlers_seen)


@pytest.mark.parametrize('broken', ['external', 'credits', 'images'])
def test_tmdb_changed_detail_schema_is_visible(monkeypatch, broken):
    from scraper.metadata_sources import TmdbProvider, ProviderError
    replies = [movie_record(), {'imdb_id': None}, {'cast': [], 'crew': []}, {'posters': []}]
    replies[{'external': 1, 'credits': 2, 'images': 3}[broken]] = {'changed': True}
    transport(monkeypatch, replies)
    with pytest.raises(ProviderError):
        TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).details(Candidate('tmdb', '1', '电影'))


@pytest.mark.parametrize('query', ['https://[', 'https://evil.invalid/movie/17', 'https://themoviedb.org/tv/17'])
def test_malformed_or_wrong_source_link_is_domain_error(query):
    from scraper.metadata_sources import TmdbProvider, DoubanProvider, ProviderError
    for provider in (TmdbProvider(ScrapeSettings(tmdb_api_key='fake')), DoubanProvider(ScrapeSettings(douban_delay=0))):
        with pytest.raises(ProviderError):
            provider.search(query)


def test_douban_by_id_uses_identity_and_rejects_mismatched_details(monkeypatch):
    from scraper.metadata_sources import DoubanProvider, ProviderError
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {'id': id, 'title': '电影', 'rating': '8.0', 'cover': 'https://img/a.jpg'})
    metadata = DoubanProvider(ScrapeSettings(douban_delay=0)).by_id('17')
    assert metadata.ids == {'douban': '17'} and metadata.ratings == {'douban': 8.0}
    assert not metadata.votes
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {'id': '99', 'title': '其他电影'})
    with pytest.raises(ProviderError):
        DoubanProvider(ScrapeSettings(douban_delay=0)).by_id('17')


def test_douban_named_numeric_movie_cover_query_is_not_interpreted_as_id(monkeypatch):
    from scraper.metadata_sources import DoubanProvider
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, 'get_movie_detail', lambda id: {'id': id, 'title': '1917'})
    monkeypatch.setattr(cli, 'run_douban_cli', lambda *args, **kw: [
        {'id': '17', 'title': '1917', 'type': 'movie', 'cover': 'https://img/1917.jpg'}])
    metadata = DoubanProvider(ScrapeSettings(douban_delay=0)).by_id('17')
    assert metadata.artwork[0].url == 'https://img/1917.jpg'


@pytest.mark.parametrize('body', [b'null', b'123', b'"string"'])
def test_http_non_container_json_is_error(monkeypatch, body):
    from scraper.scrape_http import HttpClient
    transport(monkeypatch, [Response(body)])
    with pytest.raises(ScrapeError):
        HttpClient(ScrapeSettings()).get_json('https://example.invalid/')


def test_http_bytes_are_unmodified_and_declared_limits_enforced(monkeypatch):
    from scraper.scrape_http import HttpClient
    transport(monkeypatch, [Response(b'raw-image'), Response(b'abc', headers={'Content-Length': '100'}),
                           Response(b'abc', headers={'Content-Length': '4'})])
    client = HttpClient(ScrapeSettings())
    assert client.get_bytes('https://example.invalid/image') == b'raw-image'
    with pytest.raises(ScrapeError):
        client.get_bytes('https://example.invalid/image', max_bytes=10)
    with pytest.raises(ScrapeError):
        client.get_bytes('https://example.invalid/image', max_bytes=10)
