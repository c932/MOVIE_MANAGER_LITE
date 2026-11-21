from hashlib import sha256

from models.movie import Movie
from scraper.metadata_sources import TmdbProvider
from scraper.scrape_settings import ScrapeSettings
from utils.library_sync import atomic_json

from .test_movie_helpers import API, movie_client, wait_job


def test_series_reads_official_cache_and_matches_entire_library(service_data_dir, monkeypatch):
    from movie_service.store import MovieStore, movie_id

    name = '测试三部曲'
    first = Movie(title='本地第一部', set_name=name, nfo_path='first.nfo', tmdb_id='1', year='2001')
    second = Movie(title='本地第二部', nfo_path='second.nfo', tmdb_id='2', year='2004')
    monkeypatch.setattr(MovieStore, 'snapshot', lambda self: [first, second])
    def unexpected_get(*args):
        raise AssertionError('Cache should not call TMDB')

    monkeypatch.setattr(TmdbProvider, '_get', unexpected_get)
    def part(identity, title, year):
        return {'tmdb_id': identity, 'title': title, 'original_title': '', 'year': year,
                'premiered': f'{year}-01-01', 'rating': 7.5, 'poster_url': 'https://image.tmdb.org/t/p/w342/series.jpg'}

    path = service_data_dir / 'series_collections' / (sha256(name.encode()).hexdigest() + '.json')
    atomic_json(path, {'anchor': '1', 'fetched_at': 0, 'parts': [
        part('3', '尚未收录的第三部', '2006'), part('2', '来源第二部', '2004'), part('1', '来源第一部', '2001'),
    ]})
    monkeypatch.setenv('MML_SCRAPE_CONFIG', str(service_data_dir / 'scrape_config.json'))
    with movie_client(service_data_dir) as client:
        reply = client.get(f'{API}/discovery/series', params={'name': name})
        assert reply.status_code == 200
        result = reply.json()
        assert result['source'] == 'tmdb'
        assert [item['movie_id'] for item in result['items']] == [movie_id('first.nfo'), movie_id('second.nfo'), None]
        assert [item['title'] for item in result['items']] == ['本地第一部', '本地第二部', '尚未收录的第三部']
        assert result['items'][2]['rating'] == 7.5
        assert client.get(f'{API}/discovery/series').json() == {'groups': [result]}
        assert client.get(f'{API}/discovery/series', params={'name': '未知系列'}).status_code == 404


def test_provider_resolves_collection_from_movie_id(monkeypatch):
    provider = TmdbProvider(ScrapeSettings())
    data = {'movie/1': {'id': 1, 'belongs_to_collection': {'id': 20}},
            'collection/20': {'id': 20, 'parts': [{'id': 1, 'title': '第一部', 'vote_average': 8,
                                                   'release_date': '2001-12-19', 'poster_path': '/one.jpg'}]}}
    monkeypatch.setattr(provider, '_get', data.__getitem__)
    assert provider.movie_collection('1') == [{'tmdb_id': '1', 'title': '第一部', 'original_title': '',
        'year': '2001', 'premiered': '2001-12-19', 'plot': '', 'rating': 8.0, 'poster_url': 'https://image.tmdb.org/t/p/w342/one.jpg'}]


def test_series_refresh_fills_assets_and_preserves_previous_plot(service_data_dir, monkeypatch):
    from movie_service import browse_cache
    from movie_service.store import MovieStore

    name = '测试三部曲'
    movie = Movie(title='本地第一部', set_name=name, nfo_path='first.nfo', tmdb_id='1', year='2001',
                  poster_path='local.jpg')
    monkeypatch.setattr(MovieStore, 'snapshot', lambda self: [movie])

    def get(_self, path, **params):
        if path == 'movie/1':
            return {'id': 1, 'belongs_to_collection': {'id': 20}}
        assert path == 'collection/20'
        if params.get('language') == 'en-US':
            return {'id': 20, 'parts': [
                {'id': 1, 'title': '第一部', 'release_date': '2001-01-01', 'vote_average': 0,
                 'poster_path': '/english.jpg'},
            ]}
        return {'id': 20, 'parts': [
            {'id': 1, 'title': '第一部', 'release_date': '2001-01-01', 'vote_average': 0},
            {'id': 2, 'title': '第二部', 'release_date': '2004-01-01', 'vote_average': 7.8,
             'overview': '第二部简介', 'poster_path': '/second.jpg'},
        ]}

    monkeypatch.setattr(TmdbProvider, '_get', get)
    monkeypatch.setattr(browse_cache, 'cached_remote', lambda *args, **kwargs: service_data_dir / 'cover.img')
    atomic_json(service_data_dir / 'scrape_config.json', {'tmdb_token': 'test-token'})
    monkeypatch.setenv('MML_SCRAPE_CONFIG', str(service_data_dir / 'scrape_config.json'))

    path = service_data_dir / 'series_collections' / (sha256(name.encode()).hexdigest() + '.json')
    atomic_json(path, {'anchor': '1', 'fetched_at': 0, 'parts': [{
        'tmdb_id': '1', 'title': '旧第一部', 'original_title': '', 'year': '2001',
        'premiered': '2001-01-01', 'rating': 8.9, 'poster_url': 'https://image.tmdb.org/t/p/w342/old.jpg',
        'plot': '上次已取得的简介',
    }]})

    with movie_client(service_data_dir) as client:
        response = client.post(f'{API}/discovery/series/refresh')
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()['job_id'])
        assert job['status'] == 'done', job['error']
        assert job['result']['updated'] == 1
        assert job['result']['failed'] == 0

        groups = client.get(f'{API}/discovery/series').json()['groups']
        items = groups[0]['items']
        assert items[0]['title'] == '本地第一部'
        assert items[0]['rating'] == 8.9
        assert items[0]['poster_url'] == 'https://image.tmdb.org/t/p/w342/english.jpg'
        assert items[0]['plot'] == '上次已取得的简介'
        assert items[1]['title'] == '第二部'
        assert items[1]['rating'] == 7.8
        assert items[1]['plot'] == '第二部简介'
