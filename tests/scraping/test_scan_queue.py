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


def test_rescan_keeps_complete_douban_movies_out_of_queue(app, tmp_path):
    from parsers.nfo_parser import NFOParser
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from scraper.scan_queue import load_queue
    from tests.scraping.test_scrape_dialog import until
    from ui.scrape_dialog import ScrapeDialog
    for name, score, link in [('完整', '9.1', '<uniqueid type="douban">1293174</uniqueid>'),
                              ('缺评分', '0', '<doubanurl>https://movie.douban.com/subject/1/</doubanurl>'),
                              ('缺链接', '8.1', '')]:
        (tmp_path / f'{name}.mkv').touch()
        (tmp_path / f'{name}.nfo').write_text(
            f'<movie><title>{name}</title><ratings><rating name="douban"><value>{score}</value></rating></ratings>{link}</movie>',
            encoding='utf-8')
    movies = [NFOParser.parse(str(p)) for p in tmp_path.glob('*.nfo')]
    window = ScrapeDialog(movies, service=ScrapeService(ScrapeSettings()))
    window.show()
    try:
        until(app, lambda: not window.tasks.busy)
        window.scan(paths=[str(tmp_path)])
        until(app, lambda: not window.tasks.busy)
        window.mode_combo.setCurrentIndex(window.mode_combo.findData('douban'))
        assert window.target_list.count() == 2
        labels = [window.target_list.item(i).text() for i in range(2)]
        assert all('完整' not in label for label in labels)
        assert next(t for t in window.targets if t.title == '完整').douban_complete is True
        assert next(t for t in load_queue() if t.title == '完整').douban_complete is True
        # 外部修改 NFO 后重新扫描，也必须发现新缺失，不能沿用旧状态。
        nfo = tmp_path / '完整.nfo'
        nfo.write_text('<movie><title>完整</title></movie>', encoding='utf-8')
        window.mode_combo.setCurrentIndex(window.mode_combo.findData('full'))
        window.scan(paths=[str(tmp_path)])
        until(app, lambda: not window.tasks.busy)
        window.mode_combo.setCurrentIndex(window.mode_combo.findData('douban'))
        assert window.target_list.count() == 3
    finally:
        window.close()


@pytest.mark.parametrize('link', [
    '<doubanurl>https://movie.douban.com/subject/1/</doubanurl>',
    '<url>https://movie.douban.com/subject/1/</url>',
    '<uniqueid type="douban">1</uniqueid>',
])
@pytest.mark.parametrize('score,expected', [('9.1', True), ('0', False), ('NaN', False), ('11', False)])
def test_discovery_douban_completeness_uses_library_nfo_rules(tmp_path, link, score, expected):
    from scraper.media_discovery import discover_videos
    (tmp_path / 'film.mkv').touch()
    (tmp_path / 'film.nfo').write_text(
        f'<movie><title>电影</title><ratings><rating name="douban"><value>{score}</value></rating></ratings>{link}</movie>',
        encoding='utf-8')
    assert discover_videos([tmp_path])[0].douban_complete is expected


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
