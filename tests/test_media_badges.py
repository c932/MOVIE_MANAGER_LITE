import pytest

from utils.media_badges import media_badges, asset_root


@pytest.mark.parametrize('resolution,key', [('480p','480p'), ('HD','720p'), ('1080P','1080p'),
    ('2K','2k'), ('1440p','2k'), ('2160p','4k'), ('4K','4k'), ('4320p','8k'), ('8K','8k')])
def test_resolution_aliases_have_packaged_assets(resolution, key):
    badge, = media_badges(resolution)
    assert badge.key == key
    assert (asset_root() / badge.file).is_file()


@pytest.mark.parametrize('hdr,keys', [('HDR10+',['hdr']), ('HLG',['hdr']), ('Dolby Vision',['dolbyvision']),
    ('DV',['dolbyvision']), ('dovi',['dolbyvision']), ('Dolby Vision / HDR10',['hdr','dolbyvision'])])
def test_dynamic_range_and_combined_formats(hdr, keys):
    badges = media_badges('', hdr)
    assert [badge.key for badge in badges] == keys
    assert all((asset_root() / badge.file).is_file() for badge in badges)


def test_unknown_values_are_not_misrepresented():
    assert media_badges() == []
    assert [(b.title, b.file) for b in media_badges('576p', 'SDR')] == [('576p',''),('SDR','')]


@pytest.mark.parametrize('width,height,key', [(7680,4320,'8k'), (3840,1600,'4k'), (2560,1440,'2k'),
    (2048,1080,'2k'), (1920,800,'1080p'), (1280,544,'720p'), (640,480,'480p')])
def test_real_nfo_dimensions_select_corresponding_icon(width, height, key):
    from parsers.nfo_parser import NFOParser
    resolution = NFOParser._determine_resolution(width,height)
    assert media_badges(resolution)[0].key == key


def test_frozen_resource_root(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert asset_root() == tmp_path / 'logo' / 'media-badges'


def test_qt_card_refresh_and_detail_share_icons(monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('MML_DATA_DIR', str(tmp_path))
    from PyQt6.QtWidgets import QApplication, QLabel
    from models.movie import Movie
    from ui.movie_card import MovieCard
    from ui.tech_badges import TechBadges
    app = QApplication.instance() or QApplication([])
    movie = Movie(title='测试', resolution='4K', hdr_type='Dolby Vision / HDR10')
    card = MovieCard(movie, poster_width=152, poster_height=228)
    detail = TechBadges(movie.resolution, movie.hdr_type, height=42)
    for widget in (card.tech_badges_container, detail):
        labels = widget.findChildren(QLabel)
        assert [label.property('badgeKey') for label in labels] == ['4k','hdr','dolbyvision']
        assert all(not label.pixmap().isNull() for label in labels)
    card.refresh_metadata(Movie(title='新资料', resolution='1080p', hdr_type='HDR10'))
    app.sendPostedEvents(None, 52)  # DeferredDelete
    labels = card.tech_badges_container.findChildren(QLabel)
    assert [label.property('badgeKey') for label in labels] == ['1080p','hdr']
    card.close()
    detail.close()
