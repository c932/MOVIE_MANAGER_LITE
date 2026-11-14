import xml.etree.ElementTree as ET

import pytest


def test_ambiguous_automatic_search_returns_no_match(monkeypatch):
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, "run_douban_cli", lambda *a, **k: [
        {"id": "1", "title": "电影", "year": "2024", "rating": "8.0"},
        {"id": "2", "title": "电影", "year": "2024", "rating": "8.2"},
    ])
    assert cli.search_movie("电影", "2024") is None


def test_complete_search_keeps_unrated_movies_and_covers(monkeypatch):
    import scraper.douban_cli as cli
    monkeypatch.setattr(cli, "run_douban_cli", lambda *a, **k: [
        {"id": "1", "title": "新片", "year": "2026", "rating": "-", "type": "movie", "cover": "https://img2.doubanio.com/a.jpg"},
        {"id": "2", "title": "剧集", "rating": "9", "type": "tv"},
    ])
    items = cli.search_movies("新片")
    assert len(items) == 1
    assert items[0]["rating"] == "-" and items[0]["cover"].endswith("a.jpg")


def test_old_injector_calls_shared_atomic_writer(tmp_path, monkeypatch):
    import scraper.douban_cli as cli
    import scraper.scrape_persistence as persistence
    path = tmp_path / "a.nfo"
    original = "<movie><title>A</title></movie>"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(persistence, "_atomic_write", lambda *a: (_ for _ in ()).throw(OSError("模拟磁盘失败")))
    assert not cli.inject_douban_to_nfo(str(path), "123", {"rating": "8"})
    assert path.read_text(encoding="utf-8") == original


def test_old_single_scrape_reuses_id_and_preserves_plot(tmp_path, monkeypatch):
    import scraper.douban_cli as cli
    path = tmp_path / "a.nfo"
    path.write_text('<movie><title>A</title><doubanid>123</doubanid><plot>原简介</plot></movie>', encoding="utf-8")
    monkeypatch.setattr(cli, "search_movie", lambda *a: pytest.fail("不应搜索已知ID"))
    monkeypatch.setattr(cli, "get_movie_detail", lambda id: {"id": id, "title": "A", "rating": "8.1", "comment_count": 300})
    result = cli.scrape_single_movie(str(path), "A", "", "2024")
    assert result["success"] and result["douban_id"] == "123"
    root = ET.parse(path).getroot()
    assert root.findtext("plot") == "原简介"
    assert root.find("ratings/rating/votes") is None
