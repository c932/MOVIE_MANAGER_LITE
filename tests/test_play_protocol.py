from urllib.parse import quote
import pytest
from utils.play_protocol import play_url, video_path_from_url


def test_plays_exact_unc_path_without_shell():
    path = r'\\192.168.50.100\movie\中文 电影 & test\Film.mkv'
    url = 'moviewall://play?path=' + quote(path, safe='')
    calls = []
    play_url(url, opener=calls.append)
    assert calls == [path]


@pytest.mark.parametrize('path', ['relative.mkv', r'C:film.mkv', r'\\?\C:\film.mkv', r'C:\test.exe', 'C:\\film.mkv\n', '/tmp/film.mkv'])
def test_rejects_unsafe_or_nonvideo_paths(path):
    with pytest.raises(ValueError):
        video_path_from_url('moviewall://play?path=' + quote(path, safe=''))
