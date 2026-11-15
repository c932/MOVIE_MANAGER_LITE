from models.movie import Movie
from tests.scraping.test_main_integration import qt_window, _wait
from utils.library_sync import movie_key, read_json
from utils.sync_client import SyncClient


def test_download_updates_wall_without_scan_and_keeps_inflight_edits(qt_window, tmp_path, monkeypatch):
    app, window = qt_window
    movie = Movie(nfo_path=str(tmp_path / 'Film.nfo'), title='本机刚编辑', year='2016')
    window.all_movies = [movie]
    mid = movie_key(movie.nfo_path)
    current = window._library_sync.snapshot()[mid]
    before = dict(current, title='旧标题')
    after = dict(before, title='服务器标题', year='2017', watched=True, _favorite=True)
    client = SyncClient('http://server', tmp_path)
    result = {'patches': [{'id': mid, 'data': after, 'before': before, 'deleted': False}],
              'state': {'base': {mid: after}}, 'uploaded': 0, 'downloaded': 1, 'conflicts': [], 'asset_errors': []}
    monkeypatch.setattr(window, 'start_scan', lambda *a, **k: (_ for _ in ()).throw(AssertionError('同步不能扫描 NAS')))
    window._library_sync._result('sync', 1, (client, result))
    _wait(app, lambda: not window._library_sync.runner.busy)
    assert movie.title == '本机刚编辑' and movie.year == '2017'
    assert window.watch_history.is_watched(movie.nfo_path)
    assert window.favorite_manager.is_favorite(movie.nfo_path)
    assert read_json(client.state_path, {})['base'][mid]['title'] == '服务器标题'


def test_sync_settings_do_not_rescan_unchanged_paths(qt_window):
    from ui.settings_dialog import SettingsDialog
    app, window = qt_window
    dialog = SettingsDialog(window)
    rescans = []
    dialog.settings_updated.connect(lambda: rescans.append(True))
    dialog.sync_enabled.setChecked(True)
    dialog.sync_mode.setCurrentIndex(dialog.sync_mode.findData('download'))
    dialog.save_settings()
    assert not rescans
    assert window.config.get_value('library_sync')['mode'] == 'download'
    dialog.deleteLater()


def test_synced_poster_cache_does_not_probe_nas(qt_window, tmp_path, monkeypatch):
    from PyQt6.QtGui import QImage
    from utils.poster_cache_manager import PosterCacheManager
    app, window = qt_window
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'cache')
    cache = PosterCacheManager()
    monkeypatch.setattr(cache, '_get_original_mtime', lambda path: (_ for _ in ()).throw(AssertionError('不应访问 NAS')))
    image = QImage(280, 420, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    assert cache.save_to_cache_from_image('//nas/poster.jpg', 280, 420, image, probe_source=False)
    assert cache.has_valid_cache('//nas/poster.jpg', 280, 420)
