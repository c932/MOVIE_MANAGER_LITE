from pathlib import Path
import importlib.util
import json
import threading

import pytest

from utils.library_sync import atomic_json, movie_key
from tests.webapp.test_movie_helpers import movie_client, wait_job, add_movie, refresh


@pytest.fixture
def helper(tmp_path):
    spec = importlib.util.spec_from_file_location('nas_helper_test', Path(__file__).resolve().parents[2] / 'deploy/nas_helper.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.NASHelper.__new__(module.NASHelper)
    helper.state_dir, helper.mount_root, helper.runtime_dir = (tmp_path / name for name in ('state', 'mounts', 'run'))
    for path in (helper.state_dir, helper.mount_root, helper.runtime_dir):
        path.mkdir()
    helper.uid = helper.gid = 1000
    helper.config, helper.errors, helper.lock = helper.state_dir / 'connections.json', {}, threading.RLock()
    return helper


def test_helper_rejects_injection_keeps_password_out_of_commands_and_response(helper, monkeypatch):
    config = {'host': '192.168.50.100', 'share': 'Movie Series', 'username': 'reader', 'password': 'a,b=Secret'}
    for changes in ({'host': '127.0.0.1;touch /bad'}, {'share': '../etc'}, {'password': 'x\nusername=root'}):
        with pytest.raises(ValueError):
            helper.spec(dict(config, **changes))
    commands = []
    def command(args, password='', timeout=20):
        commands.append(args)
        assert config['password'] not in str(args)
        credential = next(helper.runtime_dir.glob('*.cred'))
        assert config['password'] in credential.read_text(encoding='utf-8')
        return ''
    monkeypatch.setattr(helper, 'command', command)
    result = helper.handle({'action': 'connect', 'config': config})
    assert config['password'] not in json.dumps(result)
    assert result['has_password'] and result['read_only']
    assert 'ro,nosuid,nodev,noexec' in commands[0][-1]
    assert not list(helper.runtime_dir.glob('*.cred'))
    assert helper.spec(dict(config, password=''))['password'] == config['password']
    with pytest.raises(ValueError):
        helper.target('../../outside')


@pytest.fixture
def nas_rpc(tmp_path, monkeypatch):
    from movie_service.nas import NASManager
    root = tmp_path / 'mount'
    root.mkdir()
    (root / 'Films').mkdir()
    state = {'connections': [{'id': 'a' * 16, 'host': '192.168.50.100', 'share': 'movie',
                              'mount_path': str(root), 'read_only': True, 'connected': True, 'mounted': True,
                              'enabled': True, 'username': 'reader', 'domain': '', 'guest': False, 'port': 445,
                              'vers': '3.0', 'has_password': True, 'error': ''}]}
    def rpc(self, request):
        if request['action'] == 'status':
            return state
        if request['action'] == 'shares':
            if request['config'].get('password') == 'wrong-secret':
                raise ValueError('NAS 登录失败，请检查用户名或密码')
            return {'shares': ['movie', 'Movie Series']}
        if request['action'] == 'connect':
            return state['connections'][0]
        if request['action'] == 'disconnect':
            state['connections'][0]['connected'] = False
            return {'disconnected': True}
        raise AssertionError(request)
    monkeypatch.setattr(NASManager, '_rpc', rpc)
    return root, state


def test_nas_settings_login_browse_and_scan_keep_unc_identity(service_data_dir, nas_rpc):
    root, state = nas_rpc
    nfo = add_movie(root / 'Films' / 'A', 'A', title='NAS新标题')
    canonical = r'\\192.168.50.100\movie\Films\A\A.nfo'
    from movie_service.nas import NASPaths
    with movie_client(service_data_dir) as client:
        status = client.get('/api/movie/system/info').json()
        assert status['nas_connected'] and status['nas_connected_count'] == 1
        assert not status['source_available'] and status['nas_library_count'] == 0
        response = client.post('/api/movie/nas/shares', json={'host': '192.168.50.100', 'username': 'reader', 'password': 'secret'})
        assert wait_job(client, response.json()['job_id'])['result']['shares'] == ['movie', 'Movie Series']
        failed = client.post('/api/movie/nas/shares', json={'host': '192.168.50.100', 'username': 'reader', 'password': 'wrong-secret'})
        job = wait_job(client, failed.json()['job_id'])
        assert job['status'] == 'error' and 'wrong-secret' not in json.dumps(job)
        assert client.get('/api/movie/nas/' + 'a' * 16 + '/directories').json()['directories'][0]['name'] == 'Films'
        assert client.get('/api/movie/nas/' + 'a' * 16 + '/directories', params={'path': '../'}).status_code == 400
        selected = [{'connection_id': 'a' * 16, 'path': 'Films'}]
        assert client.put('/api/movie/nas/libraries', json={'libraries': selected}).status_code == 200
        mapper = NASPaths(service_data_dir)
        assert mapper.canonical(str(nfo)) == canonical
        assert mapper.source(canonical) == str(nfo)
        assert client.get('/api/movie/system/info').json()['source_available']
        assert client.get('/api/movie/system/info').json()['nas_library_count'] == 1
        original = {'nfo_path': canonical, 'title': '原电影', 'added_time': 123, 'watched': True}
        outside = {'nfo_path': r'\\192.168.50.100\Movie Series\Other.nfo', 'title': '其他共享电影'}
        assert client.post('/api/movie/sync/push', json={'changes': [
            {'id': movie_key(item['nfo_path']), 'data': item} for item in (original, outside)]}).status_code == 200
        job = refresh(client, force=False)
        assert job['status'] == 'done'
        movies = client.get('/api/movie/movies').json()['movies']
        assert len(movies) == 2, '仅扫描一个目录不能删除其他共享中的电影'
        movie = next(item for item in movies if item['id'] == movie_key(canonical))
        assert movie['title'] == 'NAS新标题' and movie['nfo_path'] == canonical
        assert movie['added_time'] == 123 and movie['watched']
        assert client.post(f"/api/movie/movies/{movie['id']}/reparse").status_code == 200
        assert client.get(f"/api/movie/movies/{movie['id']}/nfo").status_code == 200
        assert client.get(f"/api/movie/movies/{movie['id']}/poster").status_code == 200
        assert 'secret' not in (service_data_dir / 'nas_libraries.json').read_text(encoding='utf-8')
        state['connections'][0]['connected'] = False
        assert not client.get('/api/movie/system/info').json()['source_available']
        assert refresh(client, force=False, expect='error')['error']
        assert client.get('/api/movie/movies').json()['total'] == 2


def test_nas_cannot_configure_directory_from_disconnected_share(service_data_dir, nas_rpc):
    root, state = nas_rpc
    state['connections'][0]['connected'] = False
    with movie_client(service_data_dir) as client:
        response = client.put('/api/movie/nas/libraries', json={'libraries': [{'connection_id': 'a' * 16, 'path': ''}]})
        assert response.status_code == 400
        assert client.get('/api/movie/settings').json()['movie_paths'] == []
