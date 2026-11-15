import threading
import pytest

from PyQt6.QtGui import QImage, QPixmap
from models.movie import Movie
from tests.scraping.test_main_integration import qt_window, _wait


def test_update_nfo_reads_latest_source_in_background(qt_window, tmp_path, monkeypatch):
    from parsers.nfo_parser import NFOParser
    app, window = qt_window
    video = tmp_path / 'Film.mkv'
    video.touch()
    nfo = video.with_suffix('.nfo')
    nfo.write_text('<movie><title>NAS最新标题</title><ratings><rating name="user">'
                   '<value>9</value></rating></ratings></movie>', encoding='utf-8')
    movie = Movie(title='旧缓存标题', nfo_path=str(nfo), video_path=str(video), added_time=123)
    window.all_movies = [movie]
    original = NFOParser.parse
    threads = []
    def parse(*args, **kwargs):
        threads.append(threading.current_thread())
        assert threading.current_thread() is not threading.main_thread(), 'NAS 读取不能阻塞 UI'
        return original(*args, **kwargs)
    monkeypatch.setattr(NFOParser, 'parse', staticmethod(parse))
    window._menu_refresh_movie_from_nfo(movie)
    _wait(app, lambda: not window._scrape_refresh_runner.busy)
    assert threads and movie.title == 'NAS最新标题'
    assert movie.ratings['user'] == 9 and movie.added_time == 123


def test_update_poster_forces_source_even_if_started_offline(qt_window, tmp_path, monkeypatch):
    from utils.poster_cache_manager import PosterCacheManager
    from utils import network_mode
    app, window = qt_window
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'posters')
    monkeypatch.setattr(network_mode, '_OFFLINE_CACHE_ONLY', True)
    poster = tmp_path / 'poster.jpg'
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    image.save(str(poster))
    cache = PosterCacheManager()
    assert cache.refresh_from_source(str(poster))
    image.fill(0x0000FF)
    image.save(str(poster))
    window._poster_cache_manager = cache
    movie = Movie(title='电影', poster_path=str(poster), nfo_path=str(tmp_path / 'Film.nfo'))
    window.all_movies = window.filtered_movies = [movie]
    window.refresh_poster_wall()
    card = window.movie_cards[0]
    old_display = QImage(200, 300, QImage.Format.Format_RGB32)
    old_display.fill(0xFF0000)
    card._set_poster_pixmap(QPixmap.fromImage(old_display))
    card._poster_loaded = True
    window._menu_refresh_movie_poster(movie)
    runner = getattr(window, '_scrape_refresh_runner', None)
    if runner:
        _wait(app, lambda: not runner.busy)
    fresh = cache.get_cached_image(str(poster), 280, 420)
    assert fresh is not None
    assert fresh.pixelColor(10, 10).blue() > 240 and fresh.pixelColor(10, 10).red() < 10
    assert card.poster_label.pixmap().toImage().pixelColor(10, 10).blue() > 240


def test_failed_source_poster_refresh_keeps_existing_cache(qt_window, tmp_path, monkeypatch):
    from utils.poster_cache_manager import PosterCacheManager
    app, window = qt_window
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'posters')
    poster = tmp_path / 'poster.jpg'
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    image.save(str(poster))
    cache = PosterCacheManager()
    assert cache.refresh_from_source(str(poster))
    poster.unlink()
    window._poster_cache_manager = cache
    window._menu_refresh_movie_poster(Movie(title='电影', poster_path=str(poster)))
    runner = getattr(window, '_scrape_refresh_runner', None)
    if runner:
        _wait(app, lambda: not runner.busy)
    existing = cache.get_cached_image(str(poster), 280, 420)
    assert existing is not None and existing.pixelColor(10, 10).red() > 240
    assert '失败' in window.status_label.text()


@pytest.mark.parametrize('had_old_poster', [True, False])
def test_update_poster_rereads_current_nfo_artwork_reference(qt_window, tmp_path, monkeypatch, had_old_poster):
    from utils.poster_cache_manager import PosterCacheManager
    from PyQt6.QtWidgets import QMessageBox
    app, window = qt_window
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'posters')
    video = tmp_path / 'Film.mkv'
    video.touch()
    nfo = video.with_suffix('.nfo')
    nfo.write_text('<movie><title>电影</title><thumb aspect="poster">new-poster.jpg</thumb></movie>', encoding='utf-8')
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    old = tmp_path / 'old-poster.jpg'
    image.save(str(old))
    image.fill(0x0000FF)
    new = tmp_path / 'new-poster.jpg'
    image.save(str(new))
    cache = PosterCacheManager()
    cache.refresh_from_source(str(old))
    window._poster_cache_manager = cache
    movie = Movie(title='旧缓存资料', video_path=str(video), nfo_path=str(nfo), poster_path=str(old) if had_old_poster else '')
    window.all_movies = [movie]
    window._menu_refresh_movie_poster(movie)
    runner = getattr(window, '_scrape_refresh_runner', None)
    if runner:
        _wait(app, lambda: not runner.busy)
    assert movie.poster_path == str(new)
    assert movie.title == '旧缓存资料', '更新海报只更新图片关联，不覆盖其他字段'
    cached = cache.get_cached_image(str(new), 280, 420)
    assert cached is not None and cached.pixelColor(10, 10).blue() > 240


def test_failed_nfo_source_keeps_local_metadata(qt_window, tmp_path):
    app, window = qt_window
    movie = Movie(title='保留旧资料', nfo_path=str(tmp_path / 'unreachable.nfo'), video_path=str(tmp_path / 'Film.mkv'))
    window.all_movies = [movie]
    window._menu_refresh_movie_from_nfo(movie)
    _wait(app, lambda: not window._scrape_refresh_runner.busy)
    assert window.all_movies == [movie] and movie.title == '保留旧资料'
    assert '失败' in window.status_label.text()
