from io import BytesIO
from fastapi.testclient import TestClient
from PIL import Image
from utils.library_sync import movie_key


def test_shared_database_web_state_poster_and_restart(service_data_dir):
    from movie_service.main import create
    app = create(str(service_data_dir))
    record = dict(nfo_path=r'\\nas\movie\Film.nfo', title='共享电影', ratings={'tmdb': 7, 'imdb': 8, 'douban': 9},
                  poster_path=r'\\nas\movie\poster.jpg', set_name='系列', actors=[], countries=['United States of America'])
    mid = movie_key(record['nfo_path'])
    with TestClient(app) as client:
        assert client.post('/api/movie/sync/push', json={'changes': [{'id': mid, 'data': record}]}).status_code == 200
        movies = client.get('/api/movie/movies').json()['movies']
        assert movies[0]['ratings'] == record['ratings']
        assert movies[0]['countries'] == ['美国']
        assert client.post(f'/api/movie/movies/{mid}/favorite', json={'favorite': True}).status_code == 200
        assert client.post(f'/api/movie/movies/{mid}/watched', json={'watched': True}).status_code == 200
        assert client.put(f'/api/movie/movies/{mid}/rating', json={'rating': 9}).status_code == 200
        changed = client.get('/api/movie/sync/changes').json()['records'][0]['data']
        assert changed['_favorite'] and changed['watched'] and changed['ratings']['user'] == 9
        buf = BytesIO()
        Image.new('RGB', (280, 420), 'red').save(buf, 'JPEG')
        assert client.put(f'/api/movie/sync/assets/{mid}', content=buf.getvalue()).status_code == 200
        assert client.get(f'/api/movie/movies/{mid}/poster').status_code == 200
        old_hash = client.get('/api/movie/sync/assets').json()[mid]
        buf = BytesIO()
        Image.new('RGB', (280, 420), 'blue').save(buf, 'JPEG')
        assert client.put(f'/api/movie/sync/assets/{mid}', content=buf.getvalue()).status_code == 409
        assert client.put(f'/api/movie/sync/assets/{mid}', content=buf.getvalue(), headers={'If-Match': old_hash}).status_code == 200
    with TestClient(create(str(service_data_dir))) as client:
        detail = client.get(f'/api/movie/movies/{mid}').json()
        assert detail['watched'] and detail['favorite'] and detail['ratings']['user'] == 9
        assert client.get(f'/api/movie/movies/{mid}/poster').status_code == 200


def test_sync_rejects_wrong_identity_and_server(service_data_dir):
    from movie_service.main import create
    with TestClient(create(str(service_data_dir))) as client:
        assert client.post('/api/movie/sync/push', json={'server_id': 'wrong', 'changes': []}).status_code == 409
        assert client.post('/api/movie/sync/push', json={'changes': [{'id': '0' * 16, 'data': {'nfo_path': '/film.nfo'}}]}).status_code == 422
        for bad in ({'actors': [{'name': []}]}, {'ratings': {'tmdb': 'bad'}}, {'api_key': 'must-not-store'}):
            data = dict(nfo_path='/film.nfo', **bad)
            response = client.post('/api/movie/sync/push', json={'changes': [{'id': movie_key('/film.nfo'), 'data': data}]})
            assert response.status_code == 422
        assert client.get('/api/movie/movies').json()['total'] == 0
