"""IMDb 页面评分：仅替换网络边界，身份判断与有界下载使用真实实现。"""
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from scraper.metadata_sources import ProviderError
from scraper.scrape_settings import ScrapeSettings


IDENTITY = 'tt0143145'
URL = 'https://www.imdb.com/title/tt0143145/'


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def transport(monkeypatch, body, *, status=200, headers=None, error=None):
    import urllib.request
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            if error is not None:
                raise error
            return Response(body.encode('utf-8'), status, headers)

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Opener())
    return calls


def rating():
    from scraper.imdb_provider import ImdbProvider
    return ImdbProvider(ScrapeSettings(timeout=7)).rating(IDENTITY)


def ld_movie(**changes):
    return {'@context': 'https://schema.org', '@type': 'Movie', 'url': URL,
            'name': '目标电影', 'aggregateRating': {
                '@type': 'AggregateRating', 'ratingValue': 7.4, 'ratingCount': 52871,
                'bestRating': 10, 'worstRating': 1}, **changes}


def ld_script(data):
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def next_script(**page_props):
    data = {'props': {'pageProps': page_props}, 'query': {'tconst': IDENTITY}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>'


def test_json_ld_downloads_imdb_directly_without_credentials(monkeypatch):
    calls = transport(monkeypatch, ld_script(ld_movie()))
    assert rating() == (7.4, 52871)
    request, timeout = calls[0]
    assert request.full_url == URL
    assert timeout == 7
    assert request.get_header('Authorization') is None
    assert len(calls) == 1


@pytest.mark.parametrize('container', ['array', 'graph'])
def test_json_ld_only_uses_matching_title_in_array_or_graph(monkeypatch, container):
    items = [ld_movie(url='https://www.imdb.com/title/tt0111161/',
                      aggregateRating={'ratingValue': 9.3, 'ratingCount': 3000000}), ld_movie()]
    data = items if container == 'array' else {'@context': 'https://schema.org', '@graph': items}
    transport(monkeypatch, ld_script(data))
    assert rating() == (7.4, 52871)


@pytest.mark.parametrize('key', ['aboveTheFoldData', 'mainColumnData'])
def test_next_data_reads_only_direct_rating_of_identified_title(monkeypatch, key):
    title = {'id': IDENTITY, 'ratingsSummary': {'aggregateRating': 6.8, 'voteCount': 12345},
             'moreLikeThisTitles': {'edges': [{'node': {'id': 'tt0111161',
                'ratingsSummary': {'aggregateRating': 9.3, 'voteCount': 3000000}}}]}}
    transport(monkeypatch, next_script(**{key: title}))
    assert rating() == (6.8, 12345)


def test_next_data_fallback_when_ld_is_broken_or_unrated(monkeypatch):
    body = '<script type="application/ld+json">{broken</script>' + ld_script(ld_movie(aggregateRating=None))
    body += next_script(aboveTheFoldData={'id': IDENTITY,
                         'ratingsSummary': {'aggregateRating': 6.8, 'voteCount': 12345}})
    transport(monkeypatch, body)
    assert rating() == (6.8, 12345)


@pytest.mark.parametrize('changes', [
    {'url': None, '@id': URL + '#title'},
    {'url': '/title/tt0143145/'},
    {'url': 'https://imdb.com/title/tt0143145/?ref_=test'},
    {'@type': ['Movie', 'CreativeWork']},
])
def test_json_ld_supports_explicit_title_identity_forms(monkeypatch, changes):
    transport(monkeypatch, ld_script(ld_movie(**changes)))
    assert rating() == (7.4, 52871)


@pytest.mark.parametrize('body', [
    ld_script(ld_movie(url='https://www.imdb.com/title/tt0111161/')),
    ld_script(ld_movie(url=None)),
    ld_script(ld_movie(url='https://imdb.com.evil.test/title/tt0143145/')),
    ld_script(ld_movie(url='https://www.imdb.com/title/tt01431450/')),
    ld_script(ld_movie(url='https://www.imdb.com/title/tt0143145/',
                       **{'@id': 'https://www.imdb.com/title/tt0111161/'})),
    next_script(aboveTheFoldData={'id': 'tt0111161', 'ratingsSummary': {
        'aggregateRating': 9.3, 'voteCount': 3000000}}),
    next_script(aboveTheFoldData={'ratingsSummary': {'aggregateRating': 7.4, 'voteCount': 52871}}),
    '<link rel="canonical" href="https://www.imdb.com/title/tt0111161/">' + ld_script(ld_movie()),
])
def test_wrong_or_missing_identity_is_rejected(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ProviderError):
        rating()


def test_recommendation_rating_cannot_fill_missing_target_rating(monkeypatch):
    title = ld_movie(aggregateRating=None, subjectOf=ld_movie())
    body = ld_script(title) + next_script(aboveTheFoldData={
        'id': IDENTITY, 'ratingsSummary': None, 'recommendations': [
            {'id': IDENTITY, 'ratingsSummary': {'aggregateRating': 9.3, 'voteCount': 3000000}}]})
    transport(monkeypatch, body)
    assert rating() == (None, None)


def test_matching_recommendation_cannot_validate_wrong_next_page(monkeypatch):
    body = next_script(aboveTheFoldData={'id': 'tt0111161', 'recommendations': [
        {'id': IDENTITY, 'ratingsSummary': {'aggregateRating': 7.4, 'voteCount': 52871}}]})
    transport(monkeypatch, body)
    with pytest.raises(ProviderError):
        rating()


@pytest.mark.parametrize(('score', 'votes'), [
    (7.4, 0), (0, 0), (7.4, None), (None, 52871), ('NaN', 52871),
    (float('nan'), 52871), (float('inf'), 52871), (-1, 52871), (11, 52871),
    (True, 52871), (7.4, True), (7.4, -1), (7.4, '1.5'), (7.4, '52K'),
    (7.4, float('nan')), (7.4, float('inf')),
])
def test_invalid_or_unvoted_aggregate_never_returns_usable_rating(monkeypatch, score, votes):
    transport(monkeypatch, ld_script(ld_movie(aggregateRating={
        'ratingValue': score, 'ratingCount': votes})))
    assert rating() == (None, None)


def test_json_ld_accepts_grouped_integer_count(monkeypatch):
    transport(monkeypatch, ld_script(ld_movie(aggregateRating={
        'ratingValue': '7.4', 'ratingCount': '1,234,567'})))
    assert rating() == (7.4, 1234567)


def test_non_ten_point_scale_is_not_imdb_score(monkeypatch):
    transport(monkeypatch, ld_script(ld_movie(aggregateRating={
        'ratingValue': 4, 'ratingCount': 300, 'bestRating': 5})))
    assert rating() == (None, None)


@pytest.mark.parametrize('body', [
    ld_script(ld_movie(aggregateRating=None)),
    next_script(aboveTheFoldData={'id': IDENTITY, 'ratingsSummary': {'aggregateRating': 0, 'voteCount': 0}}),
])
def test_known_title_without_rating_returns_none(monkeypatch, body):
    transport(monkeypatch, body)
    assert rating() == (None, None)


@pytest.mark.parametrize('body', [
    '<html><title>Just a moment...</title><p>Verify you are human</p></html>',
    '<html><script src="https://example.test/awswaf/challenge.js"></script></html>',
    '<html><title>Robot Check</title><p>Please enable JavaScript</p></html>',
    '<html><p>Sorry, something went wrong</p></html>',
    '<script type="application/ld+json">{broken</script>',
    '',
])
def test_challenge_or_unrecognized_html_raises_visible_error(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ProviderError):
        rating()


def test_challenge_rejects_even_embedded_matching_rating(monkeypatch):
    transport(monkeypatch, '<p>Verify you are human</p>' + ld_script(ld_movie()))
    with pytest.raises(ProviderError, match='验证|受限'):
        rating()


def test_captcha_word_in_movie_description_is_not_a_challenge(monkeypatch):
    transport(monkeypatch, ld_script(ld_movie(description='A movie about captcha and robots.')))
    assert rating() == (7.4, 52871)


@pytest.mark.parametrize('status', [202, 403, 404])
def test_http_failure_has_visible_status_and_no_credential_request(monkeypatch, status):
    calls = transport(monkeypatch, 'not a page', status=status)
    with pytest.raises(ProviderError, match=str(status)):
        rating()
    assert len(calls) == (2 if status in {202, 403} else 1)


def test_urllib_403_does_not_request_api_key_or_retry(monkeypatch):
    calls = transport(monkeypatch, '', error=HTTPError(URL, 403, 'forbidden', {}, None))
    with pytest.raises(ProviderError, match='403') as error:
        rating()
    assert 'Key' not in str(error.value)
    assert len(calls) == 2  # 网页不重试；第二次请求是官方数据集。


def test_network_error_is_visible_without_echoing_transport_detail(monkeypatch):
    transport(monkeypatch, '', error=URLError('private transport diagnostic'))
    with pytest.raises(ProviderError) as error:
        rating()
    assert 'private transport diagnostic' not in str(error.value)


def test_page_download_is_bounded(monkeypatch):
    transport(monkeypatch, ld_script(ld_movie()), headers={'Content-Length': str(100 * 1024 * 1024)})
    with pytest.raises(ProviderError, match='上限'):
        rating()


@pytest.mark.parametrize('identity', ['', '0143145', 'tt1/path', 'tt0143145?key=x', None, True])
def test_invalid_id_never_reaches_network(monkeypatch, identity):
    from scraper.imdb_provider import ImdbProvider
    calls = transport(monkeypatch, ld_script(ld_movie()))
    with pytest.raises(ProviderError):
        ImdbProvider(ScrapeSettings()).rating(identity)
    assert calls == []
