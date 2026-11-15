from pathlib import Path

from PyQt6.QtCore import Qt

from models.movie import Movie
from scraper.management import ManagementRow
from scraper.scrape_models import VideoTarget
from tests.scraping.test_scrape_dialog import app, until


def row(title, score=0):
    return ManagementRow(VideoTarget(Path(title + '.mkv'), Path(title + '.nfo'), title, existing=True),
                         Movie(title=title, video_path=title + '.mkv', nfo_path=title + '.nfo', ratings={'douban': score}))


def test_table_numeric_sort_and_filter_keep_video_identity(app):
    from ui.scrape_table import MovieTableModel, MovieFilterModel
    model = MovieTableModel([row('低分', 7), row('高分', 9.1)])
    proxy = MovieFilterModel()
    proxy.setSourceModel(model)
    proxy.sort(4, Qt.SortOrder.DescendingOrder)
    assert proxy.index(0, 0).data() == '高分'
    assert proxy.index(0, 0).data(Qt.ItemDataRole.UserRole).movie.title == '高分'
    proxy.set_query('低分')
    assert proxy.rowCount() == 1 and proxy.index(0, 0).data() == '低分'


def test_manager_opens_without_scan_and_restores_state(app, tmp_path, monkeypatch):
    from ui.scrape_manager import ScrapeManagerDialog
    import scraper.management as management
    monkeypatch.setattr(management, 'scan_rows', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('打开不能扫描')))
    window = ScrapeManagerDialog([row('电影').movie])
    window.show()
    until(app, lambda: not window.tasks.busy)
    assert window.model.rowCount() == 1
    assert window.model.columnCount() == 14
    assert window.table.columnWidth(0) == 155
    assert window.scan_button.text().startswith('更新媒体库')
    window.close()
    until(app, lambda: not window.tasks.busy)
    reopened = ScrapeManagerDialog()
    reopened.show()
    until(app, lambda: not reopened.tasks.busy)
    assert reopened.model.rowCount() == 1
    reopened.close()
    until(app, lambda: not reopened.tasks.busy)


def test_manager_scan_populates_table_and_retains_selected_identity(app, tmp_path):
    from ui.scrape_manager import ScrapeManagerDialog
    from tests.scraping.test_management import movie_files
    movie_files(tmp_path)
    window = ScrapeManagerDialog()
    window.show()
    until(app, lambda: not window.tasks.busy)
    window.scan(paths=[str(tmp_path)])
    until(app, lambda: not window.tasks.busy)
    assert window.model.rowCount() == 1
    assert window.selected_rows()[0].movie.title == '电影'
    assert window.inspector.current_row.movie.title == '电影'
    window.close()
    until(app, lambda: not window.tasks.busy and not window.inspector.tasks.busy)


def test_manager_scan_failure_keeps_rows_and_close_waits_for_poster(app, tmp_path, monkeypatch):
    from ui.scrape_manager import ScrapeManagerDialog
    from PyQt6.QtGui import QImage
    from utils import image_loader
    from utils.poster_cache_manager import PosterCacheManager
    from utils import network_mode
    import threading
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'posters')
    monkeypatch.setattr(network_mode, 'is_offline_cache_only', lambda: False)
    def load(*args):
        entered.set()
        release.wait(3)
        return QImage()
    monkeypatch.setattr(image_loader, '_load_and_scale_image', load)
    movie = row('保留电影').movie
    movie.poster_path = str(tmp_path / 'poster.jpg')
    window = ScrapeManagerDialog([movie])
    window.show()
    until(app, entered.is_set)
    window.scan(paths=[str(tmp_path / 'missing-folder')])
    until(app, lambda: not window.tasks.busy)
    assert window.model.rowCount() == 1
    assert '操作失败' in window.status_label.text()
    window.close()
    assert window.isVisible()
    release.set()
    until(app, lambda: not window.tasks.busy and not window.inspector.tasks.busy)
    assert not window.isVisible()


def test_close_preserves_committed_save_refresh_and_durable_status(app, tmp_path, monkeypatch):
    from ui.scrape_manager import ScrapeManagerDialog
    import ui.scrape_manager as manager
    from scraper.management import load_library
    from tests.scraping.test_management import movie_files
    import threading
    nfo = movie_files(tmp_path)
    entered, release = threading.Event(), threading.Event()
    real = manager.inspect_target
    def slow(target):
        entered.set()
        release.wait(3)
        return real(target)
    monkeypatch.setattr(manager, 'inspect_target', slow)
    movie = Movie(title='旧标题', nfo_path=str(nfo), video_path=str(nfo.with_suffix('.mkv')))
    window = ScrapeManagerDialog([movie])
    window.show()
    until(app, lambda: not window.tasks.busy)
    window._child_saved([str(nfo)])
    until(app, entered.is_set)
    window.close()
    release.set()
    until(app, lambda: not window.tasks.busy and not window.inspector.tasks.busy)
    rows = load_library()
    assert rows[0].movie.title == '电影' and rows[0].outcome == '已保存'


def test_reopen_keeps_scanned_metadata_over_stale_wall_cache(app, tmp_path):
    from ui.scrape_manager import ScrapeManagerDialog
    from scraper.management import save_library
    fresh = row('新片名', 9.1)
    fresh.checked_at = 123
    save_library([fresh])
    stale = Movie(title='旧片名', nfo_path=str(fresh.target.nfo_path), video_path=str(fresh.target.video_path), ratings={'douban': 6})
    window = ScrapeManagerDialog([stale])
    window.show()
    until(app, lambda: not window.tasks.busy)
    assert window.model.rows[0].movie.title == '新片名'
    assert window.model.rows[0].score('douban') == 9.1
    window.close()
    until(app, lambda: not window.tasks.busy and not window.inspector.tasks.busy)
