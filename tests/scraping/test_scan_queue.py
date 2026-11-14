from pathlib import Path

import pytest

from scraper.scrape_models import ScrapeError, VideoTarget


def test_queue_roundtrip_uses_local_cache_without_visiting_video_paths(tmp_path, monkeypatch):
    from scraper.scan_queue import load_queue, save_queue
    target = VideoTarget(Path('//offline-nas/movies/Film.mkv'), Path('//offline-nas/movies/Film.nfo'),
                         'Film', '2024', True, '旧发布说明', (123, 42), 'sha256', True, 'not_metadata', '原 NFO 是发布说明')
    save_queue([target])
    real = Path.stat
    def no_nas(path, *args, **kwargs):
        if 'offline-nas' in str(path):
            pytest.fail('恢复待处理列表不得访问影库')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', no_nas)
    assert load_queue() == [target]


def test_invalid_queue_is_reported_without_overwriting_it(scrape_data_dir):
    from scraper.scan_queue import load_queue
    path = scrape_data_dir / 'scrape_queue.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ScrapeError, match='待处理列表'):
        load_queue()
    assert path.read_text(encoding='utf-8') == '{broken'


def test_opening_workbench_does_not_scan_and_restores_queue(app, tmp_path, monkeypatch):
    from scraper.scan_queue import save_queue
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from tests.scraping.test_scrape_dialog import until
    from ui.scrape_dialog import ScrapeDialog
    import scraper.media_discovery as discovery
    target = VideoTarget(tmp_path / 'pending.mkv', tmp_path / 'pending.nfo', '上次待处理')
    save_queue([target])
    monkeypatch.setattr(discovery, 'discover_videos', lambda *a, **k: pytest.fail('打开刮削不得自动扫描'))
    window = ScrapeDialog(service=ScrapeService(ScrapeSettings()))
    window.show()
    until(app, lambda: not window.tasks.busy)
    assert window.target_list.count() == 1
    assert '上次待处理' in window.target_list.item(0).text()
    window._settings_saved(ScrapeSettings())
    until(app, lambda: not window.tasks.busy)
    assert window.target_list.count() == 1
    window.close()


def test_scan_results_survive_closing_and_reopening(app, tmp_path, monkeypatch):
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from tests.scraping.test_scrape_dialog import until
    from ui.scrape_dialog import ScrapeDialog
    import scraper.media_discovery as discovery
    target = VideoTarget(tmp_path / 'new.mkv', tmp_path / 'new.nfo', '新片')
    calls = []
    monkeypatch.setattr(discovery, 'discover_videos', lambda *a, **k: calls.append(True) or [target])
    window = ScrapeDialog(service=ScrapeService(ScrapeSettings()))
    window.show()
    until(app, lambda: not window.tasks.busy)
    assert not calls
    window.scan(paths=[str(tmp_path)])
    until(app, lambda: not window.tasks.busy)
    assert len(calls) == 1
    window.close()
    reopened = ScrapeDialog(service=ScrapeService(ScrapeSettings()))
    reopened.show()
    until(app, lambda: not reopened.tasks.busy)
    assert len(calls) == 1 and reopened.target_list.count() == 1
    reopened.close()


def test_open_folder_targets_clicked_video_parent(app, tmp_path, monkeypatch):
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QMenu
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from ui.scrape_dialog import ScrapeDialog
    from tests.scraping.test_scrape_dialog import until
    target = VideoTarget(tmp_path / '电影目录' / 'film.mkv', tmp_path / '电影目录' / 'film.nfo')
    opened = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url.toLocalFile()) or True)
    window = ScrapeDialog([target], service=ScrapeService(ScrapeSettings()))
    window.show()
    until(app, lambda: not window.tasks.busy)
    monkeypatch.setattr(QMenu, 'exec', lambda menu, point: menu.actions()[0].trigger())
    window._target_menu(window.target_list.visualItemRect(window.target_list.item(0)).center())
    assert Path(opened[0]) == target.video_path.parent
    window.close()


# 复用本项目统一 QApplication / QSS 夹具。
from tests.scraping.test_scrape_dialog import app


def test_slow_restore_merged_with_new_scan_is_saved(app, tmp_path, monkeypatch):
    import threading
    import scraper.scan_queue as queue
    import scraper.media_discovery as discovery
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from ui.scrape_dialog import ScrapeDialog
    from tests.scraping.test_scrape_dialog import until
    gate = threading.Event()
    old = VideoTarget(tmp_path / 'old.mkv', tmp_path / 'old.nfo')
    new = VideoTarget(tmp_path / 'new.mkv', tmp_path / 'new.nfo')
    real_load = queue.load_queue
    monkeypatch.setattr(queue, 'load_queue', lambda: gate.wait(3) and [old])
    monkeypatch.setattr(discovery, 'discover_videos', lambda *a, **k: [new])
    window = ScrapeDialog(service=ScrapeService(ScrapeSettings()))
    window.show()
    window.scan(paths=[str(tmp_path)])
    try:
        until(app, lambda: len(window.targets) == 1)
        gate.set()
        until(app, lambda: not window.tasks.busy)
        assert {t.video_path.name for t in real_load()} == {'old.mkv', 'new.mkv'}
    finally:
        gate.set()
        until(app, lambda: not window.tasks.busy)
        window.close()
