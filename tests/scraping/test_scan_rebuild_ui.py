"""进度可见性与用户确认后备份重建的真实服务回归。"""
import threading

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from scraper.scrape_models import Candidate, Metadata, VideoTarget
from scraper.scrape_service import ScrapeService
from scraper.scrape_settings import ScrapeSettings
from tests.scraping.test_scrape_dialog import app, until


def test_scan_progress_shows_current_directory_and_known_total(app, tmp_path, monkeypatch):
    from ui.scrape_dialog import ScrapeDialog
    from scraper.scrape_models import ScanProgress
    import scraper.media_discovery as module
    gate = threading.Event()
    def discover(paths, **options):
        try:
            options["progress"](ScanProgress("扫描目录", 1, 0, str(tmp_path), 2))
            gate.wait(3)
            options["progress"](ScanProgress("扫描完成", 2, 2, str(tmp_path), 2))
            return []
        finally:
            gate.set()
    monkeypatch.setattr(module, "discover_videos", discover)
    window = ScrapeDialog(mode="existing", service=ScrapeService(ScrapeSettings()))
    window.show()
    window.scan(paths=[str(tmp_path)])
    try:
        until(app, lambda: hasattr(window, "scan_directory") and window.scan_directory.text() == str(tmp_path))
        assert window.scan_progress.isVisible()
        assert window.scan_progress.minimum() == window.scan_progress.maximum() == 0
        assert window.scan_directory.isReadOnly()
        assert window.rect().contains(window.scan_progress.mapTo(window, window.scan_progress.rect().bottomRight()))
        gate.set()
        until(app, lambda: not window.tasks.busy)
        assert window.scan_progress.value() == 2
        assert window.scan_progress.maximum() == 2
        assert "扫描完成" in window.scan_progress.format()
    finally:
        gate.set()
        until(app, lambda: not window.tasks.busy)
        window.close()


@pytest.mark.parametrize(("accept", "transient_failure"), [(True, False), (False, False), (True, True)])
def test_release_nfo_requires_explicit_backup_rebuild_and_save_confirmation(app, tmp_path, monkeypatch, accept, transient_failure):
    from scraper.media_discovery import discover_videos
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / "Film.2024.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    original = b"[URL=https://example.invalid/poster][IMG]release poster[/IMG][/URL]\r\nRelease information"
    nfo.write_bytes(original)
    target = discover_videos([tmp_path])[0]
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "details", lambda c: Metadata("douban", "123", {"title": "重新匹配电影", "plot": "新简介"}, {"douban": "123"}, {"douban": 8.1}))
    window = ScrapeDialog([target], mode="existing", service=service)
    window.show()
    window.plot_source_combo.setCurrentIndex(window.plot_source_combo.findData("douban"))
    window._show_candidates([Candidate("douban", "123", "重新匹配电影")])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: not window.tasks.busy)
    questions = []
    def answer(*args):
        questions.append(args[2])
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", answer)
    try:
        assert "下载说明" in window.target_list.item(0).text()
        assert window.rebuild_check.isVisible()
        assert not window.confirm_button.isEnabled()
        window.rebuild_check.setChecked(True)
        assert window.confirm_button.isEnabled()
        window.confirm_button.click()
        window.metadata_only_check.setChecked(True)
        assert window.save_button.isEnabled()
        if transient_failure:
            from parsers.nfo_parser import NFOParser
            real_parse = NFOParser.parse
            monkeypatch.setattr(NFOParser, "parse", lambda *a, **k: None)
        window.save_button.click()
        until(app, lambda: not window.tasks.busy)
        if transient_failure:
            assert nfo.read_bytes() == original
            monkeypatch.setattr(NFOParser, "parse", real_parse)
            window.retry_button.click()
            until(app, lambda: not window.tasks.busy)
        assert questions and "备份" in questions[0]
        if accept:
            import xml.etree.ElementTree as ET
            assert ET.parse(nfo).getroot().findtext("title") == "重新匹配电影"
            backups = list(tmp_path.glob("*.mml-backup-*"))
            assert backups and backups[0].read_bytes() == original
            assert not window.rebuild_check.isVisible()
            assert not window.rebuild_check.isChecked()
            assert not any("原 NFO" in warning for warning in window.drafts[window._active_key].warnings)
            assert "备份原 NFO" not in window.preview_text.toPlainText()
            window.save_button.click()
            until(app, lambda: not window.tasks.busy)
            assert "成功" in window.target_list.item(0).text()
            assert "部分成功" not in window.target_list.item(0).text()
        else:
            assert nfo.read_bytes() == original
            assert not list(tmp_path.glob("*.mml-backup-*"))
    finally:
        window.close()
