import io
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from scraper.scrape_models import Artwork, ScrapeDraft, ScrapeError, VideoTarget


def target(tmp_path, old=None):
    video = tmp_path / "Test.2024.MKV"
    video.write_bytes(b"video")
    nfo = video.with_suffix(".nfo")
    if old:
        nfo.write_text(old, encoding="utf-8")
    return VideoTarget(video, nfo, "Test", "2024", existing=bool(old))


def picture(color="red"):
    stream = io.BytesIO()
    Image.new("RGB", (16, 24), color).save(stream, "PNG")
    return stream.getvalue()


def test_new_movie_roundtrip_and_metadata_only_does_not_borrow_poster(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    from parsers.nfo_parser import NFOParser
    t = target(tmp_path)
    (tmp_path / "poster.jpg").write_bytes(picture())
    (tmp_path / "fanart.jpg").write_bytes(picture())
    draft = ScrapeDraft(t, {"title": "新片", "year": "2024", "ratings": {"tmdb": 8.1, "imdb": 7.2, "douban": 8.5}}, confirmed=True)
    snapshot_files(draft)
    movie = commit_draft(draft, metadata_only=True)
    assert Path(movie.video_path).samefile(t.video_path)
    assert movie.title == "新片"
    assert movie.ratings == {"tmdb": 8.1, "imdb": 7.2, "douban": 8.5}
    assert movie.poster_path == ""
    assert movie.fanart_path == ""
    assert NFOParser.parse(str(t.nfo_path)).poster_path == ""


def test_fill_missing_preserves_user_unknown_and_existing_rating(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    old = '<movie><title>旧标题</title><custom>收藏标签</custom><unknown>keep</unknown><ratings><rating name="user"><value>9</value></rating><rating name="imdb"><value>8</value></rating></ratings></movie>'
    t = target(tmp_path, old)
    draft = ScrapeDraft(t, {"title": "新标题", "plot": "简介", "ratings": {"imdb": 7.1,"tmdb": 6.8}, "uniqueids": {"douban": "123"}}, confirmed=True)
    snapshot_files(draft)
    commit_draft(draft, metadata_only=True)
    root = ET.parse(t.nfo_path).getroot()
    assert root.findtext("title") == "旧标题"
    assert root.findtext("plot") == "简介"
    assert root.findtext("custom") == "收藏标签"
    assert root.findtext("unknown") == "keep"
    assert root.findtext("ratings/rating[@name='user']/value") == "9"
    assert root.findtext("ratings/rating[@name='imdb']/value") == "8"
    assert root.findtext("doubanid") == "123"
    assert root.findtext("doubanurl") == "https://movie.douban.com/subject/123/"


def test_reject_unconfirmed_and_conflicting_disk_state(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path)
    draft = ScrapeDraft(t, {"title": "新片"})
    snapshot_files(draft)
    with pytest.raises(ScrapeError, match="确认"):
        commit_draft(draft, metadata_only=True)
    draft.confirmed = True
    t.nfo_path.write_text("<movie><title>其他应用写入</title></movie>", encoding="utf-8")
    with pytest.raises(ScrapeError, match="改变|冲突"):
        commit_draft(draft, metadata_only=True)


def test_rolls_back_poster_when_nfo_commit_fails(tmp_path, monkeypatch):
    import scraper.scrape_persistence as persistence
    t = target(tmp_path, "<movie><title>原电影</title></movie>")
    poster = t.video_path.with_name(t.video_path.stem + "-poster.jpg")
    original = picture("blue")
    poster.write_bytes(original)
    draft = ScrapeDraft(t, {"title": "新标题"}, poster=Artwork("https://image.tmdb.org/t/p/x.jpg"), confirmed=True)
    persistence.snapshot_files(draft)
    real_write = persistence._atomic_write
    def fail_nfo(path, data):
        if path == t.nfo_path:
            raise OSError("模拟断网")
        return real_write(path, data)
    monkeypatch.setattr(persistence, "_atomic_write", fail_nfo)
    with pytest.raises(ScrapeError, match="保存"):
        persistence.commit_draft(draft, overwrite=True, poster_bytes=picture())
    assert poster.read_bytes() == original
    assert ET.parse(t.nfo_path).getroot().findtext("title") == "原电影"


def test_identity_replacement_does_not_retain_old_ids_scores_or_art(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path, '<movie><title>A</title><id>tt1234567</id><uniqueid type="tmdb">100</uniqueid><doubanid>200</doubanid><doubanurl>https://movie.douban.com/subject/200/</doubanurl><plot>A剧情</plot><ratings><rating name="imdb"><value>8</value></rating><rating name="user"><value>9</value></rating></ratings></movie>')
    (tmp_path / "poster.jpg").write_bytes(picture())
    draft = ScrapeDraft(t, {"title": "B", "uniqueids": {"tmdb": "300"}}, confirmed=True, replace_identity=True)
    snapshot_files(draft)
    movie = commit_draft(draft, metadata_only=True)
    root = ET.parse(t.nfo_path).getroot()
    assert root.findtext("title") == "B"
    assert root.find("id") is None and root.find("doubanid") is None
    assert root.find("plot") is None
    assert root.find("ratings/rating[@name='imdb']") is None
    assert root.findtext("ratings/rating[@name='user']/value") == "9"
    assert movie.poster_path == ""


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 11])
def test_bad_scores_never_touch_disk(tmp_path, score):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path)
    draft = ScrapeDraft(t, {"title": "片名", "ratings": {"tmdb": score}}, confirmed=True)
    snapshot_files(draft)
    with pytest.raises(ScrapeError, match="评分"):
        commit_draft(draft, metadata_only=True)
    assert not t.nfo_path.exists()


def test_douban_update_uses_real_votes_and_preserves_other_fields(tmp_path):
    from scraper.scrape_persistence import update_douban_nfo
    t = target(tmp_path, "<movie><title>原电影</title><plot>原简介</plot></movie>")
    assert update_douban_nfo(str(t.nfo_path), "123", {"rating": "8.2", "comment_count": 500})
    root = ET.parse(t.nfo_path).getroot()
    assert root.findtext("plot") == "原简介"
    assert root.find("ratings/rating/votes") is None
    assert update_douban_nfo(str(t.nfo_path), "123", {"rating": "8.3", "rating_count": 900})
    assert ET.parse(t.nfo_path).getroot().findtext("ratings/rating/votes") == "900"


def test_full_save_keeps_real_rating_counts(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path)
    draft = ScrapeDraft(t, {"title": "电影", "ratings": {"tmdb": 8.5}}, confirmed=True, votes={"tmdb": 1200})
    snapshot_files(draft)
    commit_draft(draft, metadata_only=True)
    assert ET.parse(t.nfo_path).getroot().findtext("ratings/rating[@name='tmdb']/votes") == "1200"


def test_corrupt_poster_does_not_create_nfo(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path)
    draft = ScrapeDraft(t, {"title": "电影"}, confirmed=True)
    snapshot_files(draft)
    with pytest.raises(ScrapeError, match="有效海报"):
        commit_draft(draft, poster_bytes=b"<html>Access denied</html>")
    assert not t.nfo_path.exists()


def test_overwrite_old_tmdb_alias_roundtrips_new_score(tmp_path):
    from scraper.scrape_persistence import commit_draft, snapshot_files
    t = target(tmp_path, '<movie><title>A</title><ratings><rating name="themoviedb"><value>9</value></rating></ratings></movie>')
    draft = ScrapeDraft(t, {"ratings": {"tmdb": 6}}, confirmed=True)
    snapshot_files(draft)
    movie = commit_draft(draft, overwrite=True, metadata_only=True)
    assert movie.rating == 6
    assert len(ET.parse(t.nfo_path).getroot().findall("ratings/rating")) == 1
