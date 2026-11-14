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
@pytest.mark.parametrize('save_api', ['service', 'commit'])
def test_readonly_poster_stops_before_download_backup_or_write(tmp_path, monkeypatch, save_api):
    import scraper.scrape_persistence as persistence
    from scraper.scrape_http import HttpClient
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    draft.poster = Artwork('https://image.tmdb.org/t/p/test.jpg')
    poster = persistence.poster_path(draft)
    poster.write_bytes(png('blue'))
    persistence.snapshot_files(draft)
    protected = poster
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


def is_readonly(path):
    return bool(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)


@pytest.fixture(params=['commit', 'douban'])
def readonly_nfo_operation(tmp_path, request):
    if os.name != 'nt':
        pytest.skip('Windows 只读属性与替换行为')
    import scraper.scrape_persistence as persistence
    if request.param == 'commit':
        draft = preview(tmp_path)
        draft.confirmed = draft.rebuild_nfo = True
        path, original = draft.target.nfo_path, BB_CODE
        def save():
            return persistence.commit_draft(draft, metadata_only=True)
    else:
        original = '<?xml version="1.0" encoding="utf-16"?><movie><!--原始格式--><title>旧片</title><plot>保留简介</plot></movie>'.encode('utf-16')
        path = library(tmp_path, original).with_suffix('.nfo')
        def save():
            return persistence.update_douban_nfo(str(path), '123', {'rating': '8.2', 'rating_count': 42},
                                                 expected_fingerprint=hashlib.sha256(original).hexdigest())
    path.chmod(stat.S_IREAD)
    try:
        yield path, original, save
    finally:
        if path.exists():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_readonly_check_opt_in_never_changes_attributes(readonly_nfo_operation):
    from scraper.scrape_persistence import ensure_writable_file
    path, original, _ = readonly_nfo_operation
    with pytest.raises(ScrapeError, match='只读'):
        ensure_writable_file(path, 'NFO')
    ensure_writable_file(path, 'NFO', allow_readonly=True)
    assert is_readonly(path)
    assert path.read_bytes() == original
    assert not list(path.parent.glob('*.mml-backup-*'))


def test_readonly_nfo_replaced_only_after_exact_backup(readonly_nfo_operation, monkeypatch):
    import scraper.scrape_persistence as persistence
    path, original, save = readonly_nfo_operation
    real_chmod = Path.chmod
    def checked_chmod(p, mode, *args, **kwargs):
        if p == path and mode & stat.S_IWRITE:
            assert [b.read_bytes() for b in path.parent.glob('*.mml-backup-*')] == [original]
            assert p.read_bytes() == original
        return real_chmod(p, mode, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'chmod', checked_chmod)
        assert save()
    assert not is_readonly(path)
    assert path.read_bytes() != original
    root = ET.parse(path).getroot()
    if root.find('ratings') is not None:
        assert root.findtext("ratings/rating[@name='douban']/value") == '8.2'
        assert root.findtext('plot') == '保留简介'
    else:
        assert root.findtext('title') == '乐高蝙蝠侠大电影'
    assert [b.read_bytes() for b in path.parent.glob('*.mml-backup-*')] == [original]


@pytest.mark.skipif(os.name != 'nt', reason='Windows 只读属性与替换行为')
def test_readonly_valid_nfo_merge_preserves_fields_and_original_backup(tmp_path):
    import scraper.scrape_persistence as persistence
    original = '<movie><title>旧片</title><plot>保留简介</plot><custom>保留标签</custom></movie>'.encode('utf-16')
    library(tmp_path, original)
    draft = ScrapeService().build_draft(discover_videos([tmp_path])[0],
                                       [Metadata('tmdb', '324849', {'title': '旧片', 'year': '2017'})])
    draft.confirmed = True
    path = draft.target.nfo_path
    path.chmod(stat.S_IREAD)
    try:
        movie = persistence.commit_draft(draft, metadata_only=True)
        assert movie.title == '旧片'
        assert not is_readonly(path)
        root = ET.parse(path).getroot()
        assert root.findtext('plot') == '保留简介'
        assert root.findtext('custom') == '保留标签'
        assert root.findtext('year') == '2017'
        assert [b.read_bytes() for b in tmp_path.glob('*.mml-backup-*')] == [original]
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize('failure', ['backup', 'replace', 'chmod', 'chmod_after_change', 'readback'])
def test_readonly_nfo_failure_restores_bytes_and_attribute(readonly_nfo_operation, monkeypatch, failure):
    import scraper.scrape_persistence as persistence
    path, original, save = readonly_nfo_operation
    real_write, real_chmod, real_replace = persistence._atomic_write, Path.chmod, os.replace
    def write(p, data):
        if failure == 'backup' and '.mml-backup-' in p.name:
            raise PermissionError('模拟备份失败')
        return real_write(p, data)
    def chmod(p, mode, *args, **kwargs):
        if p == path and mode & stat.S_IWRITE and failure in {'chmod', 'chmod_after_change'}:
            if failure == 'chmod_after_change':
                real_chmod(p, mode, *args, **kwargs)
            raise PermissionError('模拟属性设置失败')
        if p == path and mode & stat.S_IWRITE and failure == 'backup':
            pytest.fail('备份失败不得解除只读')
        return real_chmod(p, mode, *args, **kwargs)
    def replace(src, dst):
        if failure == 'replace' and Path(dst) == path:
            raise PermissionError('模拟原子替换失败')
        return real_replace(src, dst)
    with monkeypatch.context() as patch:
        patch.setattr(persistence, '_atomic_write', write)
        patch.setattr(Path, 'chmod', chmod)
        patch.setattr(os, 'replace', replace)
        if failure == 'readback':
            patch.setattr(persistence.NFOParser, 'parse', lambda *a, **k: None)
            real_xml = persistence._xml
            def xml(p):
                if p == path and p.read_bytes() != original:
                    raise ScrapeError('模拟回读失败')
                return real_xml(p)
            patch.setattr(persistence, '_xml', xml)
        with pytest.raises(ScrapeError):
            save()
    assert path.read_bytes() == original
    assert is_readonly(path)
    assert not list(path.parent.glob('*.tmp'))
    if failure != 'backup':
        assert [b.read_bytes() for b in path.parent.glob('*.mml-backup-*')] == [original]
    # 回滚后仍可使用同一已确认操作重试。
    assert save()
    assert not is_readonly(path)


@pytest.mark.parametrize('external_readonly', [False, True])
def test_readonly_nfo_backup_conflict_never_changes_external_attributes(readonly_nfo_operation, monkeypatch, external_readonly):
    import scraper.scrape_persistence as persistence
    path, original, save = readonly_nfo_operation
    external = b'Changed externally'
    real_write, real_chmod = persistence._atomic_write, Path.chmod
    def backup_then_change(p, data):
        real_write(p, data)
        if '.mml-backup-' in p.name:
            real_chmod(path, stat.S_IREAD | stat.S_IWRITE)
            path.write_bytes(external)
            if external_readonly:
                real_chmod(path, stat.S_IREAD)
    def forbidden_chmod(p, *args, **kwargs):
        if p == path:
            pytest.fail('冲突时不得修改外部文件属性')
        return real_chmod(p, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(persistence, '_atomic_write', backup_then_change)
        patch.setattr(Path, 'chmod', forbidden_chmod)
        with pytest.raises(ScrapeError, match='改变|冲突'):
            save()
    assert path.read_bytes() == external
    assert is_readonly(path) is external_readonly
    assert [b.read_bytes() for b in path.parent.glob('*.mml-backup-*')] == [original]


@pytest.mark.skipif(os.name != 'nt', reason='Windows 只读属性与替换行为')
@pytest.mark.parametrize('existing_poster', [False, True])
@pytest.mark.parametrize('failure', ['poster', 'nfo', 'readback', 'nfo_conflict'])
def test_readonly_nfo_with_poster_failure_restores_transaction(tmp_path, monkeypatch, existing_poster, failure):
    import scraper.scrape_persistence as persistence
    draft = preview(tmp_path)
    draft.confirmed = draft.rebuild_nfo = True
    path, poster = draft.target.nfo_path, persistence.poster_path(draft)
    original_poster = png('blue') if existing_poster else None
    if original_poster is not None:
        poster.write_bytes(original_poster)
    persistence.snapshot_files(draft)
    path.chmod(stat.S_IREAD)
    real_write, real_chmod = persistence._atomic_write, Path.chmod
    external = b'External NFO'
    def write(p, data):
        if ((failure == 'poster' and p == poster and data != original_poster)
                or (failure == 'nfo' and p == path and data != BB_CODE)):
            raise PermissionError('模拟保存失败')
        real_write(p, data)
        if failure == 'nfo_conflict' and p == poster and data != original_poster:
            real_chmod(path, stat.S_IREAD | stat.S_IWRITE)
            path.write_bytes(external)
            real_chmod(path, stat.S_IREAD)
    def chmod(p, *args, **kwargs):
        if p == path and failure in {'poster', 'nfo_conflict'}:
            pytest.fail('NFO 尚未写入或发生冲突时不得修改属性')
        return real_chmod(p, *args, **kwargs)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(persistence, '_atomic_write', write)
            patch.setattr(Path, 'chmod', chmod)
            if failure == 'readback':
                patch.setattr(persistence.NFOParser, 'parse', lambda *a, **k: None)
            with pytest.raises(ScrapeError):
                persistence.commit_draft(draft, poster_bytes=png('red'))
        assert path.read_bytes() == (external if failure == 'nfo_conflict' else BB_CODE)
        assert is_readonly(path)
        assert (poster.read_bytes() if poster.exists() else None) == original_poster
        assert BB_CODE in [b.read_bytes() for b in tmp_path.glob('*.mml-backup-*')]
        if failure != 'nfo_conflict':
            assert persistence.commit_draft(draft, poster_bytes=png('red')).title == '乐高蝙蝠侠大电影'
            assert not is_readonly(path)
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_readonly_nfo_attribute_rollback_failure_reports_backup(readonly_nfo_operation, monkeypatch):
    import scraper.scrape_persistence as persistence
    path, original, save = readonly_nfo_operation
    real_chmod, real_write = Path.chmod, persistence._atomic_write
    def chmod(p, mode, *args, **kwargs):
        if p == path and not mode & stat.S_IWRITE:
            raise PermissionError('模拟无法恢复只读')
        return real_chmod(p, mode, *args, **kwargs)
    def write(p, data):
        if p == path:
            raise PermissionError('模拟写入失败')
        return real_write(p, data)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'chmod', chmod)
        patch.setattr(persistence, '_atomic_write', write)
        with pytest.raises(ScrapeError, match='未能恢复.*mml-backup') as raised:
            save()
    assert str(path) in str(raised.value)
    assert path.read_bytes() == original
    assert not is_readonly(path)
    assert [b.read_bytes() for b in path.parent.glob('*.mml-backup-*')] == [original]


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
