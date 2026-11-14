from types import SimpleNamespace


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
