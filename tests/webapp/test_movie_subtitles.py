import xml.etree.ElementTree as ET

from tests.test_subtitles import SRT
from tests.webapp.test_movie_helpers import (
    API, build_library, find_movie, movie_client, prepare_library, wait_job,
)


def test_import_save_sync_matches_nfo_and_shared_database(service_data_dir):
    library = build_library(service_data_dir / 'library')
    with movie_client(service_data_dir) as client:
        prepare_library(client, library['root'])
        movie = find_movie(client, '电锯惊魂')
        endpoint = f'{API}/movies/{movie["id"]}/subtitles'
        draft = client.post(f'{endpoint}/import', files={'file': ('caption.srt', SRT)}).json()
        assert draft['tracks'] == [{'name': 'caption.srt', 'language': 'zh-Hans'}]
        assert not library['saw'].with_suffix('.srt').exists()
        other = find_movie(client, '疯狂动物城')
        selection = {'token': draft['token'], 'index': 0, 'language': 'zh-Hans'}
        assert client.post(f'{API}/movies/{other["id"]}/subtitles/save', json=selection).status_code == 409
        response = client.post(f'{endpoint}/save', json=selection)
        job = wait_job(client, response.json()['job_id'])
        assert job['status'] == 'done', job
        tracks = [{'file': 'Saw.srt', 'language': 'zh-Hans'}]
        assert job['result']['movie']['subtitles'] == tracks
        assert find_movie(client, '电锯惊魂')['subtitles'] == tracks
        record = next(item for item in client.get(f'{API}/sync/changes').json()['records']
                      if item['id'] == movie['id'])
        assert record['data']['subtitles'] == tracks
        nfo = library['saw']
        assert ET.parse(nfo).findtext('mmlsubtitles/subtitle/language') == 'zh-Hans'
        nfo.with_suffix('.srt').unlink()
        job = wait_job(client, client.post(f'{endpoint}/sync').json()['job_id'])
        assert job['status'] == 'done', job
        assert job['result']['movie']['subtitles'] == []
        assert ET.parse(nfo).find('mmlsubtitles/subtitle') is None


def test_download_returns_original_verification_page(service_data_dir, monkeypatch):
    from movie_service import routes_subtitles
    from utils.subtitle_sources import SiteCheck

    def verify(*_args):
        raise SiteCheck('网站要求验证')

    monkeypatch.setattr(routes_subtitles, 'download_subtitles', verify)
    library = build_library(service_data_dir / 'library')
    with movie_client(service_data_dir) as client:
        prepare_library(client, library['root'])
        movie = find_movie(client, '电锯惊魂')
        endpoint = f'{API}/movies/{movie["id"]}/subtitles/download'
        result = client.post(endpoint, json={'source': 'subhd', 'id': 'movie12'}).json()
        assert result == {'verification_url': 'https://subhdtw.com/a/movie12', 'message': '网站要求验证'}
        result = client.post(endpoint, json={'source': 'subhd', 'id': 'https://example.com/'})
        assert result.status_code == 400
