import json
from tests.webapp.test_movie_helpers import movie_client, wait_job


def test_annual_official_categories_and_movie_year(service_data_dir):
    from movie_service.discovery import parse_annual
    result = parse_annual({'widgets': [
        {'id': 0, 'source_data': ['年度台词图']},
        {'id': 1, 'title': '评分最高外语电影', 'source_data': {
            'subject_collection': {'subject_type': 'movie'},
            'subject_collection_items': [{'id': '123', 'title': '电影',
                'card_subtitle': '2024 / 美国', 'cover_url': 'https://img3.doubanio.com/a.jpg',
                'rating': {'value': 8.5}}]}},
        {'id': 2, 'title': '剧集', 'source_data': {
            'subject_collection': {'subject_type': 'tv'}, 'subject_collection_items': []}},
        {'id': 3, 'title': '地区和类型电影', 'source_data': [{
            'subject_collection': {'subject_type': 'movie', 'title': '评分最高动画片'},
            'subject_collection_items': [{'id': '456', 'title': '动画电影'}]}]}
    ]}, 2025)
    assert len(result['categories']) == 2
    assert result['categories'][1]['title'] == '评分最高动画片'
    assert result['categories'][0]['items'][0]['year'] == '2024'
    assert result['categories'][0]['items'][0]['douban_id'] == '123'


def test_annual_refresh_and_detail_are_read_only(service_data_dir, monkeypatch):
    from movie_service import discovery
    calls = []
    def fetch(url):
        calls.append(url)
        if '/annual/' in url:
            return "page: {'id': 33, 'alias': 'movie_2025'}"
        return json.dumps({'widgets': [{'id': 1, 'title': '佳片', 'source_data': {
            'subject_collection': {'subject_type': 'movie'},
            'subject_collection_items': [{'id': '123', 'title': '电影'}]}}]})
    monkeypatch.setattr(discovery, 'fetch_text', fetch)
    monkeypatch.setattr(discovery, 'fetch_subject_page', lambda did: '''
        <span property="v:itemreviewed">电影</span>
        <span property="v:summary">真实简介</span>
    ''')
    with movie_client(service_data_dir) as client:
        assert client.get('/api/movie/discovery/annual/2025').json()['categories'] == []
        job = wait_job(client, client.post('/api/movie/discovery/annual/2025/refresh').json()['job_id'])
        assert job['status'] == 'done', job
        body = client.get('/api/movie/discovery/annual/2025').json()
        assert body['categories'][0]['items'][0]['title'] == '电影'
        assert body['categories'][0]['items'][0]['plot'] == '真实简介'
        assert len(calls) == 2
        job = wait_job(client, client.post('/api/movie/discovery/subject/123').json()['job_id'])
        assert job['result']['plot'] == '真实简介'
        assert client.get('/api/movie/movies').json()['movies'] == []
        assert client.post('/api/movie/discovery/subject/not-id').status_code == 400


def test_browse_warmup_reuses_success_and_isolates_failed_sources(service_data_dir, monkeypatch):
    from movie_service import browse_cache, discovery
    from utils.library_sync import atomic_json
    from wall_common.images import ImageError

    image = 'https://img3.doubanio.com/poster.jpg'
    attempted = []

    def poster(url, cache_dir, **kwargs):
        attempted.append(url)
        assert kwargs['ttl'] == float('inf')
        raise ImageError('图片暂不可用', status_code=502)

    def subject(data_dir, did, ctx):
        attempted.append(did)
        raise ValueError('没有公开简介')

    atomic_json(service_data_dir / 'discovery' / 'subject-123.json', {'plot': '原简介'})
    monkeypatch.setattr(browse_cache, 'cached_remote', poster)
    monkeypatch.setattr(discovery, 'subject_detail', subject)
    result = browse_cache.warm_browse(service_data_dir, service_data_dir / 'covers', [
        {'poster_url': image, 'douban_id': '123', 'plot': '其他简介'},
        {'poster_url': image, 'douban_id': '456'},
        {'poster_url': 'https://[invalid', 'imdb_id': 'tt890', 'plot': 'IMDb 剧情'},
    ])
    assert result == {'posters': 0, 'poster_total': 1, 'plots': 2, 'plot_total': 3}
    assert sorted(attempted) == ['456', image]
    assert browse_cache.cached_plot(service_data_dir, '123') == '原简介'
    assert browse_cache.cached_plot(service_data_dir, 'tt890') == 'IMDb 剧情'


def test_rankings_use_cached_alternative_poster(service_data_dir):
    from scraper.douban_ranking import RankedMovie, save_ranking_cache
    from utils.library_sync import atomic_json

    movie = RankedMovie('Movie', '2025', 8, 'tt123', 1, 'imdb_top250',
                        poster_url='https://m.media-amazon.com/removed.jpg')
    save_ranking_cache([], [], [movie], cache_path=service_data_dir / 'douban_ranking_cache.json')
    atomic_json(service_data_dir / 'discovery' / 'subject-tt123.json',
                {'plot': '预存的简介', 'poster_url': 'https://image.tmdb.org/t/p/w342/poster.jpg'})
    with movie_client(service_data_dir) as client:
        result = client.get('/api/movie/rankings/imdb_top250').json()['items'][0]
    assert result['poster_url'] == 'https://image.tmdb.org/t/p/w342/poster.jpg'
    assert result['plot'] == '预存的简介'


def test_enrich_top250_uses_cached_plot_alternative_poster_and_imdb_rating(service_data_dir, monkeypatch):
    from pathlib import Path
    from movie_service import browse_cache
    from scraper.douban_ranking import RankedMovie
    from scraper.imdb_ratings import ImdbRatings
    from scraper.scrape_settings import ScrapeSettings
    from utils.library_sync import atomic_json

    class Context:
        def update(self, **kwargs):
            assert kwargs['stage'] == '补齐榜单资料'

        def check_cancelled(self):
            pass

    atomic_json(service_data_dir / 'discovery' / 'subject-tt123.json',
                {'plot': '缓存简介', 'poster_url': 'https://image.tmdb.org/t/p/w342/alternate.jpg'})
    monkeypatch.setattr(ImdbRatings, 'rating', lambda self, identity: (8.1, 1200))
    monkeypatch.setattr(browse_cache, 'cached_remote',
                        lambda *args, **kwargs: Path(service_data_dir) / 'cover.img')
    row = RankedMovie('Movie', '2025', 0.0, 'tt123', 1, 'imdb_top250')
    result = browse_cache.enrich_top250(
        service_data_dir, service_data_dir / 'covers', [row], [], [],
        ScrapeSettings(), Context(),
    )
    assert result == {'ratings': 1, 'plots': 1, 'posters': 1}
    assert row.rating == 8.1
    assert row.plot == '缓存简介'
    assert row.poster_url == 'https://image.tmdb.org/t/p/w342/alternate.jpg'


def test_parse_subject_page_cleans_douban_summary():
    from movie_service.discovery import parse_subject_page
    page = '''<span property="v:itemreviewed">八仙！</span>
    <span property="v:summary">　　A &amp; B。<br>下一段</span>'''
    result = parse_subject_page(page, '123')
    assert result['title'] == '八仙！'
    assert result['plot'] == 'A & B。 下一段'


def test_ranking_source_timestamp_is_independent(service_data_dir):
    from scraper.douban_ranking import RankedMovie, save_ranking_cache
    path = service_data_dir / 'douban_ranking_cache.json'
    path.write_text(json.dumps({'timestamp': '2020-01-01', 'chart': [],
                              'source_timestamps': {'chart': '2020-01-01'}}))
    save_ranking_cache([RankedMovie('电影', '2020', 8, '123', 1, 'top250')], [], cache_path=path)
    assert json.loads(path.read_text())['source_timestamps']['chart'] == '2020-01-01'


def test_legacy_nested_categories_exclude_tv_and_people(service_data_dir):
    from movie_service.discovery import normalize_legacy, parse_annual
    def widget(title, did):
        return {'id': did, 'payload': {'title': title},
                'subjects': [{'id': str(did), 'title': '作品', 'rating': 8, 'type': 'movie'}]}
    legacy = {'widgets': [{'payload': {'widgets': [widget('动画片', 1), widget('动画剧集', 2), widget('最受关注导演', 3)]}}]}
    parsed = parse_annual(normalize_legacy(legacy), 2022)
    assert [c['title'] for c in parsed['categories']] == ['动画片']
    assert parsed['categories'][0]['items'][0]['year'] == ''


def test_douban_image_headers(monkeypatch):
    import io
    from wall_common import images
    class Response(io.BytesIO):
        headers = {}
    def urlopen(req, timeout):
        assert req.get_header('Referer') == 'https://movie.douban.com/'
        assert 'Mozilla/' in req.get_header('User-agent')
        return Response(b'image')
    monkeypatch.setattr(images.urllib.request, 'urlopen', urlopen)
    assert images.fetch_remote('https://img3.doubanio.com/a.jpg') == b'image'


def test_douban_chart_accepts_current_cli_rating_field(monkeypatch):
    import scraper.douban_ranking as ranking

    monkeypatch.setattr(ranking, '_run_douban_cli', lambda *args, **kwargs: [
        {'id': '123', 'title': '可能的爱', 'rating': '8.6',
         'cover': 'https://img3.doubanio.com/poster.jpg'},
        {'id': '456', 'title': '低分电影', 'rating': '5.8',
         'cover': 'https://img9.doubanio.com/low.jpg'},
    ])
    items = ranking.fetch_douban_chart(fetch_details=False)
    assert [item.title for item in items] == ['可能的爱', '低分电影']
    assert items[0].rating == 8.6
    assert items[1].rating == 5.8
    assert items[1].poster_url.endswith('/low.jpg')


def test_top250_extracts_poster(monkeypatch):
    import scraper.douban_ranking as ranking

    page = '''<li><em>1</em><img src="https://img3.doubanio.com/top.jpg">
    <div class="info"><a href="https://movie.douban.com/subject/123/">
    <span class="title">电影</span></a><span class="rating_num">9.0</span>
    <p>2025</p></div></li>'''
    monkeypatch.setattr(ranking, '_fetch_url', lambda url: page)
    items = ranking.fetch_douban_top250()
    assert items[0].poster_url == 'https://img3.doubanio.com/top.jpg'


def test_now_and_coming_keep_douban_order_and_posters(monkeypatch):
    import scraper.new_movie_checker as checker

    now = [{'id': '1', 'title': '无评分热映', 'rating': '-', 'release_date': '11.14',
            'meta': '2026 / 中国大陆 / 剧情 喜剧 / 导演 / 演员',
            'cover': 'https://img3.doubanio.com/now.jpg'}]
    coming = [{'id': '2', 'title': '即将上映', 'release_date': '11月19日',
               'types': ['剧情'], 'regions': ['中国台湾'], 'wish_count': 12}]
    monkeypatch.setattr(checker, '_run_cli', lambda *args, **kwargs: now if args[0] == 'now' else coming)
    monkeypatch.setattr(checker, '_fetch_cinema_posters', lambda segment: {
        '2': 'https://img9.doubanio.com/coming.jpg'})
    playing = checker.fetch_nowplaying()
    upcoming = checker.fetch_coming_soon()
    assert playing[0].title == '无评分热映'
    assert playing[0].poster_url.endswith('/now.jpg')
    assert playing[0].year == '2026'
    assert upcoming[0].poster_url.endswith('/coming.jpg')
    assert upcoming[0].year == '2026'


def test_cinema_page_poster_parser():
    from scraper.new_movie_checker import _parse_cinema_posters
    page = '''<div class="item mod "><a class="thumb" href="https://movie.douban.com/subject/123/">
    <img src="https://img3.doubanio.com/coming.jpg"></a></div>'''
    assert _parse_cinema_posters(page)['123'].endswith('/coming.jpg')


def test_imdb_top250_extracts_poster(monkeypatch):
    import scraper.douban_ranking as ranking

    payload = json.dumps([{
        'name': 'Movie', 'datePublished': '2025-01-01',
        'aggregateRating': {'ratingValue': 9.0, 'ratingCount': 100000},
        'url': '/title/tt1234567/',
        'image': 'https://m.media-amazon.com/images/poster.jpg',
    }])
    monkeypatch.setattr(ranking, '_fetch_url', lambda url: payload)
    items = ranking.fetch_imdb_top250()
    assert items[0].poster_url == 'https://m.media-amazon.com/images/poster.jpg'


def test_mobile_movie_retries_rate_limit(monkeypatch):
    import io
    import scraper.douban_ranking as ranking

    attempts = 0
    def urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError('temporary')
        return io.BytesIO(json.dumps({'id': '123', 'cover_url': 'https://img3.doubanio.com/a.jpg'}).encode())

    monkeypatch.setattr(ranking.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(ranking.time, 'sleep', lambda _: None)
    assert ranking._fetch_mobile_movie('123')['cover_url'].endswith('/a.jpg')
    assert attempts == 3


def test_subject_suggest_requires_exact_movie_id(monkeypatch):
    import io
    import scraper.douban_ranking as ranking

    payload = [{'id': '123', 'type': 'movie', 'title': '电影', 'year': '2026',
                'img': 'https://img3.doubanio.com/suggest.jpg'}]
    monkeypatch.setattr(ranking.urllib.request, 'urlopen',
                        lambda request, timeout: io.BytesIO(json.dumps(payload).encode()))
    assert ranking._fetch_subject_suggest('电影', '123')['cover_url'].endswith('/suggest.jpg')


def test_fetch_text_retries_transient_failure(monkeypatch):
    import io
    from movie_service import discovery

    attempts = 0
    def urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError('temporary')
        return io.BytesIO('年度数据'.encode())

    monkeypatch.setattr(discovery.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(discovery.time, 'sleep', lambda _: None)
    assert discovery.fetch_text('https://movie.douban.com/annual/2018/') == '年度数据'
    assert attempts == 2
