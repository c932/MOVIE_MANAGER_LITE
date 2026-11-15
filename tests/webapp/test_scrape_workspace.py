from pathlib import Path
import pytest

from tests.webapp.test_movie_helpers import movie_client, wait_job, add_movie, set_movie_paths, refresh
from scraper.scrape_models import Candidate, Metadata


def post_job(client, url, data=None, expect='done'):
    response = client.post('/api/movie/scrape/' + url, json=data or {})
    assert response.status_code == 200, response.text
    result = wait_job(client, response.json()['job_id'])
    assert result['status'] == expect, result
    return result['result'] if expect == 'done' else result['error']


@pytest.fixture
def fake_sources(monkeypatch):
    from scraper.scrape_service import ScrapeService
    monkeypatch.setattr(ScrapeService, 'search', lambda self, source, query, year='', page=1: [Candidate(source, '99', query, year=year)])
    monkeypatch.setattr(ScrapeService, 'details', lambda self, candidate: Metadata(candidate.source, '99',
        fields={'title': candidate.title, 'year': '2016', 'plot': candidate.source + ' 剧情', 'set_name': '测试系列'},
        ids={'tmdb':'99', 'imdb':'tt1234567', 'douban':'1234567'}, ratings={'douban':7.7,'tmdb':6.6,'imdb':5.5}))
    monkeypatch.setattr(ScrapeService, 'enrich_metadata', lambda self, metadata: metadata)
    monkeypatch.setattr(ScrapeService, 'automatic_tmdb_metadata', lambda *a: [])
    monkeypatch.setattr(ScrapeService, 'automatic_douban_metadata', lambda *a: [])


def prepare(client, root):
    set_movie_paths(client, [root])
    post_job(client, 'workspace/scan')
    return client.get('/api/movie/scrape/workspace').json()['rows'][0]['id']


def draft(client, tid):
    candidates = post_job(client, 'search', {'source':'douban','query':'测试新电影','year':'2016'})
    return post_job(client, 'preview', {'target_id':tid,'candidate':candidates[0]['token']})


def confirm(client, view):
    return post_job(client, f"sessions/{view['session']}/confirm", {'title':view['fields']['title'],
        'plot':view['fields']['plot'], 'plot_source':'douban'})


def test_discovery_three_ratings_confirmation_save_and_readback(service_data_dir, fake_sources):
    root = service_data_dir / 'media'
    root.mkdir()
    (root / 'new.2016.mkv').write_bytes(b'video')
    with movie_client(service_data_dir) as client:
        tid = prepare(client, root)
        view = draft(client, tid)
        assert view['fields']['ratings'] == {'douban':7.7,'tmdb':6.6,'imdb':5.5}
        assert view['plot_source'] == 'douban'
        payload = {'selected_fields':['title','year','plot','ratings','uniqueids','set_name'], 'metadata_only':True}
        assert '确认' in post_job(client, f"sessions/{view['session']}/save", payload, 'error')
        confirm(client, view)
        saved = post_job(client, f"sessions/{view['session']}/save", payload)
        assert saved['set_name'] == '测试系列'
        assert saved['ratings'] == view['fields']['ratings']
        assert Path(saved['nfo_path']).is_file()
        assert client.get('/api/movie/movies/' + saved['id']).json()['ratings'] == saved['ratings']
        assert '重复' in post_job(client, f"sessions/{view['session']}/save", payload, 'error')
        assert not client.get('/api/movie/scrape/workspace').json()['rows'][0]['is_new']


def test_conflicting_nfo_is_preserved_and_editor_changes_only_dirty_fields(service_data_dir, fake_sources):
    root = service_data_dir / 'media'
    nfo = add_movie(root, 'film', title='原电影', ratings=(('douban',8),('rottentomatoes',91)))
    with movie_client(service_data_dir) as client:
        tid = prepare(client, root)
        edit = post_job(client, 'edit/' + tid)
        before = nfo.read_bytes()
        saved = post_job(client, f"edit/sessions/{edit['session']}/save", {'changes':{'title':'已编辑'}})
        assert saved['title'] == '已编辑' and saved['ratings']['rottentomatoes'] == 91
        assert any(p.read_bytes() == before for p in root.glob('*.mml-backup-*'))
        view = confirm(client, draft(client, tid))
        nfo.write_text(nfo.read_text(encoding='utf8').replace('已编辑','外部编辑'), encoding='utf8')
        external = nfo.read_bytes()
        error = post_job(client, f"sessions/{view['session']}/save", {'selected_fields':['title'],'metadata_only':True,'replace_identity_ack':True}, 'error')
        assert '改变' in error or '冲突' in error
        assert nfo.read_bytes() == external


def test_settings_secrets_hidden_and_unknown_candidate_rejected(service_data_dir):
    root = service_data_dir / 'media'
    add_movie(root, 'movie', title='原电影')
    with movie_client(service_data_dir) as client:
        tid = prepare(client, root)
        assert client.put('/api/movie/scrape/settings',json={'tmdb_api_key':'test-private-token'}).status_code == 200
        client.put('/api/movie/scrape/settings',json={'tmdb_api_key':''})
        settings = client.get('/api/movie/scrape/settings').json()
        assert settings['has_tmdb_api_key'] and 'test-private-token' not in str(settings)
        assert '过期' in post_job(client, 'preview', {'target_id':tid,'candidate':'invented'}, 'error')
