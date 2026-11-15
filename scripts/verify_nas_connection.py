"""NUC 专用：针对临时 SMB 共享和独立 API 数据目录的真实只读挂载验收。"""
from pathlib import Path
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp/backend'))


if __name__ == '__main__':
    from PIL import Image
    from movie_service.nas import NASManager
    from utils.library_sync import movie_key
    config = json.loads(Path('/tmp/mml-smb-test/test-login.json').read_text(encoding='utf-8'))
    assert config['host'] == '127.0.0.1' and config['port'] == 1445 and config['share'] == 'MMLTest'
    Image.new('RGB', (600, 900), 'red').save('/tmp/mml-smb-test/share/Films/TestFilm/poster.jpg')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request('http://127.0.0.1:18011/api/movie' + path, data=data,
                                     method=method, headers={'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=30) as response:
                value = response.read()
                return json.loads(value) if 'json' in response.headers.get('Content-Type', '') else value
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode('utf-8', errors='replace')) from exc
    def wait(job, expected='done'):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            result = request('GET', '/jobs/' + job['job_id'])
            if result['status'] in {'done', 'error', 'cancelled'}:
                assert result['status'] == expected, result.get('error')
                return result['result']
            time.sleep(.2)
        raise TimeoutError('NAS 验收任务超时')
    mid = None
    deadline = time.monotonic() + 10
    while True:
        try:
            if request('GET', '/nas')['available']:
                break
        except urllib.error.URLError:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError('NAS 连接助手未就绪')
        time.sleep(.2)
    try:
        assert 'mmltest' in [name.casefold() for name in wait(request('POST', '/nas/shares', config))['shares']]
        print('SMB login and share listing: PASS', flush=True)
        connection = wait(request('POST', '/nas/connect', config))
        mid = connection['id']
        assert connection['connected'] and connection['mounted'] and connection['read_only']
        probe = Path(connection['mount_path']) / 'write-probe.txt'
        try:
            probe.write_text('must fail', encoding='utf-8')
        except OSError:
            pass
        else:
            probe.unlink()
            raise AssertionError('测试挂载不是只读')
        print('Real CIFS mount and denied writes: PASS', flush=True)
        assert 'Films' in [item['name'] for item in request('GET', f'/nas/{mid}/directories')['directories']]
        request('PUT', '/nas/libraries', {'libraries': [{'connection_id': mid, 'path': 'Films'}]})
        assert request('GET', '/system/info')['source_available']
        canonical = r'\\127.0.0.1\MMLTest\Films\TestFilm\TestFilm.nfo'
        mid_movie = movie_key(canonical)
        records = [{'nfo_path': canonical, 'title': '旧标题', 'watched': True, 'added_time': 123,
                    'ratings': {'tomatometerallcritics': 91}},
                   {'nfo_path': '//other-nas/other/film.nfo', 'title': '未扫描目录的电影'}]
        request('POST', '/sync/push', {'changes': [{'id': movie_key(item['nfo_path']), 'data': item} for item in records]})
        assert not wait(request('POST', '/library/refresh', {'force': False}))['poster_errors']
        movies = request('GET', '/movies')['movies']
        assert len(movies) == 2
        movie = request('GET', '/movies/' + mid_movie)
        assert movie['title'] == 'NAS只读扫描验收' and movie['added_time'] == 123 and movie['watched']
        assert len(request('GET', f'/movies/{mid_movie}/poster')) > 100
        assert 'NAS只读扫描验收' in request('GET', f'/movies/{mid_movie}/nfo')['xml']
        print('Directory selection, stable UNC identity, scan and poster: PASS', flush=True)
        wait(request('POST', f'/nas/{mid}/disconnect'))
        assert not request('GET', '/system/info')['source_available']
        assert len(request('GET', f'/movies/{mid_movie}/poster')) > 100
        wait(request('POST', '/library/refresh', {'force': False}), expected='error')
        assert request('GET', '/movies')['total'] == 2
        print('Disconnect, offline poster and database protection: PASS', flush=True)
    finally:
        if mid:
            NASManager(Path('/tmp/mml-nas-e2e-data')).transport({'action': 'forget', 'id': mid})
