import io
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from utils import bilibili
from utils.bilibili import (
    open_bilibili_play,
    open_bilibili_search,
    open_bridge_url,
    search_web_url,
    video_player_uri,
    video_web_url,
)


def test_search_url_opens_film_tab_with_only_title():
    url = urlsplit(search_web_url('抓特务'))
    assert (url.scheme, url.netloc, url.path) == ('https', 'search.bilibili.com', '/pgc')
    assert parse_qs(url.query) == {'keyword': ['抓特务']}


def test_search_uses_bilibili_web_results():
    calls = []
    mode = open_bilibili_search(
        '电影', original_title='Movie', year='2025',
        browser=lambda url, new=2: calls.append(url) or True,
    )
    assert mode == 'browser'
    assert calls == [search_web_url('电影')]


def test_play_opens_best_video_through_local_client():
    video = {'player_uri': video_player_uri('BV1xx411c7mD', 123, 456),
             'aid': 123, 'cid': 456, 'page': 1,
             'url': video_web_url('BV1xx411c7mD')}
    calls = []
    mode = open_bilibili_play(
        '电影', 'Movie', '2025',
        local_launcher=lambda uri: calls.append(uri) or True,
        browser=lambda url, new=2: False,
        finder=lambda title, original, year: video,
    )
    assert mode == 'app'
    scheme = urlsplit(calls[0])
    assert (scheme.scheme, scheme.netloc, scheme.path) == ('bilipc', 'page', '/player')
    assert parse_qs(scheme.query) == {
        'type': ['ugc'], 'bvid': ['BV1xx411c7mD'], 'aid': ['123'],
        'cid': ['456'], 'page': ['1'], 'itemId': ['456'],
    }


def test_play_opens_same_video_in_browser_if_no_local_handler():
    video = {'player_uri': video_player_uri('BV1xx411c7mD', 123, 456),
             'url': video_web_url('BV1xx411c7mD')}
    calls = []
    assert open_bilibili_play('沙丘', finder=lambda *args: video,
                              local_launcher=lambda uri: False,
                              browser=lambda url, new=2: calls.append(url) or True) == 'browser'
    assert calls == [video['url']]


def test_find_video_skips_unrelated_and_unavailable_results(monkeypatch):
    monkeypatch.setattr(bilibili, '_search_results', lambda keyword: {'video': [
        {'title': '2021 科幻电影合集', 'bvid': 'BV1xx411c7mA'},
        {'title': '《沙丘》2021', 'bvid': 'BV1xx411c7mB'},
        {'title': '沙丘电影解说', 'bvid': 'BV1xx411c7mC'},
        {'title': 'Dune', 'bvid': 'BV1xx411c7mD'},
    ]})
    requests = []

    def resolve(bvid):
        requests.append(bvid)
        if bvid.endswith('B'):
            raise ValueError('视频已删除')
        return {'aid': 123, 'cid': 456, 'title': 'Dune'}

    monkeypatch.setattr(bilibili, 'resolve_video', resolve)
    video = bilibili.find_play_video('沙丘', 'Dune', '2021')
    assert requests == ['BV1xx411c7mB', 'BV1xx411c7mD']
    assert video['url'] == video_web_url('BV1xx411c7mD')


@pytest.mark.parametrize('has_client', [True, False])
def test_play_opens_official_original_edition_over_same_title_upload(monkeypatch, has_client):
    queries = []
    title = '星球大战：曼达洛人与古古'

    def search(keyword):
        queries.append(keyword)
        return {
            'media_ft': [{'title': f'<em>{title}</em>', 'season_type': 2, 'season_id': 228358,
                          'eps': [{'title': '预告', 'id': 12}]}],
            'video': [{'title': title, 'bvid': 'BV1RQM361EFe'}],
        }

    def get_season(request, timeout):
        assert request.full_url == 'https://api.bilibili.com/pgc/view/web/season?season_id=228358'
        return io.BytesIO(json.dumps({'code': 0, 'result': {'season_id': 228358, 'episodes': [
            {'id': 12, 'title': '预告'}, {'id': 6319572, 'title': '中文版'}, {'id': 6319566, 'title': '原版'},
        ]}}).encode())

    monkeypatch.setattr(bilibili, '_search_results', search)
    monkeypatch.setattr(bilibili, 'resolve_video', lambda bvid: pytest.fail('Attempted to resolve a user upload'))
    monkeypatch.setattr(bilibili.urllib.request, 'urlopen', get_season)
    opened, launched = [], []
    target = 'moviewall://bilibili/play?' + urlencode({
        'keyword': title, 'title': title, 'year': '2026',
        'fallback': 'https://search.bilibili.com/video?keyword=outdated',
    })
    assert open_bridge_url(
        target, local_launcher=lambda uri: launched.append(uri) or has_client,
        browser=lambda url, new=2: opened.append(url) or True,
    ) == ('app' if has_client else 'browser')
    assert queries == [title]
    assert launched == ['bilipc://page/player?type=ogv&epid=6319566&seasonId=228358']
    assert opened == ([] if has_client else ['https://www.bilibili.com/bangumi/play/ep6319566?theme=movie'])


def test_only_trailer_opens_official_title_page_without_native_launch(monkeypatch):
    monkeypatch.setattr(bilibili, '_search_results', lambda keyword: {
        'media_ft': [{'title': '抓特务', 'season_type': 2, 'season_id': 111193}],
    })
    payload = {'code': 0, 'result': {'season_id': 111193, 'episodes': [{'id': 5512246, 'title': 'PV1 预告'}]}}
    monkeypatch.setattr(bilibili.urllib.request, 'urlopen',
                        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    opened = []
    assert open_bilibili_play(
        '抓特务', local_launcher=lambda uri: pytest.fail(f'Unexpected trailer launch: {uri}'),
        browser=lambda url, new=2: opened.append(url) or True,
    ) == 'browser'
    assert opened == ['https://www.bilibili.com/bangumi/play/ss111193?theme=movie']


@pytest.mark.parametrize(('year', 'season'), [('2021', 40396), ('', None)])
def test_uses_year_to_distinguish_same_title_official_movies(monkeypatch, year, season):
    monkeypatch.setattr(bilibili, '_search_results', lambda keyword: {'media_ft': [
        {'title': '沙丘', 'season_type': 2, 'season_id': 40752, 'index_show': '1984-12-14上映'},
        {'title': '沙丘', 'season_type': 2, 'season_id': 40396, 'index_show': '2021-10-22上映'},
    ]})
    def get_season(request, timeout):
        assert season is not None
        assert parse_qs(urlsplit(request.full_url).query) == {'season_id': [str(season)]}
        raise OSError('Episode metadata temporarily unavailable')

    monkeypatch.setattr(bilibili.urllib.request, 'urlopen', get_season)
    opened = []
    open_bilibili_play('沙丘', year=year, browser=lambda url, new=2: opened.append(url) or True)
    assert opened == [f'https://www.bilibili.com/bangumi/play/ss{season}?theme=movie' if season else search_web_url('沙丘')]


def test_resolve_video_rejects_response_for_different_video(monkeypatch):
    payload = {'code': 0, 'data': {'bvid': 'BV1xx411c7mB', 'aid': 123, 'cid': 456}}
    monkeypatch.setattr(bilibili.urllib.request, 'urlopen',
                        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(ValueError):
        bilibili.resolve_video('BV1xx411c7mA')


@pytest.mark.parametrize('hints', [{}, {'title': '沙丘', 'original_title': 'Dune', 'year': '2021'}])
def test_bridge_no_match_opens_search_without_launching_client(hints):
    keyword = '沙丘 Dune 2021 电影'
    calls = []

    def find(title, original_title, year):
        calls.append((title, original_title, year))
        return None

    target = 'moviewall://bilibili/play?' + urlencode({'keyword': keyword, **hints})
    assert open_bridge_url(target, finder=find,
                           local_launcher=lambda uri: pytest.fail(f'Unexpected native URI: {uri}'),
                           browser=lambda url, new=2: calls.append(url) or True) == 'browser'
    assert calls == [(
        hints.get('title', '沙丘 Dune'), hints.get('original_title', ''),
        hints.get('year', '2021'),
    ), search_web_url(hints.get('title', '沙丘 Dune'))]


def test_bridge_accepts_only_moviewall_bilibili_urls():
    target = 'moviewall://bilibili/search?' + urlencode({'keyword': '电影', 'fallback': search_web_url('电影')})
    calls = []
    assert open_bridge_url(target, local_launcher=lambda uri: calls.append(uri) or True,
                           browser=lambda url, new=2: calls.append(url) or True) == 'browser'
    assert calls == [search_web_url('电影')]
    with pytest.raises(ValueError):
        open_bridge_url('moviewall://other/search?keyword=x')


def test_bridge_ignores_non_bilibili_fallback():
    target = 'moviewall://bilibili/search?' + urlencode({'keyword': '电影', 'fallback': 'https://evil.example/'})
    calls = []
    open_bridge_url(target, local_launcher=lambda uri: False,
                    browser=lambda url, new=2: calls.append(url) or True)
    assert calls == [search_web_url('电影')]
