from types import SimpleNamespace

import pytest


@pytest.fixture
def qt_window(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "start_scan", lambda *args, **kwargs: None)
    monkeypatch.setattr(MainWindow, "_load_visible_posters", lambda *args: None)
    window = MainWindow()
    window.offline_cache_only = True
    yield application, window
    if hasattr(window, "scanner"):
        window.scanner = SimpleNamespace(isRunning=lambda: False)
    runner = getattr(window, "_scrape_refresh_runner", None)
    if runner:
        _wait(application, lambda: not runner.busy)
    window.close()
    application.processEvents()


def _wait(application, predicate):
    import time
    from PyQt6.QtTest import QTest
    deadline = time.monotonic() + 4
    application.processEvents()
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)
    assert predicate(), "主窗口异步刷新超时"


def test_toolbar_opens_unified_workbench_even_when_library_empty():
    from ui.main_window import MainWindow
    calls = []
    fake = SimpleNamespace(_show_scrape_workbench=lambda *args, **kw: calls.append((args, kw)))
    MainWindow._open_scrape_dialog(fake)
    assert len(calls) == 1


def test_douban_shortcut_selects_same_workbench_mode():
    from ui.main_window import MainWindow
    calls = []
    fake = SimpleNamespace(_show_scrape_workbench=lambda *args, **kw: calls.append((args, kw)))
    movie = object()
    MainWindow._menu_scrape_douban_rating(fake, movie)
    assert calls == [(([movie],), {"mode": "douban"})]


def test_saved_movies_are_added_without_full_rescan_or_lost_queue(tmp_path, monkeypatch):
    import time
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "start_scan", lambda *a, **k: None)
    monkeypatch.setattr(MainWindow, "_load_visible_posters", lambda *a: None)
    window = MainWindow()
    paths = []
    for name in ("A", "B"):
        (tmp_path / (name + ".mkv")).touch()
        nfo = tmp_path / (name + ".nfo")
        nfo.write_text(f"<movie><title>{name}</title></movie>", encoding="utf-8")
        paths.append(str(nfo))
    window._on_scrape_saved(paths[:1])
    window._on_scrape_saved(paths[1:])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if len(window.all_movies) == 2 and not window._scrape_refresh_runner.busy:
            break
        QTest.qWait(10)
    try:
        assert {m.title for m in window.all_movies} == {"A", "B"}
        assert not window._pending_scrape_paths
        assert not window._scrape_refresh_runner.busy
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("read_finishes_first", [True, False])
def test_scrape_read_overlapping_scan_upserts_movie_and_cache(qt_window, tmp_path, monkeypatch, read_finishes_first):
    import threading
    from models.movie import Movie
    from parsers.nfo_parser import NFOParser
    from utils.watch_history import WatchHistoryManager
    app, window = qt_window
    video = tmp_path / "one.mkv"
    video.touch()
    nfo = video.with_suffix(".nfo")
    nfo.write_text('<movie><title>保存后的片名</title></movie>', encoding="utf-8")
    started, release = threading.Event(), threading.Event()
    real_parse = NFOParser.parse
    def parse(*args, **kwargs):
        started.set()
        release.wait(3)
        return real_parse(*args, **kwargs)
    monkeypatch.setattr(NFOParser, "parse", staticmethod(parse))
    caches = []
    def cache(movies, roots):
        caches.append([WatchHistoryManager.normalize_path(m.nfo_path) for m in movies])
        return True
    monkeypatch.setattr(window.cache_manager, "save_cache", cache)
    running = [False]
    window.scanner = SimpleNamespace(isRunning=lambda: running[0])
    window._on_scrape_saved([str(nfo)])
    _wait(app, started.is_set)
    running[0] = True
    try:
        if read_finishes_first:
            release.set()
            _wait(app, lambda: not window._scrape_refresh_runner.busy)
            assert not window.all_movies, "扫描尚在进行时应延后合并读回结果"
        window.on_movie_found(Movie(title="扫描结果", video_path=str(video), nfo_path=str(nfo)))
        window.on_movie_found(Movie(title="扫描结果", video_path=str(video), nfo_path=str(nfo).replace('\\', '/').upper()))
        running[0] = False
        window.on_scan_completed(2)
        release.set()
        _wait(app, lambda: not window._scrape_refresh_runner.busy and bool(window.all_movies))
        assert len(window.all_movies) == 1
        assert window.all_movies[0].title == "保存后的片名"
        assert caches and all(len(keys) == len(set(keys)) for keys in caches)
        assert len(window._card_pool) == 1
    finally:
        running[0] = False
        release.set()
        _wait(app, lambda: not window._scrape_refresh_runner.busy)


@pytest.mark.parametrize("old_rating,new_rating", [(7.0, 9.1), (0, 9.1), (7.0, 0)])
def test_scrape_refresh_updates_actual_card_title_and_rating(qt_window, tmp_path, monkeypatch, old_rating, new_rating):
    from models.movie import Movie
    from ui.scrape_tasks import TaskRunner
    app, window = qt_window
    nfo = str(tmp_path / "card.nfo")
    old = Movie(title="旧卡片标题", nfo_path=nfo, rating=old_rating, rating_source="douban")
    window.all_movies = [old]
    window.filtered_movies = [old]
    window.refresh_poster_wall()
    card = window.movie_cards[0]
    assert card.title_label.text() == "旧卡片标题"
    monkeypatch.setattr(window.cache_manager, "save_cache", lambda *args: True)
    window._scrape_refresh_runner = TaskRunner(window)
    window._on_scrape_refresh_result("read", 0, [Movie(title="新卡片标题", nfo_path=nfo, rating=new_rating, rating_source="douban")])
    _wait(app, lambda: not window._scrape_refresh_runner.busy)
    current = window.movie_cards[0]
    assert current.title_label.text() == "新卡片标题"
    if new_rating:
        assert f"{new_rating:.1f}" in current.rating_badge.text()
        assert not current.rating_badge.isHidden()
    else:
        badge = getattr(current, "rating_badge", None)
        assert badge is None or badge.isHidden() or not badge.text()
