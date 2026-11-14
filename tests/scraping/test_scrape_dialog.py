"""原生工作台行为测试：外部网络/写盘以注入服务隔离。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit

from models.movie import Movie
from scraper.scrape_models import Artwork, Candidate, Metadata, ScrapeDraft, VideoTarget
from scraper.scrape_settings import ScrapeSettings


@pytest.fixture(autouse=True)
def isolate_optional_rating_network(monkeypatch):
    from scraper.scrape_service import ScrapeService
    monkeypatch.setattr(ScrapeService, "enrich_metadata", lambda self, metadata: metadata)


@pytest.fixture(scope="session")
def app():
    from PyQt6.QtGui import QFont, QFontDatabase
    application = QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and Path("C:/Windows/Fonts/msyh.ttc").exists():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyhbd.ttc")
        application.setFont(QFont("Microsoft YaHei", 9))
    application.setStyleSheet((Path(__file__).resolve().parents[2] / "styles/style.qss").read_text(encoding="utf-8"))
    return application


def until(app, predicate, timeout=3000):
    app.processEvents()
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "Qt 操作未在时限内完成"


class FakeService:
    def __init__(self):
        self.settings = ScrapeSettings(tmdb_api_key="fake")
        self.calls = []
        self.save_calls = []
        self.gates = {}
        self.fail_save = False

    def _record(self, operation, *args):
        assert threading.current_thread() is not threading.main_thread()
        self.calls.append((operation, *args))

    def search(self, source, query, year="", page=1):
        self._record("search", source, query, year, page)
        if query in self.gates:
            self.gates[query].wait(2)
        return [Candidate(source, query, query, year=year, overview="候选简介")]

    def details(self, candidate):
        self._record("details", candidate.source, candidate.id)
        if candidate.id in self.gates:
            self.gates[candidate.id].wait(2)
        return Metadata(candidate.source, candidate.id,
                        fields={"title": candidate.title, "plot": candidate.title + "简介"},
                        ids={candidate.source: candidate.id}, ratings={candidate.source: 8.1})

    def build_draft(self, target, metadata, plot_source="tmdb"):
        self._record("build", str(target.video_path), plot_source)
        values = {}
        ratings = {}
        ids = {}
        for item in metadata:
            values.update(item.fields)
            ratings.update(item.ratings)
            ids.update(item.ids)
        values["ratings"] = ratings
        values["uniqueids"] = ids
        preferred = next((m for m in metadata if m.source == plot_source), None)
        if preferred:
            values["plot"] = preferred.fields.get("plot", "")
        return ScrapeDraft(target, fields=values, artwork=[a for m in metadata for a in m.artwork])

    def save(self, draft, selected_fields=None, overwrite=False, metadata_only=False):
        self._record("save", str(draft.target.video_path))
        assert draft.confirmed
        self.save_calls.append((draft, selected_fields, overwrite, metadata_only))
        if self.fail_save:
            raise ValueError("测试写入失败，请重试")
        gate = self.gates.get("save")
        if gate:
            gate.wait(2)
        return Movie(title=draft.fields["title"], nfo_path=str(draft.target.nfo_path))

    def douban_only(self, target):
        self._record("douban", str(target.video_path))
        return {"success": False, "message": "候选歧义，需要人工确认", "rating": None, "douban_id": ""}


@pytest.fixture
def dialog(app, tmp_path):
    from ui.scrape_dialog import ScrapeDialog
    service = FakeService()
    movies = [Movie(title="甲", video_path=str(tmp_path / "a.mkv"), nfo_path=str(tmp_path / "a.nfo")),
              Movie(title="乙", video_path=str(tmp_path / "b.mkv"), nfo_path=str(tmp_path / "b.nfo"))]
    window = ScrapeDialog(movies, mode="existing", service=service)
    window.show()
    yield window, service
    for gate in service.gates.values():
        gate.set()
    window.close()
    until(app, lambda: not window.tasks.busy)
    app.processEvents()


def search_and_preview(app, window, title="匹配甲"):
    window.query_edit.setText(title)
    window.search_button.click()
    until(app, lambda: window.candidate_list.count() == 1 and not window.tasks.busy)
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: window.confirm_button.isEnabled() and not window.tasks.busy)


def test_empty_state_small_window_and_existing_movies_in_full_mode(app, tmp_path):
    from ui.scrape_dialog import ScrapeDialog
    window = ScrapeDialog(service=FakeService())
    window.show()
    until(app, lambda: not window.tasks.busy)
    window.resize(780, 520)
    app.processEvents()
    assert not window.save_button.isEnabled()
    assert window.minimumWidth() <= 780
    assert window.minimumHeight() <= 520
    assert window.rect().contains(window.save_button.mapTo(window, window.save_button.rect().bottomRight()))
    assert window.status_label.text()
    window.close()
    movie = Movie(title="旧片", nfo_path=str(tmp_path / "old.nfo"), video_path=str(tmp_path / "old.mkv"))
    window = ScrapeDialog([movie], service=FakeService())
    until(app, lambda: not window.tasks.busy)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("existing"))
    assert window.target_list.count() == 1
    window.close()


def test_preview_requires_manual_confirmation_and_saves_selected_fields(dialog, app):
    window, service = dialog
    written = []
    window.saved.connect(written.extend)
    search_and_preview(app, window)
    assert not window.save_button.isEnabled()
    assert "匹配甲" in window.preview_text.toPlainText()
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.field_checks["plot"].setChecked(False)
    window.metadata_only_check.setChecked(True)
    window.save_button.click()
    until(app, lambda: bool(written))
    assert written == [str(window.targets[0].nfo_path)]
    assert "plot" not in service.save_calls[0][1]
    assert service.save_calls[0][3] is True


def test_confirmed_drafts_survive_target_switch_and_batch_save(dialog, app):
    window, service = dialog
    search_and_preview(app, window, "甲确认")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.target_list.setCurrentRow(1)
    search_and_preview(app, window, "乙确认")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    window.target_list.setCurrentRow(0)
    assert "甲确认" in window.preview_text.toPlainText()
    assert window.save_button.isEnabled()
    window.metadata_only_check.setChecked(True)
    window.save_all_button.click()
    until(app, lambda: len(service.save_calls) == 2 and not window.tasks.busy)
    assert [s[0].fields["title"] for s in service.save_calls] == ["甲确认", "乙确认"]


def test_late_candidate_details_cannot_replace_current_preview(dialog, app):
    window, service = dialog
    gate = threading.Event()
    service.gates["旧候选"] = gate
    window._show_candidates([Candidate("tmdb", "旧候选", "旧候选"), Candidate("tmdb", "新候选", "新候选")])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: ("details", "tmdb", "旧候选") in service.calls)
    window.candidate_list.setCurrentRow(1)
    until(app, lambda: "新候选简介" in window.preview_text.toPlainText())
    gate.set()
    until(app, lambda: not window.tasks.busy)
    assert "旧候选" not in window.preview_text.toPlainText()
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    assert next(iter(window.drafts.values())).fields["title"] == "新候选"


def test_clearing_chinese_search_invalidates_late_search(dialog, app):
    window, service = dialog
    service.gates["中文搜索"] = threading.Event()
    window.query_edit.setText("中文搜索")
    window.search_button.click()
    until(app, lambda: any(c[:3] == ("search", "tmdb", "中文搜索") for c in service.calls))
    window.clear_button.click()
    service.gates["中文搜索"].set()
    until(app, lambda: not window.tasks.busy)
    assert not window.query_edit.text()
    assert window.candidate_list.count() == 0


def test_douban_batch_ambiguity_stays_in_same_window_without_other_sources(dialog, app):
    window, service = dialog
    service.settings = ScrapeSettings()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("douban"))
    window.target_list.selectAll()
    window.douban_button.click()
    until(app, lambda: len([c for c in service.calls if c[0] == "douban"]) == 2 and not window.tasks.busy)
    assert "待确认" in window.target_list.item(0).text()
    assert window.source_combo.currentData() == "douban"
    assert not any(c[0] in {"save", "search", "details"} for c in service.calls)
    search_and_preview(app, window, "手动豆瓣")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.save_button.click()
    until(app, lambda: len(service.save_calls) == 1 and not window.tasks.busy)
    selected = service.save_calls[0][1]
    assert "plot" not in selected and "poster" not in selected


def test_save_error_is_visible_and_retryable(dialog, app):
    window, service = dialog
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    service.fail_save = True
    window.save_button.click()
    until(app, lambda: "测试写入失败" in window.status_label.text())
    assert window.retry_button.isEnabled()
    service.fail_save = False
    window.retry_button.click()
    until(app, lambda: len(service.save_calls) == 2 and not window.tasks.busy)
    assert "成功" in window.status_label.text()


def test_close_defers_until_current_write_finishes_and_cancels_following(dialog, app):
    window, service = dialog
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    service.gates["save"] = threading.Event()
    paths = []
    window.saved.connect(paths.extend)
    window.save_button.click()
    until(app, lambda: len(service.save_calls) == 1)
    window.close()
    assert window.isVisible()
    service.gates["save"].set()
    until(app, lambda: not window.isVisible() and not window.tasks.busy)
    assert paths == [str(window.targets[0].nfo_path)]


def test_settings_credentials_masked_and_io_in_background(app, monkeypatch):
    from ui.scrape_settings_dialog import ScrapeSettingsDialog
    saved = []
    def load():
        assert threading.current_thread() is not threading.main_thread()
        return ScrapeSettings(tmdb_api_key="secret", proxy="http://127.0.0.1:7890")
    def save(settings):
        assert threading.current_thread() is not threading.main_thread()
        saved.append(settings)
    monkeypatch.setattr(ScrapeSettings, "load", load)
    monkeypatch.setattr(ScrapeSettings, "save", save)
    window = ScrapeSettingsDialog()
    window.show()
    until(app, lambda: window.tmdb_key_edit.text() == "secret")
    assert window.tmdb_key_edit.echoMode() == QLineEdit.EchoMode.Password
    window.show_credentials_check.setChecked(True)
    assert window.tmdb_key_edit.echoMode() == QLineEdit.EchoMode.Normal
    window.save_button.click()
    until(app, lambda: bool(saved) and not window.tasks.busy)
    assert saved[0].proxy == "http://127.0.0.1:7890"
    window.close()


def test_loading_new_candidate_disables_saving_old_confirmed_draft(dialog, app):
    window, service = dialog
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    gate = threading.Event()
    service.gates["尚未确认"] = gate
    window._show_candidates([Candidate("tmdb", "尚未确认", "尚未确认")])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: ("details", "tmdb", "尚未确认") in service.calls)
    assert not window.save_button.isEnabled()
    gate.set()


def test_cross_source_only_merges_after_explicit_confirmation(dialog, app):
    window, service = dialog
    search_and_preview(app, window, "TMDB片名")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.source_combo.setCurrentIndex(1)
    search_and_preview(app, window, "豆瓣片名")
    assert "douban" not in next(iter(window.drafts.values())).fields["ratings"]
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    assert next(iter(window.drafts.values())).fields["ratings"] == {"tmdb": 8.1, "douban": 8.1}


def test_switching_to_douban_does_not_save_other_source_fields(dialog, app):
    window, service = dialog
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("douban"))
    assert not window.save_button.isEnabled(), "豆瓣模式须单独人工确认豆瓣身份"
    search_and_preview(app, window, "豆瓣补分")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.save_button.click()
    until(app, lambda: bool(service.save_calls) and not window.tasks.busy)
    fields = service.save_calls[0][1]
    assert fields == {"ratings", "uniqueids"}
    assert service.save_calls[0][0].poster is None


def test_real_service_roundtrip_saves_uniqueids_and_votes(app, tmp_path, monkeypatch):
    from ui.scrape_dialog import ScrapeDialog
    from scraper.scrape_service import ScrapeService
    from parsers.nfo_parser import NFOParser
    video = tmp_path / "roundtrip.mkv"
    video.touch()
    target = VideoTarget(video, video.with_suffix(".nfo"), title="临时新片")
    service = ScrapeService(ScrapeSettings())
    class Provider:
        def search(self, query, year="", page=1):
            return [Candidate("douban", "12345", "临时新片")]
        def details(self, candidate):
            return Metadata("douban", "12345", fields={"title": "临时新片", "plot": "真实服务往返"},
                            ids={"douban": "12345"}, ratings={"douban": 8.6}, votes={"douban": 120})
    monkeypatch.setattr(service, "_provider", lambda source: Provider())
    window = ScrapeDialog([target], mode="full", service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    window.target_list.setCurrentRow(0)
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    paths = []
    window.saved.connect(paths.extend)
    window.save_button.click()
    until(app, lambda: bool(paths) and not window.tasks.busy)
    result = NFOParser.parse(paths[0])
    assert result.title == "临时新片"
    assert result.ratings["douban"] == 8.6
    xml = target.nfo_path.read_text(encoding="utf-8")
    assert 'type="douban"' in xml and ">12345<" in xml
    assert "<votes>120</votes>" in xml
    window.close()


def test_paging_and_id_input_are_explicit_and_preserve_source(dialog, app):
    window, service = dialog
    window.query_edit.setText("https://www.themoviedb.org/movie/278")
    window.search_button.click()
    until(app, lambda: not window.tasks.busy)
    window.next_button.click()
    until(app, lambda: not window.tasks.busy)
    assert ("search", "tmdb", "https://www.themoviedb.org/movie/278", "", 2) in service.calls
    window.previous_button.click()
    until(app, lambda: not window.tasks.busy)
    assert window.page_label.text() == "第 1 页"


def test_cancel_batch_stops_following_saves_but_reports_current(dialog, app):
    window, service = dialog
    for row in (0, 1):
        window.target_list.setCurrentRow(row)
        search_and_preview(app, window, str(row))
        window.confirm_button.click()
        until(app, lambda: not window.tasks.busy)
        window.metadata_only_check.setChecked(True)
    gate = threading.Event()
    service.gates["save"] = gate
    paths = []
    window.saved.connect(paths.extend)
    window.save_all_button.click()
    until(app, lambda: len(service.save_calls) == 1)
    window.cancel_button.click()
    gate.set()
    until(app, lambda: not window.tasks.busy)
    assert len(paths) == 1
    assert len(service.save_calls) == 1
    assert window.save_all_button.isEnabled()


def test_thumbnails_decode_in_worker_and_remain_visible(dialog, app, monkeypatch):
    import ui.scrape_dialog as module
    from PyQt6.QtGui import QImage
    window, service = dialog
    def thumbnail(url, settings, context):
        assert threading.current_thread() is not threading.main_thread()
        image = QImage(40, 60, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        return image
    monkeypatch.setattr(module, "download_preview", thumbnail)
    original = service.details
    def details(candidate):
        result = original(candidate)
        result.artwork = [Artwork("https://example.org/poster.jpg", language="zh", width=1000, height=1500)]
        return result
    monkeypatch.setattr(service, "details", details)
    search_and_preview(app, window)
    assert not window.artwork_list.item(1).icon().isNull()
    assert "zh" in window.artwork_list.item(1).text()
    assert "1000" in window.artwork_list.item(1).text()
    window.artwork_list.setCurrentRow(1)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.field_checks["poster"].setChecked(False)
    window.save_button.click()
    until(app, lambda: bool(service.save_calls) and not window.tasks.busy)
    assert service.save_calls[0][3] is True


def test_identity_replacement_requires_confirmation_but_daily_save_does_not(dialog, app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    window, service = dialog
    original = service.build_draft
    def build(*args, **kwargs):
        draft = original(*args, **kwargs)
        draft.replace_identity = True
        return draft
    monkeypatch.setattr(service, "build_draft", build)
    asked = []
    def reject(*args):
        asked.append(args[2])
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", reject)
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    window.save_button.click()
    assert asked and "整组替换" in asked[0]
    assert not service.save_calls
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.save_button.click()
    until(app, lambda: bool(service.save_calls) and not window.tasks.busy)


def test_settings_connection_test_runs_in_worker_and_cancel_closes_safely(app):
    from ui.scrape_settings_dialog import ScrapeSettingsDialog
    gate = threading.Event()
    started = threading.Event()
    def connect(settings, source):
        assert threading.current_thread() is not threading.main_thread()
        started.set()
        gate.wait(2)
        return "连接成功"
    window = ScrapeSettingsDialog(settings=ScrapeSettings(), connection_test=connect)
    window.show()
    window.test_button.click()
    until(app, started.is_set)
    window.reject()
    assert window.isVisible()
    gate.set()
    until(app, lambda: not window.isVisible() and not window.tasks.busy)
    assert window.result() == window.DialogCode.Rejected


def test_real_service_can_save_same_draft_again_after_success(app, tmp_path, monkeypatch):
    from scraper.scrape_service import ScrapeService
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / "repeat.mkv"
    video.touch()
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "search", lambda *args, **kwargs: [Candidate("douban", "100", "重复")])
    monkeypatch.setattr(service, "details", lambda candidate: Metadata("douban", "100", fields={"title": "重复"}, ids={"douban": "100"}))
    window = ScrapeDialog([VideoTarget(video, video.with_suffix(".nfo"), title="重复")], service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.metadata_only_check.setChecked(True)
    paths = []
    window.saved.connect(paths.extend)
    window.save_button.click()
    until(app, lambda: len(paths) == 1 and not window.tasks.busy)
    window.save_button.click()
    until(app, lambda: not window.tasks.busy)
    try:
        assert len(paths) == 2, window.status_label.text()
    finally:
        window.close()


def test_new_movie_without_poster_requires_explicit_metadata_only(app, tmp_path):
    from ui.scrape_dialog import ScrapeDialog
    service = FakeService()
    target = VideoTarget(tmp_path / "new.mkv", tmp_path / "new.nfo", "新片")
    window = ScrapeDialog([target], service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.field_checks["poster"].setChecked(False)
    window.save_button.click()
    assert not service.save_calls
    assert "仅保存元数据" in window.status_label.text()
    window.metadata_only_check.setChecked(True)
    window.save_button.click()
    until(app, lambda: bool(service.save_calls) and not window.tasks.busy)
    window.close()


@pytest.mark.parametrize("overwrite", [False, True])
def test_real_service_existing_poster_requires_explicit_overwrite(app, tmp_path, monkeypatch, overwrite):
    import io
    from PIL import Image
    from scraper.scrape_http import HttpClient
    from scraper.scrape_service import ScrapeService
    from ui.scrape_dialog import ScrapeDialog
    import ui.scrape_dialog as module
    from PyQt6.QtGui import QImage
    video = tmp_path / "old.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    nfo.write_text('<movie><title>同一电影</title><uniqueid type="tmdb">278</uniqueid></movie>', encoding="utf-8")
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"original-poster")
    data = io.BytesIO()
    Image.new("RGB", (20, 30), "blue").save(data, "JPEG")
    downloads = []
    def get_bytes(client, url, max_bytes):
        downloads.append(url)
        return data.getvalue()
    monkeypatch.setattr(HttpClient, "get_bytes", get_bytes)
    monkeypatch.setattr(module, "download_preview", lambda *args: QImage())
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "search", lambda *args, **kwargs: [Candidate("tmdb", "278", "同一电影")])
    monkeypatch.setattr(service, "details", lambda candidate: Metadata("tmdb", "278", fields={"title": "同一电影"}, ids={"tmdb": "278"}, artwork=[Artwork("https://example.org/new.jpg")]))
    window = ScrapeDialog([Movie(title="同一电影", video_path=str(video), nfo_path=str(nfo))], mode="existing", service=service)
    window.show()
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.overwrite_check.setChecked(overwrite)
    window.save_button.click()
    until(app, lambda: not window.tasks.busy)
    assert "成功" in window.status_label.text()
    assert bool(downloads) is overwrite
    assert poster.read_bytes() == b"original-poster"
    assert (tmp_path / "old-poster.jpg").exists() is overwrite
    window.close()


def test_scan_uses_config_blacklists_in_background(dialog, app, tmp_path, monkeypatch):
    import scraper.media_discovery as module
    from utils.config_manager import ConfigManager
    window, service = dialog
    config = ConfigManager()
    config._config = {"movie_paths": [str(tmp_path)], "blacklist_folders": ["skip"], "blacklist_patterns": ["sample"]}
    calls = []
    def discover(paths, blacklist_folders=(), blacklist_patterns=(), check_cancelled=None, progress=None):
        assert threading.current_thread() is not threading.main_thread()
        calls.append((paths, blacklist_folders, blacklist_patterns))
        return [VideoTarget(tmp_path / "scanned.mkv", tmp_path / "scanned.nfo", "扫描新片")]
    monkeypatch.setattr(module, "discover_videos", discover)
    window.scan_button.click()
    until(app, lambda: bool(calls) and not window.tasks.busy)
    assert calls == [([str(tmp_path)], ["skip"], ["sample"])]
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("full"))
    assert "扫描新片" in window.target_list.item(0).text()


def test_corrupt_nfo_can_preview_candidate_but_never_confirm_or_save(app, tmp_path, monkeypatch):
    from ui.scrape_dialog import ScrapeDialog
    from scraper.scrape_service import ScrapeService
    video = tmp_path / "broken.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    nfo.write_text("<movie>broken", encoding="utf-8")
    target = VideoTarget(video, nfo, "损坏原片", existing=True, error="原 NFO 损坏")
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "details", lambda candidate: Metadata("douban", "123", fields={"title": "可供预览", "plot": "候选原始简介"}))
    window = ScrapeDialog([target], mode="existing", service=service)
    window.show()
    window._show_candidates([Candidate("douban", "123", "可供预览")])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: not window.tasks.busy)
    try:
        assert "候选原始简介" in window.preview_text.toPlainText()
        assert "原 NFO 损坏" in window.preview_text.toPlainText()
        assert not window.confirm_button.isEnabled()
        assert not window.save_button.isEnabled()
        assert nfo.read_text(encoding="utf-8") == "<movie>broken"
    finally:
        window.close()


def test_parent_close_waits_for_settings_child_background_task(dialog, app):
    window, service = dialog
    window.settings_button.click()
    settings = window._settings_window
    gate = threading.Event()
    started = threading.Event()
    def connect(config, source):
        started.set()
        gate.wait(2)
        return "连接成功"
    settings._connection_test = connect
    settings.test_button.click()
    until(app, started.is_set)
    window.close()
    try:
        assert window.isVisible(), "父窗口须等设置子窗口线程完成再关闭"
    finally:
        gate.set()
        until(app, lambda: not settings.tasks.busy)
        settings.close()
        window.close()


def test_rescan_reloads_repaired_nfo_and_invalidates_changed_draft(dialog, app, monkeypatch):
    import scraper.media_discovery as module
    window, service = dialog
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    target = window.targets[0]
    target.error = "原 NFO 损坏"
    repaired = VideoTarget(target.video_path, target.nfo_path, target.title, existing=True, nfo_stamp=(10, 100))
    monkeypatch.setattr(module, "discover_videos", lambda *args, **kwargs: [repaired])
    window.scan(paths=[str(target.video_path.parent)])
    until(app, lambda: not window.tasks.busy)
    assert not window.current_target.error
    assert window.current_target.nfo_stamp == (10, 100)
    assert not window.save_button.isEnabled()


@pytest.mark.parametrize("new_id", ["111", "222"])
def test_douban_manual_save_overwrites_only_selected_douban_data(app, tmp_path, monkeypatch, new_id):
    import xml.etree.ElementTree as ET
    from PyQt6.QtWidgets import QMessageBox
    from scraper.scrape_service import ScrapeService
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / "douban.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    nfo.write_text('''<movie><title>原片名</title><plot>原简介</plot><userrating>6</userrating><playcount>1</playcount><tag>收藏标签</tag><custom>自定义</custom><uniqueid type="douban">111</uniqueid><uniqueid type="tmdb">888</uniqueid><uniqueid type="imdb">tt1234567</uniqueid><ratings><rating name="douban"><value>7</value><votes>10</votes></rating><rating name="imdb"><value>8.2</value><votes>20</votes></rating></ratings><thumb aspect="poster">poster.jpg</thumb></movie>''', encoding="utf-8")
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"old-poster")
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "search", lambda *args, **kwargs: [Candidate("douban", new_id, "不同的来源片名")])
    monkeypatch.setattr(service, "details", lambda candidate: Metadata("douban", new_id, fields={"title": "不同的来源片名", "plot": "不应写入的简介"}, ids={"douban": new_id}, ratings={"douban": 9.1}, votes={"douban": 123}))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window = ScrapeDialog([Movie(title="原片名", video_path=str(video), nfo_path=str(nfo))], mode="douban", service=service)
    window.show()
    try:
        search_and_preview(app, window)
        window.confirm_button.click()
        until(app, lambda: not window.tasks.busy)
        window.save_button.click()
        until(app, lambda: not window.tasks.busy)
        assert "成功" in window.status_label.text()
        root = ET.parse(nfo).getroot()
        assert root.findtext("uniqueid[@type='douban']") == new_id
        assert root.findtext("ratings/rating[@name='douban']/value") == "9.1"
        assert root.findtext("ratings/rating[@name='douban']/votes") == "123"
        assert root.findtext("uniqueid[@type='tmdb']") == "888"
        assert root.findtext("uniqueid[@type='imdb']") == "tt1234567"
        assert root.findtext("ratings/rating[@name='imdb']/value") == "8.2"
        assert root.findtext("plot") == "原简介" and root.findtext("title") == "原片名"
        assert root.findtext("userrating") == "6" and root.findtext("playcount") == "1"
        assert root.findtext("tag") == "收藏标签" and root.findtext("custom") == "自定义"
        assert root.findtext("thumb") == "poster.jpg" and poster.read_bytes() == b"old-poster"
    finally:
        window.close()


@pytest.mark.parametrize("existed", [True, False])
def test_nfo_changed_during_real_service_details_is_rejected(app, tmp_path, monkeypatch, existed):
    from scraper.scrape_service import ScrapeService
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / "conflict.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    if existed:
        nfo.write_text('<movie><title>原版本</title></movie>', encoding="utf-8")
    service = ScrapeService(ScrapeSettings())
    entered, release = threading.Event(), threading.Event()
    external = '<movie><title>外部修改</title><plot>保留外部内容</plot></movie>'
    def details(candidate):
        entered.set()
        release.wait(3)
        nfo.write_text(external, encoding="utf-8")
        return Metadata("douban", "123", fields={"title": "原版本"}, ids={"douban": "123"})
    monkeypatch.setattr(service, "details", details)
    window = ScrapeDialog([Movie(title="原版本", video_path=str(video), nfo_path=str(nfo))], mode="existing", service=service)
    window.show()
    try:
        window._show_candidates([Candidate("douban", "123", "原版本")])
        window.candidate_list.setCurrentRow(0)
        until(app, entered.is_set)
        release.set()
        until(app, lambda: not window.tasks.busy)
        assert not window.confirm_button.isEnabled()
        assert not window.save_button.isEnabled()
        assert "改变" in window.status_label.text() or "冲突" in window.status_label.text()
        assert nfo.read_text(encoding="utf-8") == external
    finally:
        release.set()
        until(app, lambda: not window.tasks.busy)
        window.close()


def test_confirmed_draft_editors_persist_per_target_and_save_selected_fields(dialog, app):
    window, service = dialog
    search_and_preview(app, window, "来源片名甲")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.title_edit.setText("人工片名甲")
    window.plot_edit.setPlainText("人工简介甲")
    window.query_edit.setText("搜索词不参与保存")
    window.metadata_only_check.setChecked(True)
    window.target_list.setCurrentRow(1)
    search_and_preview(app, window, "来源片名乙")
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    window.title_edit.setText("人工片名乙")
    window.plot_edit.setPlainText("人工简介乙")
    window.metadata_only_check.setChecked(True)
    window.field_checks["plot"].setChecked(False)
    window.target_list.setCurrentRow(0)
    assert window.title_edit.text() == "人工片名甲"
    assert window.plot_edit.toPlainText() == "人工简介甲"
    window.save_all_button.click()
    until(app, lambda: len(service.save_calls) == 2 and not window.tasks.busy)
    assert [call[0].fields["title"] for call in service.save_calls] == ["人工片名甲", "人工片名乙"]
    assert service.save_calls[0][0].fields["plot"] == "人工简介甲"
    assert "plot" not in service.save_calls[1][1]


def test_douban_mode_disables_title_and_plot_editors(dialog, app):
    window, service = dialog
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("douban"))
    search_and_preview(app, window)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    assert not window.title_edit.isEnabled()
    assert not window.plot_edit.isEnabled()


def test_real_service_saves_edited_title_and_respects_unselected_plot(app, tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    from scraper.scrape_service import ScrapeService
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / "edited.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    nfo.write_text('<movie><title>原片名</title><plot>原简介</plot><uniqueid type="tmdb">1</uniqueid></movie>', encoding="utf-8")
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, "search", lambda *args, **kwargs: [Candidate("tmdb", "1", "原片名")])
    monkeypatch.setattr(service, "details", lambda candidate: Metadata("tmdb", "1", fields={"title": "原片名", "plot": "来源简介"}, ids={"tmdb": "1"}))
    window = ScrapeDialog([Movie(title="原片名", video_path=str(video), nfo_path=str(nfo))], mode="existing", service=service)
    window.show()
    try:
        search_and_preview(app, window)
        window.confirm_button.click()
        until(app, lambda: not window.tasks.busy)
        window.title_edit.setText("人工修订片名")
        window.plot_edit.setPlainText("本次不写入的编辑简介")
        window.query_edit.setText("仅用于搜索的内容")
        window.field_checks["plot"].setChecked(False)
        window.overwrite_check.setChecked(True)
        window.metadata_only_check.setChecked(True)
        window.save_button.click()
        until(app, lambda: not window.tasks.busy)
        assert "成功" in window.status_label.text()
        root = ET.parse(nfo).getroot()
        assert root.findtext("title") == "人工修订片名"
        assert root.findtext("plot") == "原简介"
    finally:
        window.close()
