from fastapi.testclient import TestClient
from utils.library_sync import movie_key
from utils.sync_client import SyncClient, apply_patches


def wire(client):
    def request(method, path, body=None, headers=None):
        options = {'headers': headers or {}}
        if isinstance(body, bytes):
            options['content'] = body
        elif body is not None:
            options['json'] = body
        response = client.request(method, '/api/movie' + path, **options)
        if response.status_code >= 400:
            raise ValueError(response.text)
        return response.json() if 'json' in response.headers.get('content-type', '') else response.content
    return request


def test_two_clients_modes_conflicts_and_deletion(service_data_dir, tmp_path):
    from movie_service.main import create
    with TestClient(create(str(service_data_dir))) as server:
        a = SyncClient('http://server', tmp_path / 'a', wire(server))
        b = SyncClient('http://server', tmp_path / 'b', wire(server))
        path = r'\\nas\movie\Film.nfo'
        mid = movie_key(path)
        movies_a = {mid: {'nfo_path': path, 'title': '电影', 'year': '2016'}}
        a.commit(a.exchange(movies_a, 'upload'))
        got = b.exchange({}, 'download')
        movies_b = apply_patches({}, got['patches'])
        b.commit(got)
        assert movies_b == movies_a
        movies_a[mid]['title'] = 'A新标题'
        a.commit(a.exchange(movies_a, 'upload'))
        movies_b[mid]['title'] = 'B冲突标题'
        movies_b[mid]['year'] = '2017'
        got = b.exchange(movies_b, 'both')
        assert got['conflicts']
        movies_b = apply_patches(movies_b, got['patches'])
        b.commit(got)
        assert movies_b[mid]['title'] == 'A新标题' and movies_b[mid]['year'] == '2017'
        got = a.exchange(movies_a, 'download')
        movies_a = apply_patches(movies_a, got['patches'])
        a.commit(got)
        a.commit(a.exchange({}, 'upload', deleted_ids={mid}))
        got = b.exchange(movies_b, 'download')
        assert apply_patches(movies_b, got['patches']) == {}


def test_download_never_writes_upload_never_applies(service_data_dir, tmp_path):
    from movie_service.main import create
    with TestClient(create(str(service_data_dir))) as server:
        calls = []
        actual = wire(server)
        def transport(method, path, *args):
            calls.append(method)
            return actual(method, path, *args)
        client = SyncClient('http://server', tmp_path / 'client', transport)
        assert not client.exchange({}, 'download')['patches']
        assert calls and all(method == 'GET' for method in calls)
        path = '//nas/film.nfo'
        record = {movie_key(path): {'nfo_path': path, 'title': '仅上传'}}
        assert client.exchange(record, 'upload')['patches'] == []
        assert len(server.get('/api/movie/movies').json()['movies']) == 1
        client.commit(client.exchange(record, 'both'))
        # 现有客户端本机缓存丢失也不能误删共享库。
        assert not client.exchange({}, 'upload')['uploaded']
        assert len(server.get('/api/movie/movies').json()['movies']) == 1
        restored = client.exchange({}, 'download')
        assert apply_patches({}, restored['patches']) == record


def test_inflight_local_edits_survive_download():
    before = {'title': '旧标题', 'year': '2016'}
    patches = [{'id': 'a', 'before': before, 'deleted': False, 'data': {'title': '远程标题', 'year': '2017'}}]
    got = apply_patches({'a': dict(before, title='用户刚编辑')}, patches)
    assert got == {'a': {'title': '用户刚编辑', 'year': '2017'}}


def test_downloaded_poster_recompression_does_not_upload_again(service_data_dir, tmp_path):
    from movie_service.main import create
    from io import BytesIO
    from PIL import Image
    path = '//nas/film.nfo'
    mid = movie_key(path)
    records = {mid: {'nfo_path': path, 'title': '海报', 'poster_path': '//nas/poster.jpg'}}
    original = BytesIO()
    Image.new('RGB', (280, 420), 'red').save(original, 'JPEG', quality=95)
    with TestClient(create(str(service_data_dir))) as server:
        a = SyncClient('http://server', tmp_path / 'a', wire(server))
        a.commit(a.exchange(records, 'upload', load_asset=lambda *a: original.getvalue()))
        remote_hash = server.get('/api/movie/sync/assets').json()[mid]
        local = {}
        def save(mid, path, payload):
            converted = BytesIO()
            with Image.open(BytesIO(payload)) as image:
                image.save(converted, 'JPEG', quality=70)
            local[mid] = converted.getvalue()
        b = SyncClient('http://server', tmp_path / 'b', wire(server))
        got = b.exchange({}, 'download', load_asset=lambda mid, path: local.get(mid), save_asset=save)
        movies = apply_patches({}, got['patches'])
        b.commit(got)
        got = b.exchange(movies, 'both', load_asset=lambda mid, path: local.get(mid), save_asset=save)
        assert not got['asset_errors'] and not got['asset_downloaded']
        assert server.get('/api/movie/sync/assets').json()[mid] == remote_hash
