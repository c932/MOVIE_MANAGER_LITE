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
