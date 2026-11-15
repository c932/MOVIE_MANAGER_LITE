import copy
import xml.etree.ElementTree as ET

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from scraper.scrape_models import Candidate, Metadata, VideoTarget
from scraper.scrape_service import ScrapeService
from scraper.scrape_settings import ScrapeSettings
from tests.scraping.test_scrape_dialog import app, until, FakeService


def test_click_previous_next_navigates_and_disables_boundaries(app, tmp_path):
    from ui.scrape_search_dialog import SearchScrapeDialog
    targets = [VideoTarget(tmp_path / f'{name}.mkv', tmp_path / f'{name}.nfo', name) for name in ['A', 'B', 'C']]
    window = SearchScrapeDialog(targets, service=FakeService(), start_index=1)
    window.show()
    assert window.current_target.title == 'B'
    QTest.mouseClick(window.previous_target_button, Qt.MouseButton.LeftButton)
    assert window.current_target.title == 'A' and not window.previous_target_button.isEnabled()
    QTest.mouseClick(window.next_target_button, Qt.MouseButton.LeftButton)
    assert window.current_target.title == 'B'
    QTest.mouseClick(window.next_target_button, Qt.MouseButton.LeftButton)
    assert window.current_target.title == 'C' and not window.next_target_button.isEnabled()
    window.close()
    until(app, lambda: not window.tasks.busy)


def test_single_selection_opens_visible_library_at_current_movie(app, monkeypatch):
    from models.movie import Movie
    from ui.scrape_manager import ScrapeManagerDialog
    from ui.scrape_search_dialog import SearchScrapeDialog
    movies = [Movie(title=name, nfo_path=name + '.nfo', video_path=name + '.mkv') for name in ['A', 'B', 'C']]
    manager = ScrapeManagerDialog(movies, service=FakeService())
    manager.show()
    until(app, lambda: not manager.tasks.busy)
    manager.table.selectRow(1)
    opened = []
    monkeypatch.setattr(SearchScrapeDialog, 'exec', lambda window: opened.append(
        ([t.title for t in window.targets], window.current_target.title)) or 0)
    manager.open_search()
    assert opened == [(['A', 'B', 'C'], 'B')]
    manager.close()
    until(app, lambda: not manager.tasks.busy)


@pytest.mark.parametrize('source', ['tmdb', 'douban'])
def test_same_film_preview_and_save_preserve_all_existing_ratings(tmp_path, source):
    video = tmp_path / 'Film.mkv'
    video.touch()
    nfo = video.with_suffix('.nfo')
    nfo.write_text('<movie><title>旧译名</title><originaltitle>Film</originaltitle><year>2024</year>'
                   '<uniqueid type="tmdb">1</uniqueid><uniqueid type="imdb">tt1234567</uniqueid>'
                   '<uniqueid type="douban">2</uniqueid><ratings>'
                   '<rating name="themoviedb"><value>7.1</value><votes>123</votes></rating>'
                   '<rating name="imdb"><value>7.2</value></rating>'
                   '<rating name="douban"><value>8.1</value></rating></ratings></movie>', encoding='utf-8')
    metadata = Metadata(source, '1' if source == 'tmdb' else '2',
                        {'title': '新译名', 'original_title': 'Film', 'year': '2024'},
                        {source: '1' if source == 'tmdb' else '2'}, {source: 8.3})
    service = ScrapeService()
    draft = service.build_draft(VideoTarget(video, nfo, existing=True), [metadata])
    assert not draft.replace_identity
    assert set(draft.fields['ratings']) == {'tmdb', 'imdb', 'douban'}
    assert draft.fields['ratings'][source] == 8.3
    draft.confirmed = True
    saved = service.save(draft, overwrite=True, metadata_only=True)
    assert set(saved.ratings) >= {'tmdb', 'imdb', 'douban'}


def test_new_identity_does_not_inherit_old_film_ratings(tmp_path):
    video = tmp_path / 'Film.mkv'
    video.touch()
    nfo = video.with_suffix('.nfo')
    nfo.write_text('<movie><title>A</title><uniqueid type="tmdb">1</uniqueid>'
                   '<ratings><rating name="douban"><value>9.9</value></rating></ratings></movie>', encoding='utf-8')
    draft = ScrapeService().build_draft(VideoTarget(video, nfo, existing=True),
                                      [Metadata('tmdb', '3', {'title': 'B'}, {'tmdb': '3'}, {'tmdb': 6.1})])
    assert draft.replace_identity and 'douban' not in draft.fields['ratings']


def test_service_auto_douban_requires_unique_exact_identity(monkeypatch):
    service = ScrapeService()
    primary = Metadata('tmdb', '1', {'title': '电影', 'original_title': 'Film', 'year': '2024'},
                       {'tmdb': '1', 'imdb': 'tt1234567'}, {'tmdb': 7.1, 'imdb': 7.2})
    candidate = Candidate('douban', '2', '电影', 'Film', '2024')
    related = Metadata('douban', '2', {'title': '电影', 'year': '2024'}, {'douban': '2'}, {'douban': 8.1})
    monkeypatch.setattr(service, 'search', lambda *a, **kw: [candidate])
    monkeypatch.setattr(service, 'details', lambda selected: related)
    assert service.automatic_douban_metadata(primary) == [related]
    monkeypatch.setattr(service, 'search', lambda *a, **kw: [candidate, Candidate('douban', '3', '电影', 'Film', '2024')])
    assert service.automatic_douban_metadata(primary) == []
    monkeypatch.setattr(service, 'search', lambda *a, **kw: [Candidate('douban', '4', '电影', 'Film', '1999')])
    assert service.automatic_douban_metadata(primary) == []


def test_auto_douban_conflict_or_outage_preserves_primary_scores(monkeypatch):
    from scraper.scrape_models import ScrapeError
    service = ScrapeService()
    primary = Metadata('tmdb', '1', {'title': '电影', 'year': '2024'}, {'imdb': 'tt1234567'}, {'tmdb': 7.1, 'imdb': 7.2})
    monkeypatch.setattr(service, 'search', lambda *a, **kw: [Candidate('douban', '2', '电影', year='2024')])
    monkeypatch.setattr(service, 'details', lambda c: Metadata('douban', '2', {'title': '电影', 'year': '2024'},
                                                              {'imdb': 'tt9999999'}, {'douban': 9.9}))
    assert service.automatic_douban_metadata(primary) == []
    assert primary.ratings == {'tmdb': 7.1, 'imdb': 7.2}
    def unavailable(*args, **kwargs):
        raise ScrapeError('数据源暂不可用')
    monkeypatch.setattr(service, 'search', unavailable)
    assert service.automatic_douban_metadata(primary) == []
    assert any('暂不可用' in warning for warning in primary.warnings)


def test_same_original_title_and_year_preserve_cross_source_legacy_ratings(tmp_path):
    video = tmp_path / 'Film.mkv'
    video.touch()
    nfo = video.with_suffix('.nfo')
    nfo.write_text('<movie><title>旧译名</title><originaltitle>Film</originaltitle><year>2024</year>'
                   '<uniqueid type="douban">2</uniqueid><ratings><rating name="douban"><value>8.1</value>'
                   '</rating></ratings></movie>', encoding='utf-8')
    metadata = Metadata('tmdb', '1', {'title': '新译名', 'original_title': 'Film', 'year': '2024'},
                        {'tmdb': '1', 'imdb': 'tt1234567'}, {'tmdb': 7.1, 'imdb': 7.2})
    draft = ScrapeService().build_draft(VideoTarget(video, nfo, existing=True), [metadata])
    assert not draft.replace_identity
    assert draft.fields['ratings'] == {'tmdb': 7.1, 'imdb': 7.2, 'douban': 8.1}


def test_manual_douban_match_adds_to_confirmed_tmdb_without_losing_plot_source(app, tmp_path, monkeypatch):
    from ui.scrape_search_dialog import SearchScrapeDialog
    video = tmp_path / 'Film.mkv'
    video.touch()
    tmdb = Metadata('tmdb', '1', {'title': '电影', 'original_title': 'Film', 'year': '2024', 'plot': 'TMDB简介'},
                    {'tmdb': '1', 'imdb': 'tt1234567'}, {'tmdb': 7.1, 'imdb': 7.2})
    douban = Metadata('douban', '2', {'title': '电影', 'original_title': 'Film', 'year': '2024', 'plot': '豆瓣简介'},
                      {'douban': '2'}, {'douban': 8.1})
    service = ScrapeService(ScrapeSettings(tmdb_api_key='fake'))
    monkeypatch.setattr(service, 'details', lambda candidate: copy.deepcopy(tmdb if candidate.source == 'tmdb' else douban))
    monkeypatch.setattr(service, 'enrich_metadata', lambda metadata: metadata)
    monkeypatch.setattr(service, 'automatic_tmdb_metadata', lambda metadata: [])
    monkeypatch.setattr(service, 'automatic_douban_metadata', lambda metadata: [])
    monkeypatch.setattr(service, 'search', lambda *a, **kw: [Candidate('douban', '2', '电影', 'Film', '2024')])
    window = SearchScrapeDialog([VideoTarget(video, video.with_suffix('.nfo'), '电影', '2024')], service=service)
    window.show()
    window._show_candidates([Candidate('tmdb', '1', '电影', 'Film', '2024')])
    window.candidate_table.selectRow(0)
    until(app, lambda: not window.tasks.busy)
    window.confirm_button.click()
    assert window.douban_match_button.isVisible()
    window.douban_match_button.click()
    until(app, lambda: not window.tasks.busy)
    window.candidate_table.selectRow(0)
    until(app, lambda: not window.tasks.busy)
    window.confirm_button.click()
    assert window.drafts[window._active_key].fields['ratings'] == {'tmdb': 7.1, 'imdb': 7.2, 'douban': 8.1}
    assert window.plot_source_combo.currentData() == 'tmdb'
    assert window.drafts[window._active_key].fields['plot'] == 'TMDB简介'
    window.close()
    until(app, lambda: not window.tasks.busy)


@pytest.mark.parametrize('source', ['tmdb', 'douban'])
def test_new_movie_has_three_ratings_in_one_preview_confirm_and_save(app, tmp_path, monkeypatch, source):
    from ui.scrape_search_dialog import SearchScrapeDialog
    video = tmp_path / 'Film.mkv'
    video.touch()
    target = VideoTarget(video, video.with_suffix('.nfo'), '电影', '2024')
    tmdb = Metadata('tmdb', '1', {'title': '电影', 'original_title': 'Film', 'year': '2024', 'plot': 'TMDB简介'},
                    {'tmdb': '1', 'imdb': 'tt1234567'}, {'tmdb': 7.1})
    douban = Metadata('douban', '2', {'title': '电影', 'original_title': 'Film', 'year': '2024', 'plot': '豆瓣简介'},
                      {'douban': '2'}, {'douban': 8.1})
    service = ScrapeService(ScrapeSettings(tmdb_api_key='fake'))
    monkeypatch.setattr(service, 'details', lambda candidate: copy.deepcopy(tmdb if candidate.source == 'tmdb' else douban))
    def enrich(metadata):
        metadata = copy.deepcopy(metadata)
        metadata.ratings['imdb'] = 7.2
        return metadata
    monkeypatch.setattr(service, 'enrich_metadata', enrich)
    monkeypatch.setattr(service, 'automatic_tmdb_metadata', lambda metadata: [enrich(tmdb)] if metadata.source == 'douban' else [])
    monkeypatch.setattr(service, 'automatic_douban_metadata', lambda metadata: [copy.deepcopy(douban)] if metadata.source == 'tmdb' else [])
    window = SearchScrapeDialog([target], service=service)
    window.show()
    window.source_combo.setCurrentIndex(window.source_combo.findData(source))
    window._show_candidates([Candidate(source, '1' if source == 'tmdb' else '2', '电影', 'Film', '2024')])
    window.candidate_table.selectRow(0)
    until(app, lambda: not window.tasks.busy)
    assert set(window._preview[0].fields['ratings']) == {'tmdb', 'imdb', 'douban'}
    window.metadata_only_check.setChecked(True)
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    assert set(window.drafts[window._active_key].fields['ratings']) == {'tmdb', 'imdb', 'douban'}
    window.save_button.click()
    until(app, lambda: not window.tasks.busy)
    scores = ET.parse(target.nfo_path).getroot().findall('ratings/rating')
    assert {s.get('name') for s in scores} == {'tmdb', 'imdb', 'douban'}
    window.close()
    until(app, lambda: not window.tasks.busy)
