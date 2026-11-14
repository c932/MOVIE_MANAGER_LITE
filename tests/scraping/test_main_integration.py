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
