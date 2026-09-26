"""gamewall 主窗口的离屏 UI 回归测试。"""
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from gamewall.game_models import Game


class _Config:
    def __init__(self, splitter_sizes=None):
        self.splitter_sizes = splitter_sizes if splitter_sizes is not None else {
            "main": [280, 1380],
            "right": [430, 470],
        }
        self.saved_sizes = None
        self.values = {}

    def get_value(self, key, default=None):
        return self.values.get(key, default)

    def get_splitter_sizes(self):
        return self.splitter_sizes

    def set_splitter_sizes(self, main, right):
        self.saved_sizes = (main, right)

    def get_poster_size(self):
        return (200, 300)

    def save_config(self):
        pass


class _Cache:
    def __init__(self):
        self.manual_overrides = {}
        self.auto_classifications = {}
        self.snapshot = []
        self.merged_fields = {}
        self.negative_results = {}
        self.raise_on_apply = False

    def __len__(self):
        return 0

    def apply_to_game(self, _game):
        if self.raise_on_apply:
            raise RuntimeError("cache apply failed")

    def merge_fields(self, norm_key, fields):
        self.merged_fields.setdefault(norm_key, {}).update(fields)

    def get_scraper_neg(self, norm_key, source):
        return self.negative_results.get((norm_key, source))

    def set_scraper_neg(self, norm_key, source):
        self.negative_results[(norm_key, source)] = time.time()

    def set_auto_aaa_classification(self, norm_key, result=0, evidence=None):
        self.auto_classifications[norm_key] = (result, evidence)

    def snapshot_games(self, games):
        self.snapshot = list(games)

    def set_manual_aaa_override(self, norm_key, override):
        self.manual_overrides[norm_key] = override

    def set_installed_state(self, norm_key, installed, exe_path, source):
        pass

    def load_games_from_cache(self):
        return []

    def save(self):
        pass

    @staticmethod
    def needs_enrichment(game):
        return (not game.steam_appid or not game.description
                or not game.release_date or game.steam_positive_pct <= 0)

    @staticmethod
    def _is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0
        if isinstance(value, (int, float)):
            return value == 0
        return False


def _create_window(splitter_sizes=None):
    from gamewall import game_main_window as main_window

    config = _Config(splitter_sizes)
    cache = _Cache()
    original_config = main_window.ConfigManager
    original_cache = main_window.GameCacheManager
    original_startup = main_window.GameMainWindow._startup_load
    main_window.ConfigManager = lambda: config
    main_window.GameCacheManager = lambda: cache
    main_window.GameMainWindow._startup_load = lambda _self: None
    try:
        window = main_window.GameMainWindow()
    finally:
        main_window.ConfigManager = original_config
        main_window.GameCacheManager = original_cache
        main_window.GameMainWindow._startup_load = original_startup
    return window, cache


def _show_and_process(window, app):
    window.show()
    app.processEvents()
    app.processEvents()


def test_filter_sidebar_resizes_within_bounds_and_accepts_invalid_config():
    app = QApplication.instance() or QApplication([])
    for splitter_sizes in (None, {"right": [430, 470]}, {"right": ["bad", 470]}):
        window, _cache = _create_window(splitter_sizes)
        try:
            window.resize(1200, 720)
            _show_and_process(window, app)

            assert window.minimumSize().width() == 1200
            assert window.minimumSize().height() == 720
            assert window.filter_panel.objectName() == "GameFilterSidebar"
            assert window.main_splitter.isCollapsible(0) is False
            assert window.filter_panel.minimumWidth() == 180
            assert window.filter_panel.maximumWidth() == 400

            window.main_splitter.setSizes([340, 860])
            app.processEvents()
            assert 180 <= window.filter_panel.width() <= 400

            window.main_splitter.setSizes([0, 1200])
            app.processEvents()
            assert 180 <= window.filter_panel.width() <= 400
        finally:
            window.hide()
            window.deleteLater()
            app.processEvents()


def test_long_genre_labels_wrap_and_reset_footer_stays_visible():
    app = QApplication.instance() or QApplication([])
    window, _cache = _create_window()
    try:
        long_genres = [f"超长游戏类型标签用于测试自动换行显示第{i:02d}项" for i in range(30)]
        window.all_games = [
            Game(raw_name=f"测试游戏{i}", genres=[genre])
            for i, genre in enumerate(long_genres)
        ]
        window.resize(1200, 720)
        window.generate_genre_options()
        _show_and_process(window, app)

        genre_buttons = [
            button for button in window.filter_content.findChildren(QPushButton)
            if button.property("filter_label") in long_genres
        ]
        available_width = window.filter_scroll_area.viewport().width() - 30
        assert len(genre_buttons) == len(long_genres)
        assert all(button.width() <= available_width for button in genre_buttons)
        assert all("".join(button.text().splitlines()) == button.property("filter_label")
                   for button in genre_buttons)
        assert max(button.geometry().bottom() for button in genre_buttons) <= (
            window.genre_filter_layout.geometry().bottom())
        assert window.filter_scroll_area.verticalScrollBar().maximum() > 0

        window.filter_scroll_area.verticalScrollBar().setValue(
            window.filter_scroll_area.verticalScrollBar().maximum())
        app.processEvents()
        assert window.reset_button.isVisibleTo(window)

        window.selected_genres.add(long_genres[0])
        window.min_rating = 90.0
        window.aaa_only = True
        window.reset_button.click()
        app.processEvents()
        assert window.selected_genres == set()
        assert window.min_rating == 0.0
        assert window.aaa_only is False
        assert window.reset_button.isVisibleTo(window)
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_developer_options_refresh_preserves_current_selection():
    app = QApplication.instance() or QApplication([])
    window, _cache = _create_window()
    existing = Game(raw_name="现有游戏", developer="Existing Studio")
    enriched = Game(raw_name="待补全游戏")

    def developer_buttons():
        return {
            button.property("filter_label"): button
            for button in window.developer_filter_widget.findChildren(QPushButton)
            if button.property("filter_label")
        }

    try:
        window.all_games = [existing, enriched]
        window.filter_developers = {existing.developer}
        window.generate_developer_options()

        buttons = developer_buttons()
        assert existing.developer in buttons
        assert buttons[existing.developer].isChecked()

        window._games_by_key = {enriched.norm_key: enriched}
        window._on_game_enriched(enriched.norm_key, {"developer": "New Studio"})
        QTest.qWait(150)

        assert enriched.developer == "New Studio"
        buttons = developer_buttons()
        assert "New Studio" in buttons
        assert buttons[existing.developer].isChecked()
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_steam_negative_cache_does_not_block_third_party_candidates(monkeypatch):
    from gamewall import game_main_window as main_window

    class _Signal:
        def connect(self, _callback):
            pass

    class _RecordingWorker:
        instances = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.stage_changed = _Signal()
            self.progress_updated = _Signal()
            self.game_enriched = _Signal()
            self.negative_recorded = _Signal()
            self.finished_with = _Signal()
            self.failed = _Signal()
            self.started = False
            self.__class__.instances.append(self)

        def isRunning(self):
            return False

        def start(self):
            self.started = True

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "EnrichmentWorker", _RecordingWorker)
    window, cache = _create_window()
    core_complete = Game(
        raw_name="Steam 核心完整", steam_appid=10, description="简介",
        release_date="2025-01-01", steam_positive_pct=90.0,
    )
    steam_blocked = Game(raw_name="Steam 负缓存", gamersky_score=0.0)
    try:
        window.config.values.update({
            "network_enabled": True,
            "enable_enrichment": True,
            "enable_gamersky_scraper": True,
            "enable_ign_scraper": False,
        })
        window.all_games = [core_complete, steam_blocked]
        cache.negative_results[(steam_blocked.norm_key, "steam_match")] = 1
        window._start_local_scan = lambda: None

        window._start_background_tasks()

        worker = _RecordingWorker.instances[-1]
        assert worker.started is True
        assert worker.kwargs["steam_candidates"] == set()
        assert worker.kwargs["gamersky_candidates"] == {
            core_complete.norm_key, steam_blocked.norm_key,
        }
        assert worker.kwargs["ign_candidates"] == set()
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_cover_loader_updates_first_card_before_batch_completion(monkeypatch):
    from threading import Event

    from gamewall import cover_loader
    from utils.image_loader import ImageCache

    first_url = "https://cover.test/progressive-first"
    second_url = "https://cover.test/progressive-second"
    image = QImage(20, 30, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)

    class _BlockingCache:
        def __init__(self):
            self.second_started = Event()
            self.release_second = Event()

        def get_cached_image(self, key, _width, _height):
            if key.startswith(first_url):
                return image
            self.second_started.set()
            self.release_second.wait(2)
            return image

        def save_to_cache_from_image(self, *_args):
            pass

    cache = _BlockingCache()
    app = QApplication.instance() or QApplication([])
    ImageCache().clear()
    monkeypatch.setattr(cover_loader, "get_poster_cache_manager", lambda: cache)
    window, _window_cache = _create_window()
    first = Game(raw_name="渐进封面一", header_image=first_url)
    second = Game(raw_name="渐进封面二", header_image=second_url)
    try:
        window.resize(1200, 720)
        _show_and_process(window, app)
        window.all_games = [first, second]
        window.apply_filters()
        window._load_visible_posters()

        for _ in range(30):
            app.processEvents()
            QTest.qWait(10)
            if cache.second_started.is_set():
                break

        assert cache.second_started.is_set()
        for _ in range(30):
            app.processEvents()
            QTest.qWait(10)
            if window.movie_cards[0]._poster_loaded:
                break
        assert window.movie_cards[0]._poster_loaded is True
        assert window.movie_cards[1]._poster_loaded is False

        cache.release_second.set()
        for _ in range(30):
            app.processEvents()
            QTest.qWait(10)
            if window.movie_cards[1]._poster_loaded:
                break
        assert window.movie_cards[1]._poster_loaded is True
    finally:
        cache.release_second.set()
        loader = window._cover_loader
        if loader is not None and loader.isRunning():
            loader.cancel()
            loader.wait(1000)
        window.hide()
        window.deleteLater()
        app.processEvents()


def _fake_cover_loader(monkeypatch):
    from gamewall import game_main_window as main_window

    class _Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in self.callbacks:
                callback(*args)

    class _Loader:
        instances = []

        def __init__(self, _tasks, _parent=None):
            self.image_loaded = _Signal()
            self.all_loaded = _Signal()
            self.running = False
            self.cancelled = False
            self.__class__.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.cancelled = True
            self.running = False

        def wait(self, _ms=0):
            return True

        def complete(self):
            self.running = False
            self.all_loaded.emit()

    monkeypatch.setattr(main_window, "BatchCoverLoader", _Loader)
    return _Loader


def test_stale_cover_result_cannot_update_current_card(monkeypatch):
    from utils.image_loader import ImageCache

    app = QApplication.instance() or QApplication([])
    ImageCache().clear()
    loader_type = _fake_cover_loader(monkeypatch)
    window, _cache = _create_window()
    game = Game(raw_name="过期封面", header_image="https://cover.test/stale-result")
    image = QImage(20, 30, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    try:
        window.resize(1200, 720)
        _show_and_process(window, app)
        window.all_games = [game]
        window.apply_filters()
        window._load_visible_posters()
        first_loader = loader_type.instances[-1]

        window._load_visible_posters()
        second_loader = loader_type.instances[-1]
        assert second_loader is not first_loader
        assert first_loader.cancelled is True

        first_loader.image_loaded.emit(game.get_cover_urls()[0], image)
        QTest.qWait(20)
        assert window.movie_cards[0]._poster_loaded is False

        second_loader.image_loaded.emit(game.get_cover_urls()[0], image)
        QTest.qWait(20)
        assert window.movie_cards[0]._poster_loaded is True
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_failed_visible_cover_schedules_automatic_retry(monkeypatch):
    from utils.image_loader import ImageCache

    app = QApplication.instance() or QApplication([])
    ImageCache().clear()
    loader_type = _fake_cover_loader(monkeypatch)
    window, _cache = _create_window()
    game = Game(raw_name="封面重试", header_image="https://cover.test/retry")
    try:
        window.resize(1200, 720)
        _show_and_process(window, app)
        window.all_games = [game]
        window.apply_filters()
        window._load_visible_posters()
        first_loader = loader_type.instances[-1]

        first_loader.complete()
        QTest.qWait(40)
        assert window.movie_cards[0]._poster_fail_count == 1

        QTest.qWait(700)
        assert len(loader_type.instances) >= 2
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_manual_aaa_override_updates_filter_result_immediately():
    app = QApplication.instance() or QApplication([])
    window, cache = _create_window()
    try:
        game = Game(raw_name="测试游戏/Test Game", aaa_excel_marked=True)
        window.all_games = [game]
        window.aaa_only = True

        window._set_manual_aaa_override(game, False)
        assert cache.manual_overrides[game.norm_key] is False
        assert game.is_aaa is False
        assert window.filtered_games == []

        window._set_manual_aaa_override(game, True)
        assert cache.manual_overrides[game.norm_key] is True
        assert game.is_aaa is True
        assert window.filtered_games == [game]

        window._set_manual_aaa_override(game, None)
        assert cache.manual_overrides[game.norm_key] is None
        assert game.aaa_manual_override is None
        assert window.filtered_games == [game]
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_background_start_failure_preserves_imported_games(caplog):
    app = QApplication.instance() or QApplication([])
    window, _cache = _create_window()
    game = Game(raw_name="成功导入的游戏")
    try:
        def fail_background_start():
            raise RuntimeError("background start failed")

        window._start_background_tasks = fail_background_start
        with caplog.at_level(logging.ERROR, logger="gamewall.game_main_window"):
            window._on_excel_import_finished([game], {"mtime": 1, "header_row": 1})

        assert window.all_games == [game]
        assert window.filtered_games == [game]
        assert window.status_label.text() != "游戏库加载失败"
        assert "后台任务未启动" in window.status_label.text()
        assert any(record.message == "启动后台任务失败" and record.exc_info
                   for record in caplog.records)
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_import_apply_failure_restores_previously_displayed_games(caplog):
    app = QApplication.instance() or QApplication([])
    window, cache = _create_window()
    previous_game = Game(raw_name="先前显示的游戏")
    incoming_game = Game(raw_name="无法应用的新游戏")
    try:
        window.all_games = [previous_game]
        window.apply_filters()
        cache.raise_on_apply = True

        with caplog.at_level(logging.ERROR, logger="gamewall.game_main_window"):
            window._on_excel_import_finished([incoming_game], {"mtime": 1, "header_row": 1})

        assert window.all_games == [previous_game]
        assert window.filtered_games == [previous_game]
        assert "已保留 1 款游戏" in window.status_label.text()
        assert any(record.message == "处理导入结果失败" and record.exc_info
                   for record in caplog.records)
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_steam_alias_hit_bypasses_match_negative_cache(monkeypatch):
    from gamewall import game_main_window as main_window

    class _Signal:
        def connect(self, _callback):
            pass

    class _RecordingWorker:
        instances = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.stage_changed = _Signal()
            self.progress_updated = _Signal()
            self.game_enriched = _Signal()
            self.negative_recorded = _Signal()
            self.finished_with = _Signal()
            self.failed = _Signal()
            self.started = False
            self.__class__.instances.append(self)

        def isRunning(self):
            return False

        def start(self):
            self.started = True

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "EnrichmentWorker", _RecordingWorker)
    window, cache = _create_window()
    alias_hit = Game(raw_name="杀手3豪华版")
    normal_game = Game(raw_name="普通未匹配游戏")
    try:
        window.config.values.update({
            "network_enabled": True,
            "enable_enrichment": True,
            "enable_gamersky_scraper": True,
            "enable_ign_scraper": False,
        })
        window.all_games = [alias_hit, normal_game]
        cache.negative_results[(alias_hit.norm_key, "steam_match")] = 1
        cache.negative_results[(normal_game.norm_key, "steam_match")] = 1
        window._start_local_scan = lambda: None

        window._start_background_tasks()

        worker = _RecordingWorker.instances[-1]
        assert worker.kwargs["steam_candidates"] == {alias_hit.norm_key}
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_permanent_cover_failure_stops_retrying(monkeypatch):
    from utils.image_loader import ImageCache

    app = QApplication.instance() or QApplication([])
    ImageCache().clear()
    loader_type = _fake_cover_loader(monkeypatch)
    window, _cache = _create_window()
    game = Game(raw_name="封面永久失败", header_image="https://cover.test/dead-url")
    try:
        window.resize(1200, 720)
        _show_and_process(window, app)
        window.all_games = [game]
        window.apply_filters()

        for _round in range(3):
            window._load_visible_posters()
            loader = loader_type.instances[-1]
            loader.complete()
            QTest.qWait(40)
            window.movie_cards[0]._poster_next_retry_at = 0.0

        card = window.movie_cards[0]
        # 失败不再永久封禁为 placeholder：_poster_loaded 仍为 False，
        # _poster_next_retry_at 被设为退避时间（之前测试循环中手动清零触发了重试），
        # 下次用户操作触发刷新或退避到期仍可重试读取磁盘缓存。
        assert card._poster_fail_count == 3
        assert card._poster_loaded is False
        # 即便已失败 3 次，刷新仍可生成新 loader 尝试再次加载（不再永久封禁）
        window._load_visible_posters()
        assert len(loader_type.instances) == 4
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
