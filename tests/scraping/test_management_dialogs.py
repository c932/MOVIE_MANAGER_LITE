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
