"""只使用临时影库验证扫描分类、授权重建及事务恢复。"""
import hashlib
import io
import os
import stat
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from scraper.media_discovery import discover_videos
from scraper.scrape_models import Artwork, Metadata, ScrapeError
from scraper.scrape_service import ScrapeService


BB_CODE = '[URL=https://example.test][IMG]发布图片[/IMG][/URL]\r\n论坛发布说明'.encode('utf-8')


def library(tmp_path, content=BB_CODE):
    video = tmp_path / '乐高蝙蝠侠大电影.2017.mkv'
    video.touch()
    video.with_suffix('.nfo').write_bytes(content)
    return video


def preview(tmp_path, content=BB_CODE):
    library(tmp_path, content)
    target = discover_videos([tmp_path])[0]
    return ScrapeService().build_draft(target, [Metadata('tmdb', '324849', {'title': '乐高蝙蝠侠大电影', 'year': '2017'})])


@pytest.mark.parametrize(('content', 'kind'), [
    (BB_CODE, 'not_metadata'),
    (b'<tvshow><title>Wrong</title></tvshow>', 'not_metadata'),
    (b'<movie><title>fake</title><custom>fake</custom>', 'invalid_xml'),
    (b'', 'invalid_xml'),
    (b'\xef\xbb\xbf \r\n', 'invalid_xml'),
    (b'\xff\xfe\xff', 'invalid_xml'),
    (b'<?xml version="1.0" encoding="unknown-encoding"?><movie/>', 'invalid_xml'),
    (b'<?xml version="1.0" encoding="utf-8"?><movie><title>\xff</title></movie>', 'invalid_xml'),
])
def test_scan_classifies_rebuildable_nfo_without_changing_bytes(tmp_path, content, kind):
    from scraper.scrape_models import can_rebuild_nfo
    video = library(tmp_path, content)
    target = discover_videos([tmp_path])[0]
    assert target.error_kind == kind
    assert target.error_detail and target.error
    assert target.existing and can_rebuild_nfo(target)
    assert target.nfo_fingerprint == hashlib.sha256(content).hexdigest()
    assert video.with_suffix('.nfo').read_bytes() == content


@pytest.mark.parametrize('content', [
    '<movie><title>旧片</title><year>2017</year></movie>'.encode('utf-8-sig'),
    '<movie><title>旧片</title><year>2017</year></movie>'.encode('utf-16'),
    b'<?xml version="1.0" encoding="iso-8859-1"?><movie><title>Caf\xe9</title></movie>',
])
def test_scan_preserves_normal_legacy_xml(tmp_path, content):
    library(tmp_path, content)
    target = discover_videos([tmp_path])[0]
    assert not target.error and target.error_kind == '' and target.error_detail == ''
    assert target.title in {'旧片', 'Café'}


@pytest.mark.parametrize('save_api', ['service', 'commit'])
def test_unreadable_nfo_has_specific_reason_and_allows_only_preview(tmp_path, monkeypatch, save_api):
    from scraper.scrape_models import can_rebuild_nfo
    video = library(tmp_path)
    nfo = video.with_suffix('.nfo')
    real = Path.open
    def denied(path, *args, **kwargs):
        if path == nfo:
            raise PermissionError('模拟 NAS 拒绝访问')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    target = discover_videos([tmp_path])[0]
    assert target.error_kind == 'unreadable'
    assert '模拟 NAS 拒绝访问' in target.error_detail
    assert not can_rebuild_nfo(target)
    draft = ScrapeService().build_draft(target, [Metadata('tmdb', '1', {'title': '预览'})])
    assert draft.fields['title'] == '预览'
    assert any('无法读取' in text for text in draft.warnings)
    draft.confirmed = draft.rebuild_nfo = True
    with pytest.raises(ScrapeError, match='读取|访问'):
        if save_api == 'service':
            ScrapeService().save(draft, metadata_only=True)
        else:
            from scraper.scrape_persistence import commit_draft
            commit_draft(draft, metadata_only=True)


@pytest.mark.parametrize('save_api', ['service', 'commit'])
def test_path_conflict_overrides_rebuildable_classification(tmp_path, save_api):
    from scraper.scrape_models import can_rebuild_nfo
    video = library(tmp_path)
    video.with_suffix('.mp4').touch()
    targets = discover_videos([tmp_path])
    for target in targets:
        assert target.error_kind == 'path_conflict'
        assert not can_rebuild_nfo(target)
        draft = ScrapeService().build_draft(target, [Metadata('tmdb', '1', {'title': '预览'})])
        draft.confirmed = draft.rebuild_nfo = True
        with pytest.raises(ScrapeError, match='冲突'):
            if save_api == 'service':
                ScrapeService().save(draft, metadata_only=True)
            else:
                from scraper.scrape_persistence import commit_draft
                commit_draft(draft, metadata_only=True)


@pytest.mark.parametrize('content', [BB_CODE, b'<movie><title>fake</title><custom>fake</custom>'])
def test_rebuild_requires_explicit_opt_in_and_confirmation_then_backs_up_bytes(tmp_path, content):
    from scraper.scrape_persistence import commit_draft
    draft = preview(tmp_path, content)
    assert not draft.rebuild_nfo and not draft.confirmed
    assert any('备份' in text and '重建' in text for text in draft.warnings)
    draft.confirmed = True
    with pytest.raises(ScrapeError):
        commit_draft(draft, metadata_only=True)
    draft.rebuild_nfo, draft.confirmed = True, False
    with pytest.raises(ScrapeError, match='确认'):
        commit_draft(draft, metadata_only=True)
    assert draft.target.nfo_path.read_bytes() == content
    assert not list(tmp_path.glob('*.mml-backup-*'))
    draft.confirmed = True
    movie = commit_draft(draft, metadata_only=True)
    root = ET.parse(draft.target.nfo_path).getroot()
    assert root.tag == 'movie' and root.findtext('title') == '乐高蝙蝠侠大电影'
    assert root.find('custom') is None
    assert root.findtext("uniqueid[@type='tmdb']") == '324849'
    assert [p.read_bytes() for p in tmp_path.glob('*.mml-backup-*')] == [content]
    assert movie.title == '乐高蝙蝠侠大电影'
    assert draft.target.error == draft.target.error_kind == draft.target.error_detail == ''
    assert draft.target.version_captured
    assert draft.target.nfo_fingerprint == hashlib.sha256(draft.target.nfo_path.read_bytes()).hexdigest()
    assert draft.rebuild_nfo is False
    assert not any('原 NFO' in text for text in draft.warnings)
    # 后续保存应按正常旧电影补缺，不能再次空树覆盖。
    commit_draft(draft, metadata_only=True)


def test_service_metadata_only_rebuild_does_not_parse_old_nfo_or_borrow_art(tmp_path):
    video = library(tmp_path)
    (tmp_path / 'poster.jpg').write_bytes(b'other-movie')
    (tmp_path / 'fanart.jpg').write_bytes(b'other-movie')
    (tmp_path / (video.stem + '-poster.jpg')).write_bytes(b'stale')
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    movie = ScrapeService().save(draft, metadata_only=True)
    assert movie.poster_path == movie.fanart_path == ''
    root = ET.parse(draft.target.nfo_path).getroot()
    assert root.find("thumb[@aspect='poster']") is not None
    assert root.find('fanart') is not None


def png(color):
    stream = io.BytesIO()
    Image.new('RGB', (10, 15), color).save(stream, 'PNG')
    return stream.getvalue()


def test_rebuild_downloads_selected_poster_even_with_unrelated_local_art(tmp_path, monkeypatch):
    from scraper.scrape_http import HttpClient
    video = library(tmp_path)
    poster = tmp_path / (video.stem + '-poster.jpg')
    poster.write_bytes(png('blue'))
    (tmp_path / 'poster.jpg').write_bytes(png('blue'))
    draft = preview(tmp_path)
    draft.poster = Artwork('https://image.tmdb.org/t/p/test.jpg')
    draft.confirmed = draft.rebuild_nfo = True
    monkeypatch.setattr(HttpClient, 'get_bytes', lambda *a, **k: png('red'))
    movie = ScrapeService().save(draft)
    assert movie.poster_path == str(poster)
    with Image.open(poster) as image:
        assert image.getpixel((0, 0))[0] > 240


@pytest.mark.parametrize('phase', ['before_build', 'before_save', 'during_backup'])
def test_rebuild_refuses_changed_original_even_with_same_stamp(tmp_path, monkeypatch, phase):
    import scraper.scrape_persistence as persistence
    video = library(tmp_path)
    target = discover_videos([tmp_path])[0]
    path = target.nfo_path
    original_stat = path.stat()
    changed = b'X' * len(BB_CODE)
    def mutate():
        path.write_bytes(changed)
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    service = ScrapeService()
    metadata = [Metadata('tmdb', '1', {'title': '新片'})]
    if phase == 'before_build':
        mutate()
        with pytest.raises(ScrapeError, match='改变|冲突'):
            service.build_draft(target, metadata)
    else:
        draft = service.build_draft(target, metadata)
        draft.confirmed = draft.rebuild_nfo = True
        if phase == 'before_save':
            mutate()
        else:
            real = persistence._atomic_write
            def backup_then_mutate(p, data):
                real(p, data)
                if '.mml-backup-' in p.name:
                    mutate()
            monkeypatch.setattr(persistence, '_atomic_write', backup_then_mutate)
        with pytest.raises(ScrapeError):
            service.save(draft, metadata_only=True)
    assert video.with_suffix('.nfo').read_bytes() == changed


@pytest.mark.parametrize('failure', ['backup', 'poster', 'nfo'])
def test_rebuild_write_failure_restores_original_and_poster(tmp_path, monkeypatch, failure):
    import scraper.scrape_persistence as persistence
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    poster = tmp_path / (draft.target.video_path.stem + '-poster.jpg')
    original_poster = png('blue')
    poster.write_bytes(original_poster)
    persistence.snapshot_files(draft)
    real = persistence._atomic_write
    def fail(p, data):
        if ((failure == 'backup' and '.mml-backup-' in p.name)
                or (failure == 'poster' and p == poster and data != original_poster)
                or (failure == 'nfo' and p == draft.target.nfo_path and data != BB_CODE)):
            raise OSError('模拟 NAS 写入失败')
        return real(p, data)
    monkeypatch.setattr(persistence, '_atomic_write', fail)
    with pytest.raises(ScrapeError, match='保存失败'):
        persistence.commit_draft(draft, poster_bytes=png('red'))
    assert draft.target.nfo_path.read_bytes() == BB_CODE
    assert poster.read_bytes() == original_poster
    assert draft.target.error and draft.target.error_kind == 'not_metadata'
    if failure != 'backup':
        assert BB_CODE in [p.read_bytes() for p in tmp_path.glob('*.mml-backup-*')]


def test_rebuild_readback_failure_rolls_back_nfo_and_new_poster(tmp_path, monkeypatch):
    import scraper.scrape_persistence as persistence
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    poster = tmp_path / (draft.target.video_path.stem + '-poster.jpg')
    real_parse = persistence.NFOParser.parse
    monkeypatch.setattr(persistence.NFOParser, 'parse', lambda *a, **k: None)
    with pytest.raises(ScrapeError):
        persistence.commit_draft(draft, poster_bytes=png('red'))
    assert draft.target.nfo_path.read_bytes() == BB_CODE
    assert not poster.exists()
    assert draft.target.error_kind == 'not_metadata' and draft.rebuild_nfo
    assert BB_CODE in [p.read_bytes() for p in tmp_path.glob('*.mml-backup-*')]
    monkeypatch.setattr(persistence.NFOParser, 'parse', real_parse)
    assert persistence.commit_draft(draft, poster_bytes=png('red')).title == '乐高蝙蝠侠大电影'


def test_scan_progress_reports_traversal_parse_and_completion(tmp_path):
    from scraper.scrape_models import ScanProgress
    scan_root = tmp_path / 'library'
    (scan_root / 'sub').mkdir(parents=True)
    library(scan_root / 'sub')
    (scan_root / 'other.mp4').touch()
    events = []
    targets = discover_videos([scan_root, scan_root], progress=events.append)
    assert all(isinstance(event, ScanProgress) for event in events)
    traversal = [event for event in events if event.stage == '扫描目录']
    assert [event.current for event in traversal] == [1, 2]
    assert all(event.total == 0 for event in traversal)
    assert traversal[-1].found >= 1
    parsed = [event for event in events if event.stage == '解析 NFO']
    assert [event.current for event in parsed] == [1, 2]
    assert all(event.total == 2 and event.found == 2 for event in parsed)
    assert [event.directory for event in parsed] == [str(t.video_path.parent) for t in targets]
    assert events[-1].stage == '扫描完成' and events[-1].found == 2


def test_empty_scan_reports_completion(tmp_path):
    events = []
    assert discover_videos([tmp_path], progress=events.append) == []
    assert events[-1].stage == '扫描完成'
    assert events[-1].current == events[-1].total == events[-1].found == 0


@pytest.mark.parametrize('stage', ['扫描目录', '解析 NFO', '扫描完成'])
def test_progress_callback_exception_propagates_without_reclassification(tmp_path, stage):
    library(tmp_path)
    error = OSError('调用方回调异常')
    def callback(event):
        if event.stage == stage:
            raise error
    with pytest.raises(OSError) as raised:
        discover_videos([tmp_path], progress=callback)
    assert raised.value is error


def test_cancel_during_progress_never_emits_completion(tmp_path):
    library(tmp_path)
    events = []
    def callback(event):
        events.append(event)
    with pytest.raises(ScrapeError, match='取消'):
        discover_videos([tmp_path], progress=callback, check_cancelled=lambda: bool(events))
    assert events and all(event.stage != '扫描完成' for event in events)


@pytest.mark.skipif(os.name != 'nt', reason='Windows 只读属性与替换行为')
@pytest.mark.parametrize('asset', ['nfo', 'poster'])
@pytest.mark.parametrize('save_api', ['service', 'commit'])
def test_readonly_target_stops_before_download_backup_or_write(tmp_path, monkeypatch, asset, save_api):
    import scraper.scrape_persistence as persistence
    from scraper.scrape_http import HttpClient
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    draft.poster = Artwork('https://image.tmdb.org/t/p/test.jpg')
    poster = persistence.poster_path(draft)
    poster.write_bytes(png('blue'))
    persistence.snapshot_files(draft)
    protected = draft.target.nfo_path if asset == 'nfo' else poster
    original = protected.read_bytes()
    downloads = []
    monkeypatch.setattr(HttpClient, 'get_bytes', lambda *a, **k: downloads.append(True) or png('red'))
    protected.chmod(stat.S_IREAD)
    try:
        with pytest.raises(ScrapeError, match='只读') as raised:
            if save_api == 'service':
                ScrapeService().save(draft)
            else:
                persistence.commit_draft(draft, poster_bytes=png('red'))
        assert str(protected) in str(raised.value)
        assert '取消' in str(raised.value)
        assert not downloads
        assert protected.read_bytes() == original
        assert draft.target.nfo_path.read_bytes() == BB_CODE
        assert not list(tmp_path.glob('*.mml-backup-*'))
    finally:
        protected.chmod(stat.S_IREAD | stat.S_IWRITE)
    # 用户解除只读后，可沿用已确认草稿直接重试。
    assert ScrapeService().save(draft).title == '乐高蝙蝠侠大电影'


@pytest.mark.parametrize('phase', ['backup', 'nfo'])
def test_save_error_retains_phase_cause_and_failed_path(tmp_path, monkeypatch, phase):
    import scraper.scrape_persistence as persistence
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    real_write = persistence._atomic_write
    def fail(path, data):
        if (phase == 'backup' and '.mml-backup-' in path.name) or (phase == 'nfo' and path == draft.target.nfo_path):
            raise PermissionError(13, '模拟共享目录拒绝写入', str(path))
        real_write(path, data)
    monkeypatch.setattr(persistence, '_atomic_write', fail)
    with pytest.raises(ScrapeError) as raised:
        persistence.commit_draft(draft, metadata_only=True)
    message = str(raised.value)
    assert ('备份原文件' if phase == 'backup' else '写入 NFO') in message
    assert '拒绝' in message
    assert str(draft.target.nfo_path) in message
    assert draft.target.nfo_path.read_bytes() == BB_CODE
