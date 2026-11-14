import pytest

from scraper.scrape_models import Metadata
from scraper.scrape_settings import ScrapeSettings


def test_douban_page_reads_imdb_only_from_main_info(monkeypatch):
    from scraper.rating_enrichment import douban_imdb_id
    from scraper.scrape_http import HttpClient
    html = '''<link rel="canonical" href="https://movie.douban.com/subject/1293177/">
      <div id="info"><span class="pl">IMDb:</span> tt0143145<br></div>
      <div class="recommendations">IMDb: tt9999999</div>'''
    monkeypatch.setattr(HttpClient, 'get_bytes', lambda *a, **k: html.encode())
    assert douban_imdb_id('1293177', ScrapeSettings()) == 'tt0143145'


def test_douban_different_subject_is_rejected(monkeypatch):
    from scraper.rating_enrichment import douban_imdb_id
    from scraper.scrape_http import HttpClient
    from scraper.metadata_sources import ProviderError
    monkeypatch.setattr(HttpClient, 'get_bytes', lambda *a, **k: b'<link rel="canonical" href="https://movie.douban.com/subject/2/"><div id="info">IMDb: tt1234567</div>')
    with pytest.raises(ProviderError, match='不同|身份'):
        douban_imdb_id('1', ScrapeSettings())


def test_confirmed_douban_keeps_fields_and_gets_tmdb_imdb_without_omdb(monkeypatch):
    import scraper.rating_enrichment as module
    from scraper.imdb_provider import ImdbProvider
    from scraper.metadata_sources import TmdbProvider
    from scraper.scrape_service import ScrapeService
    monkeypatch.setattr(module, 'douban_imdb_id', lambda *a: 'tt0143145')
    monkeypatch.setattr(TmdbProvider, 'rating_by_imdb', lambda self, id: ('36643', 6.3, 2800))
    monkeypatch.setattr(ImdbProvider, 'rating', lambda self, id: (6.4, 220000))
    metadata = Metadata('douban', '1293177', {'title': '黑日危机', 'plot': '豆瓣简介'}, ratings={'douban': 7.6})
    result = ScrapeService(ScrapeSettings(tmdb_api_key='test')).enrich_metadata(metadata)
    assert result.fields == metadata.fields
    assert result.source == 'douban' and result.id == metadata.id
    assert result.ids == {'imdb': 'tt0143145', 'tmdb': '36643'}
    assert result.ratings == {'douban': 7.6, 'tmdb': 6.3, 'imdb': 6.4}
    assert result.votes == {'tmdb': 2800, 'imdb': 220000}
    assert metadata.ratings == {'douban': 7.6}


def test_no_shared_identity_never_guesses_by_title(monkeypatch):
    import scraper.rating_enrichment as module
    from scraper.metadata_sources import TmdbProvider
    monkeypatch.setattr(module, 'douban_imdb_id', lambda *a: '')
    monkeypatch.setattr(TmdbProvider, 'search', lambda *a, **k: pytest.fail('不能按同名猜关联'))
    result = module.enrich_ratings(Metadata('douban', '1', {'title': '同名电影'}), ScrapeSettings(tmdb_api_key='test'))
    assert not result.ids and not result.ratings
    assert any('IMDb ID' in warning for warning in result.warnings)


def test_tmdb_find_requires_verified_external_id(monkeypatch):
    from scraper.metadata_sources import ProviderError, TmdbProvider
    responses = {'find/tt0143145': {'movie_results': [{'id': 1}]},
                 'movie/1': {'id': 1, 'imdb_id': 'tt9999999', 'vote_average': 8, 'vote_count': 100}}
    monkeypatch.setattr(TmdbProvider, '_get', lambda self, path, **k: responses[path])
    with pytest.raises(ProviderError, match='不同|冲突'):
        TmdbProvider(ScrapeSettings(tmdb_api_key='test')).rating_by_imdb('tt0143145')


def test_confirm_only_enrichment_shows_three_ratings_and_persists_nfo(app, tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    from scraper.imdb_provider import ImdbProvider
    from scraper.metadata_sources import TmdbProvider
    from scraper.scan_queue import load_queue
    from scraper.scrape_models import Candidate, VideoTarget
    from scraper.scrape_service import ScrapeService
    from tests.scraping.test_scrape_dialog import until
    from ui.scrape_dialog import ScrapeDialog
    video = tmp_path / 'Film.mkv'
    video.touch()
    target = VideoTarget(video, video.with_suffix('.nfo'), '电影')
    service = ScrapeService(ScrapeSettings(tmdb_api_key='test'))
    monkeypatch.setattr(service, 'details', lambda c: Metadata('douban', '123', {'title': '电影', 'plot': '豆瓣简介'}, {'imdb': 'tt0143145'}, {'douban': 7.6}))
    calls = []
    monkeypatch.setattr(TmdbProvider, 'rating_by_imdb', lambda *a: calls.append('tmdb') or ('36643', 6.3, 2800))
    monkeypatch.setattr(ImdbProvider, 'rating', lambda *a: calls.append('imdb') or (6.4, 220000))
    window = ScrapeDialog([target], service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    window.plot_source_combo.setCurrentIndex(1)
    window._show_candidates([Candidate('douban', '123', '电影')])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: not window.tasks.busy)
    assert not calls
    window.confirm_button.click()
    until(app, lambda: not window.tasks.busy)
    assert calls == ['tmdb', 'imdb']
    assert '6.3' in window.rating_label.text() and '6.4' in window.rating_label.text() and '7.6' in window.rating_label.text()
    window.metadata_only_check.setChecked(True)
    window.save_button.click()
    until(app, lambda: not window.tasks.busy)
    xml = ET.parse(target.nfo_path).getroot()
    assert xml.findtext("ratings/rating[@name='imdb']/value") == '6.4'
    assert xml.findtext("ratings/rating[@name='tmdb']/value") == '6.3'
    assert xml.findtext("ratings/rating[@name='douban']/value") == '7.6'
    assert xml.findtext("ratings/rating[@name='imdb']/votes") == '220000'
    assert load_queue()[0].existing
    window.close()


def test_late_rating_enrichment_does_not_confirm_new_candidate(app, tmp_path):
    import threading
    from scraper.scrape_models import Candidate, VideoTarget
    from tests.scraping.test_scrape_dialog import FakeService, until
    from ui.scrape_dialog import ScrapeDialog
    started, gate = threading.Event(), threading.Event()
    service = FakeService()
    def enrich(metadata):
        started.set()
        gate.wait(3)
        return metadata
    service.enrich_metadata = enrich
    target = VideoTarget(tmp_path / 'a.mkv', tmp_path / 'a.nfo', existing=True)
    window = ScrapeDialog([target], mode='existing', service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    try:
        window._show_candidates([Candidate('tmdb', 'old', '旧候选')])
        window.candidate_list.setCurrentRow(0)
        until(app, lambda: not window.tasks.busy)
        window.confirm_button.click()
        until(app, started.is_set)
        window._show_candidates([Candidate('tmdb', 'new', '新候选')])
        window.candidate_list.setCurrentRow(0)
        until(app, lambda: window._preview is not None and window._preview[0].fields['title'] == '新候选')
        gate.set()
        until(app, lambda: not window.tasks.busy)
        assert not window.drafts
        assert window._preview[0].fields['title'] == '新候选'
    finally:
        gate.set()
        until(app, lambda: not window.tasks.busy)
        window.close()


def test_tmdb_matching_button_preserves_confirmed_douban_and_searches_original_title(app, tmp_path):
    from scraper.scrape_models import Candidate, VideoTarget
    from tests.scraping.test_scrape_dialog import FakeService, until
    from ui.scrape_dialog import ScrapeDialog
    service = FakeService()
    service.details = lambda c: Metadata('douban', '123', {'title': '中文片名', 'original_title': 'Original Film', 'year': '1999'}, ratings={'douban': 7.6})
    target = VideoTarget(tmp_path / 'a.mkv', tmp_path / 'a.nfo', existing=True)
    window = ScrapeDialog([target], mode='existing', service=service)
    window.show()
    until(app, lambda: not window.tasks.busy)
    window._show_candidates([Candidate('douban', '123', '中文片名')])
    window.candidate_list.setCurrentRow(0)
    until(app, lambda: not window.tasks.busy)
    window.confirm_button.click()
    assert window.tmdb_match_button.isVisible()
    window.tmdb_match_button.click()
    until(app, lambda: not window.tasks.busy)
    assert window._confirmed_metadata[window._active_key][0].source == 'douban'
    assert ('search', 'tmdb', 'Original Film', '1999', 1) in service.calls
    window.close()


from tests.scraping.test_scrape_dialog import app


def test_enrichment_does_not_accept_external_poster_as_new_snapshot(app, tmp_path, monkeypatch):
    import threading
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_models import Candidate, VideoTarget
    from tests.scraping.test_scrape_dialog import until
    from ui.scrape_dialog import ScrapeDialog
    gate, started = threading.Event(), threading.Event()
    video = tmp_path / 'a.mkv'; video.touch()
    poster = tmp_path / 'a-poster.jpg'; poster.write_bytes(b'original')
    service = ScrapeService(ScrapeSettings())
    monkeypatch.setattr(service, 'details', lambda c: Metadata('tmdb', '1', {'title': '电影'}))
    def enrich(metadata):
        started.set(); gate.wait(3); return metadata
    monkeypatch.setattr(service, 'enrich_metadata', enrich)
    window = ScrapeDialog([VideoTarget(video, video.with_suffix('.nfo'))], service=service)
    window.show(); until(app, lambda: not window.tasks.busy)
    try:
        window._show_candidates([Candidate('tmdb', '1', '电影')]); window.candidate_list.setCurrentRow(0)
        until(app, lambda: not window.tasks.busy)
        window.confirm_button.click(); until(app, started.is_set)
        poster.write_bytes(b'external change')
        gate.set(); until(app, lambda: not window.tasks.busy)
        assert not window.drafts
        assert '冲突' in window.status_label.text()
        assert poster.read_bytes() == b'external change'
    finally:
        gate.set(); until(app, lambda: not window.tasks.busy); window.close()


def test_plot_change_invalidates_pending_rating_confirmation(app, tmp_path):
    import threading
    from scraper.scrape_models import Candidate, VideoTarget
    from tests.scraping.test_scrape_dialog import FakeService, until
    from ui.scrape_dialog import ScrapeDialog
    gate, started = threading.Event(), threading.Event()
    service = FakeService()
    def enrich(metadata):
        started.set(); gate.wait(3); return metadata
    service.enrich_metadata = enrich
    target = VideoTarget(tmp_path / 'a.mkv', tmp_path / 'a.nfo', existing=True)
    window = ScrapeDialog([target], mode='existing', service=service)
    window.show(); until(app, lambda: not window.tasks.busy)
    tmdb = Metadata('tmdb', '1', {'title': '电影', 'plot': 'TMDB 简介'})
    douban = Metadata('douban', '2', {'title': '电影', 'plot': '豆瓣简介'})
    from scraper.scrape_models import ScrapeDraft
    draft = ScrapeDraft(target, fields={'title': '电影', 'plot': 'TMDB 简介'})
    window._preview = (draft, [tmdb, douban]); window._render_draft(draft)
    try:
        window._confirm(); until(app, started.is_set)
        window.plot_source_combo.setCurrentIndex(1)
        until(app, lambda: window._preview is not None and window._preview[0].fields['plot'] == '豆瓣简介')
        gate.set(); until(app, lambda: not window.tasks.busy)
        assert not window.drafts
        assert window._preview[0].fields['plot'] == '豆瓣简介'
    finally:
        gate.set(); until(app, lambda: not window.tasks.busy); window.close()
