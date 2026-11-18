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
    monkeypatch.setattr('scraper.douban_cli.get_movie_detail', lambda did: {'id': did, 'title': '电影', 'summary': '真实简介'})
    with movie_client(service_data_dir) as client:
        assert client.get('/api/movie/discovery/annual/2025').json()['categories'] == []
        job = wait_job(client, client.post('/api/movie/discovery/annual/2025/refresh').json()['job_id'])
        assert job['status'] == 'done', job
        body = client.get('/api/movie/discovery/annual/2025').json()
        assert body['categories'][0]['items'][0]['title'] == '电影'
        assert len(calls) == 2
        job = wait_job(client, client.post('/api/movie/discovery/subject/123').json()['job_id'])
        assert job['result']['plot'] == '真实简介'
        assert client.get('/api/movie/movies').json()['movies'] == []
        assert client.post('/api/movie/discovery/subject/not-id').status_code == 400


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

    monkeypatch.setattr(ranking, '_run_douban_cli', lambda *args, **kwargs: [{
        'id': '123', 'title': '可能的爱', 'rating': '8.6',
        'cover': 'https://img3.doubanio.com/poster.jpg',
    }])
    items = ranking.fetch_douban_chart(fetch_details=False)
    assert len(items) == 1
    assert items[0].rating == 8.6
