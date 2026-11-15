import pytest

from models.movie import Movie
from movie_service.store import movie_id
from tests.webapp.test_movie_helpers import movie_client


def test_playlist_preserves_utf8_unc_without_nas_read_or_write(service_data_dir):
    path = r'\\192.168.50.100\Movie Series\中文 空格 & 系列\电影.mkv'
    nfo = r'\\192.168.50.100\Movie Series\中文 空格 & 系列\电影.nfo'
    with movie_client(service_data_dir) as client:
        client.get('/api/movie/movies')
        client.app.state.store.replace_all([Movie(title='中文电影\n禁止注入', nfo_path=nfo, video_path=path)])
        response = client.get('/api/movie/movies/' + movie_id(nfo) + '/playlist.m3u8')
        assert response.status_code == 200
        assert response.content.decode('utf-8').splitlines() == ['#EXTM3U', '#EXTINF:-1,中文电影禁止注入', path]
        assert response.headers['cache-control'] == 'no-store'
        assert "filename*=UTF-8''" in response.headers['content-disposition']
        assert 'attachment;' in response.headers['content-disposition']
        assert client.get('/api/movie/movies').json()['total'] == 1


@pytest.mark.parametrize('path', ['', '/mnt/media/film.mkv', 'relative.mkv', r'C:\film.exe', '\\\\nas\\share\\film.mkv\n#EXTINF:1,other'])
def test_playlist_rejects_invalid_paths_and_injected_entries(service_data_dir, path):
    nfo = r'\\nas\share\film.nfo'
    with movie_client(service_data_dir) as client:
        client.get('/api/movie/movies')
        client.app.state.store.replace_all([Movie(title='电影', nfo_path=nfo, video_path=path)])
        response = client.get('/api/movie/movies/' + movie_id(nfo) + '/playlist.m3u8')
        assert response.status_code == 400
        assert '路径' in response.json()['detail']
