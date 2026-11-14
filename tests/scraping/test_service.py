import xml.etree.ElementTree as ET

import pytest

from scraper.scrape_models import Metadata, ScrapeError, VideoTarget


def test_draft_merges_sources_and_never_auto_confirms(tmp_path):
    from scraper.scrape_service import ScrapeService
    video = tmp_path / "A.mp4"
    video.touch()
    target = VideoTarget(video, video.with_suffix(".nfo"))
    tmdb = Metadata("tmdb", "100", {"title": "电影", "plot": "TMDB简介"}, {"tmdb": "100", "imdb": "tt1234567"}, {"tmdb": 7.5})
    douban = Metadata("douban", "200", {"title": "电影", "plot": "豆瓣简介"}, {"douban": "200"}, {"douban": 8.1})
    draft = ScrapeService().build_draft(target, [tmdb, douban], plot_source="douban")
    assert draft.fields["plot"] == "豆瓣简介"
    assert draft.fields["ratings"] == {"tmdb": 7.5, "douban": 8.1}
    assert draft.fields["uniqueids"]["imdb"] == "tt1234567"
    assert draft.confirmed is False
    assert str(target.nfo_path) in draft.expected_files
    assert not target.nfo_path.exists()


def test_cross_source_imdb_conflict_cannot_be_merged(tmp_path):
    from scraper.scrape_service import ScrapeService
    t = VideoTarget(tmp_path / "a.mp4", tmp_path / "a.nfo")
    with pytest.raises(ScrapeError, match="不同|冲突"):
        ScrapeService().build_draft(t, [Metadata("tmdb", "1", ids={"imdb": "tt1111111"}), Metadata("douban", "2", ids={"imdb": "tt2222222"})])


def test_new_identity_is_flagged_for_user_confirmation(tmp_path):
    from scraper.scrape_service import ScrapeService
    t = VideoTarget(tmp_path / "a.mp4", tmp_path / "a.nfo", existing=True)
    t.video_path.touch()
    t.nfo_path.write_text('<movie><title>A</title><uniqueid type="tmdb">10</uniqueid></movie>', encoding="utf-8")
    draft = ScrapeService().build_draft(t, [Metadata("tmdb", "20", fields={"title": "B"}, ids={"tmdb": "20"})])
    assert draft.replace_identity
    assert any("身份" in s for s in draft.warnings)


def test_legacy_douban_uses_existing_id_and_does_not_search(tmp_path, monkeypatch):
    from scraper.scrape_service import ScrapeService
    import scraper.douban_cli as cli
    t = VideoTarget(tmp_path / "a.mp4", tmp_path / "a.nfo", "电影", existing=True)
    t.video_path.touch()
    t.nfo_path.write_text('<movie><title>电影</title><doubanid>123</doubanid></movie>', encoding="utf-8")
    monkeypatch.setattr(cli, "search_movie", lambda *a: pytest.fail("不应重新猜测已有ID"))
    monkeypatch.setattr(cli, "get_movie_detail", lambda id: {"id": id, "title": "电影", "rating": "8.3"})
    result = ScrapeService().douban_only(t)
    assert result["success"]
    assert result["douban_id"] == "123"
    assert ET.parse(t.nfo_path).getroot().findtext("ratings/rating[@name='douban']/value") == "8.3"


def test_no_douban_rating_leaves_old_nfo_untouched(tmp_path, monkeypatch):
    from scraper.scrape_service import ScrapeService
    import scraper.douban_cli as cli
    t = VideoTarget(tmp_path / "a.mp4", tmp_path / "a.nfo", "电影", existing=True)
    t.video_path.touch()
    old = '<movie><title>电影</title><doubanid>123</doubanid></movie>'
    t.nfo_path.write_text(old, encoding="utf-8")
    monkeypatch.setattr(cli, "get_movie_detail", lambda id: {"id": id, "rating": "-"})
    assert not ScrapeService().douban_only(t)["success"]
    assert t.nfo_path.read_text(encoding="utf-8") == old
