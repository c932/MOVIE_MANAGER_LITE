from pathlib import Path
from PyQt6.QtCore import Qt
from tests.scraping.test_scrape_dialog import app, until, FakeService
from scraper.scrape_models import VideoTarget


def test_search_uses_only_selected_existing_movies_and_no_global_queue(app, tmp_path):
    from ui.scrape_search_dialog import SearchScrapeDialog
    from scraper.scan_queue import save_queue, load_queue
    other = VideoTarget(tmp_path / 'other.mkv', tmp_path / 'other.nfo', '其他电影')
    save_queue([other])
    target = VideoTarget(tmp_path / 'chosen.mkv', tmp_path / 'chosen.nfo', '选中电影', '2024', True)
    dialog = SearchScrapeDialog([target], service=FakeService())
    dialog.show()
    until(app, lambda: not dialog.tasks.busy)
    assert dialog.target_list.count() == 1 and dialog.current_target.title == '选中电影'
    dialog.search()
    until(app, lambda: not dialog.tasks.busy)
    assert dialog.candidate_table.rowCount() == 1
    dialog.candidate_table.selectRow(0)
    until(app, lambda: not dialog.tasks.busy)
    assert dialog._preview is not None
    assert load_queue() == [other]
    dialog.close()
    until(app, lambda: not dialog.tasks.busy)


def test_editor_cancel_and_edit_save_refresh_signal(app, tmp_path):
    from ui.metadata_editor import MetadataEditorDialog
    from tests.scraping.test_management import movie_files
    nfo = movie_files(tmp_path)
    before = nfo.read_bytes()
    editor = MetadataEditorDialog(str(nfo))
    editor.show()
    until(app, lambda: not editor.tasks.busy)
    editor.fields['title'].setText('取消的标题')
    editor.reject()
    until(app, lambda: not editor.tasks.busy)
    assert nfo.read_bytes() == before
    editor = MetadataEditorDialog(str(nfo))
    paths = []
    editor.saved.connect(paths.extend)
    editor.show()
    until(app, lambda: not editor.tasks.busy)
    editor.fields['title'].setText('修改的标题')
    editor.save()
    until(app, lambda: not editor.tasks.busy)
    assert paths == [str(nfo)]
    assert '修改的标题' in nfo.read_text(encoding='utf-8')


def test_search_reports_write_failure_for_job_not_current_navigation(app, tmp_path):
    from ui.scrape_search_dialog import SearchScrapeDialog
    from scraper.scrape_models import ScrapeDraft
    a = VideoTarget(tmp_path / 'A.mkv', tmp_path / 'A.nfo', 'A')
    b = VideoTarget(tmp_path / 'B.mkv', tmp_path / 'B.nfo', 'B')
    dialog = SearchScrapeDialog([a, b], service=FakeService())
    dialog.show()
    errors = []
    dialog.operation_failed.connect(lambda path, message: errors.append(path))
    dialog._write_active = ('save', str(a.video_path).casefold(), ScrapeDraft(a), set(), False, True)
    dialog.target_list.setCurrentRow(1)
    dialog._on_error('write', 0, '写入失败')
    assert errors == [str(a.nfo_path)]
    dialog.close()
    until(app, lambda: not dialog.tasks.busy)


def test_search_next_movie_follows_search_source_and_repeated_results_can_select(app, tmp_path):
    from ui.scrape_search_dialog import SearchScrapeDialog
    from scraper.scrape_models import Candidate
    targets = [VideoTarget(tmp_path / f'{name}.mkv', tmp_path / f'{name}.nfo', name) for name in ['A', 'B']]
    dialog = SearchScrapeDialog(targets, service=FakeService())
    dialog.show()
    dialog.source_combo.setCurrentIndex(dialog.source_combo.findData('douban'))
    dialog.target_list.setCurrentRow(1)
    assert dialog.plot_source_combo.currentData() == 'douban'
    candidates = [Candidate('douban', '1', 'B')]
    dialog._show_candidates(candidates)
    dialog.candidate_table.selectRow(0)
    until(app, lambda: not dialog.tasks.busy)
    dialog._show_candidates(candidates)
    assert not dialog.candidate_table.selectionModel().selectedRows()
    dialog.candidate_table.selectRow(0)
    until(app, lambda: not dialog.tasks.busy)
    assert dialog._preview is not None
    dialog.close()
    until(app, lambda: not dialog.tasks.busy)


def test_real_service_search_confirm_save_refreshes_management_row(app, tmp_path, monkeypatch):
    from ui.scrape_search_dialog import SearchScrapeDialog
    from ui.scrape_manager import ScrapeManagerDialog
    from scraper.scrape_service import ScrapeService
    from scraper.scrape_settings import ScrapeSettings
    from parsers.nfo_parser import NFOParser
    from tests.scraping.test_sources import transport, movie_record
    video = tmp_path / 'New.2024.mkv'
    video.touch()
    target = VideoTarget(video, video.with_suffix('.nfo'), 'New', '2024')
    record = dict(movie_record(17, title='新电影'), vote_average=8.2, vote_count=120)
    record.pop('poster_path')
    transport(monkeypatch, [{'results': [record]}, record, {'imdb_id': None},
                           {'cast': [], 'crew': []}, {'posters': []}])
    service = ScrapeService(ScrapeSettings(tmdb_api_key='fake'))
    monkeypatch.setattr(service, 'enrich_metadata', lambda metadata: metadata)
    manager = ScrapeManagerDialog([target], service=service)
    manager.show()
    until(app, lambda: not manager.tasks.busy)
    dialog = SearchScrapeDialog([target], service=service)
    dialog.saved.connect(manager._child_saved)
    dialog.show()
    dialog.search()
    until(app, lambda: not dialog.tasks.busy)
    dialog.candidate_table.selectRow(0)
    until(app, lambda: not dialog.tasks.busy)
    dialog.metadata_only_check.setChecked(True)
    dialog.confirm_button.click()
    until(app, lambda: not dialog.tasks.busy)
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    until(app, lambda: not dialog.tasks.busy and not manager.tasks.busy)
    parsed = NFOParser.parse(str(target.nfo_path))
    assert parsed.title == '新电影' and parsed.ratings['tmdb'] == 8.2
    assert manager.model.rows[0].outcome == '已保存'
    assert not manager.model.rows[0].is_new
    dialog.close()
    manager.close()
    until(app, lambda: not dialog.tasks.busy and not manager.tasks.busy)


def test_editor_preserves_unmodified_legacy_formats(app, tmp_path):
    from ui.metadata_editor import MetadataEditorDialog
    from tests.scraping.test_management import movie_files
    import xml.etree.ElementTree as ET
    nfo = movie_files(tmp_path)
    root = ET.parse(nfo).getroot()
    ET.SubElement(root, 'premiered').text = '2024/01/02'
    ET.SubElement(root, 'runtime').text = '2h'
    ET.SubElement(root, 'uniqueid', {'type': 'tmdb'}).text = 'legacy-invalid-id'
    nfo.write_bytes(ET.tostring(root, encoding='utf-8'))
    editor = MetadataEditorDialog(str(nfo))
    editor.show()
    until(app, lambda: not editor.tasks.busy)
    editor.fields['title'].setText('仅改标题')
    editor.save()
    until(app, lambda: not editor.tasks.busy)
    assert not editor.isVisible()
    root = ET.parse(nfo).getroot()
    assert root.findtext('title') == '仅改标题'
    assert root.findtext('runtime') == '2h'
    assert root.findtext('premiered') == '2024/01/02'
    assert root.findtext("uniqueid[@type='tmdb']") == 'legacy-invalid-id'
