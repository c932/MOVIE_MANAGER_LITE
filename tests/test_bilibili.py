from urllib.parse import quote

import pytest

from utils.bilibili import (
    movie_query,
    open_bilibili_play,
    open_bilibili_search,
    open_bridge_url,
    search_player_uri,
    search_web_url,
    video_player_uri,
    video_web_url,
)


def test_movie_query_deduplicates_and_encodes():
    assert movie_query('沙丘', 'Dune', '2021', play=True) == '沙丘 Dune 2021 电影'
    uri = search_player_uri('沙丘 2021')
    assert uri.startswith('bilibili://search?keyword=')
    assert '2021' in uri
    assert 'order=click' in search_web_url('沙丘 2021')


def test_search_prefers_local_bilibili_and_falls_back_to_browser():
    calls = []
    mode = open_bilibili_search(
        '电影', original_title='Movie', year='2025',
        local_launcher=lambda uri: calls.append(('app', uri)) or True,
        browser=lambda url, new=2: calls.append(('web', url)) or True,
    )
    assert mode == 'app'
    assert calls[0][0] == 'app' and calls[0][1].startswith('bilibili://search?')

    calls.clear()
    mode = open_bilibili_search(
        '电影', local_launcher=lambda uri: False,
        browser=lambda url, new=2: calls.append(url) or True,
    )
    assert mode == 'browser'
    assert calls == [search_web_url('电影')]


def test_play_opens_best_video_through_local_client():
    video = {'player_uri': video_player_uri('BV1xx411c7mD'),
             'url': video_web_url('BV1xx411c7mD')}
    calls = []
    mode = open_bilibili_play(
        '电影', 'Movie', '2025',
        local_launcher=lambda uri: calls.append(uri) or True,
        browser=lambda url, new=2: False,
        finder=lambda title, original, year: video,
    )
    assert mode == 'app'
    assert calls == [video['player_uri']]


def test_bridge_accepts_only_moviewall_bilibili_urls():
    target = 'moviewall://bilibili/search?keyword=' + quote('电影', safe='') + '&fallback=' + quote(search_web_url('电影'), safe='')
    calls = []
    assert open_bridge_url(target, local_launcher=lambda uri: calls.append(uri) or True,
                           browser=lambda url, new=2: False) == 'app'
    assert calls[0].startswith('bilibili://search?')
    with pytest.raises(ValueError):
        open_bridge_url('moviewall://other/search?keyword=x')


def test_bridge_ignores_non_bilibili_fallback():
    target = 'moviewall://bilibili/search?keyword=' + quote('电影', safe='') + '&fallback=' + quote('https://evil.example/', safe='')
    calls = []
    open_bridge_url(target, local_launcher=lambda uri: False,
                    browser=lambda url, new=2: calls.append(url) or True)
    assert calls == [search_web_url('电影')]
