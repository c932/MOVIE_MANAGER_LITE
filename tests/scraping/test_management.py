from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


def movie_files(tmp_path):
    (tmp_path / 'Film.2024.2160p.HDR10.mkv').touch()
    nfo = tmp_path / 'Film.2024.2160p.HDR10.nfo'
    nfo.write_text('<movie><title>电影</title><year>2024</year><plot>旧简介</plot>'
                   '<ratings><rating name="themoviedb"><value>8.1</value><votes>123</votes></rating>'
                   '<rating name="user"><value>9</value></rating></ratings>'
                   '<unknown>保留</unknown><fileinfo><streamdetails><subtitle><language>eng</language></subtitle>'
                   '<video><width>3840</width><height>2160</height><hdrtype>HDR10</hdrtype></video>'
                   '</streamdetails></fileinfo></movie>', encoding='utf-8')
    return nfo


def test_scan_status_alias_subtitles_and_snapshot_without_nas(tmp_path, monkeypatch):
    from scraper.management import scan_rows, save_library, load_library
    movie_files(tmp_path)
    (tmp_path / 'Film.2024.2160p.HDR10.zh.ass').touch()
    (tmp_path / 'unrelated.srt').touch()
    (tmp_path / 'New.2025.mkv').touch()
    rows = scan_rows([str(tmp_path)])
    known = next(row for row in rows if row.movie.title == '电影')
    assert known.score('tmdb') == 8.1
    assert known.subtitle_count == 2 and known.subtitle_known
    assert known.poster_exists is False
    assert not known.is_new and known.movie.resolution == '4K'
    assert next(row for row in rows if row.movie.title.startswith('New')).is_new
    save_library(rows)
    monkeypatch.setattr(Path, 'stat', lambda *args, **kw: (_ for _ in ()).throw(AssertionError('不得访问媒体路径'))
                        if str(args[0]).startswith(str(tmp_path / 'Film')) else real_stat(*args, **kw))
    restored = load_library()
    assert restored[0].key == rows[0].key


real_stat = Path.stat


def test_edit_changes_only_fields_and_preserves_unknown_alias_votes(tmp_path):
    from scraper.management import load_edit, save_edit
    nfo = movie_files(tmp_path)
    snapshot = load_edit(str(nfo))
    original = nfo.read_bytes()
    movie = save_edit(snapshot, {'title': '新标题', 'plot': '', 'ratings': {'tmdb': 7.2}})
    root = ET.parse(nfo).getroot()
    assert root.findtext('title') == '新标题' and root.findtext('plot', '') == ''
    assert root.findtext('unknown') == '保留'
    assert root.findtext("ratings/rating[@name='tmdb']/votes") == '123'
    assert root.findtext("ratings/rating[@name='user']/value") == '9'
    assert root.findtext('fileinfo/streamdetails/video/hdrtype') == 'HDR10'
    assert list(tmp_path.glob('*.mml-backup-*'))[0].read_bytes() == original
    assert movie.title == '新标题'


def test_edit_detects_external_changes_and_noop_creates_no_backup(tmp_path):
    from scraper.management import load_edit, save_edit
    nfo = movie_files(tmp_path)
    snapshot = load_edit(str(nfo))
    save_edit(snapshot, {})
    assert not list(tmp_path.glob('*.mml-backup-*'))
    nfo.write_text('<movie><title>外部修改</title></movie>', encoding='utf-8')
    with pytest.raises(ValueError, match='改变|变化'):
        save_edit(snapshot, {'title': '不能覆盖'})
    assert '外部修改' in nfo.read_text(encoding='utf-8')


def test_edit_clears_legacy_identity_and_vote_only_edit_updates_alias(tmp_path):
    from scraper.management import load_edit, save_edit
    nfo = movie_files(tmp_path)
    root = ET.parse(nfo).getroot()
    ET.SubElement(root, 'doubanurl').text = 'https://movie.douban.com/subject/1/'
    ET.SubElement(root, 'url').text = 'https://movie.douban.com/subject/1/'
    ET.SubElement(root, 'uniqueid', {'type': 'douban'}).text = '1'
    nfo.write_bytes(ET.tostring(root, encoding='utf-8'))
    save_edit(load_edit(str(nfo)), {'uniqueids': {'douban': ''}}, votes={'tmdb': 456})
    root = ET.parse(nfo).getroot()
    assert root.find('doubanurl') is None and root.find('url') is None
    assert root.find("uniqueid[@type='douban']") is None
    assert root.findtext("ratings/rating[@name='tmdb']/votes") == '456'


def test_edit_image_failure_rolls_back_original_files(tmp_path, monkeypatch):
    from PIL import Image
    import io
    import scraper.management as management
    nfo = movie_files(tmp_path)
    snapshot = management.load_edit(str(nfo))
    original = nfo.read_bytes()
    output = io.BytesIO()
    Image.new('RGB', (20, 30), 'red').save(output, format='JPEG')
    real = management._atomic_write
    def fail(path, payload):
        if path == nfo:
            raise OSError('模拟写 NFO 失败')
        real(path, payload)
    monkeypatch.setattr(management, '_atomic_write', fail)
    with pytest.raises(ValueError, match='保存失败'):
        management.save_edit(snapshot, {'title': '不能写入'}, poster_data=output.getvalue())
    assert nfo.read_bytes() == original
    assert not snapshot.poster_path.exists()


def test_reinspected_rebuilt_nfo_drops_resolved_error_and_can_clear_legacy_set(tmp_path):
    from scraper.management import inspect_target, load_edit, save_edit
    from scraper.scrape_models import VideoTarget
    nfo = movie_files(tmp_path)
    target = VideoTarget(nfo.with_suffix('.mkv'), nfo, error='原 NFO 是说明', error_kind='not_metadata', error_detail='旧错误')
    row = inspect_target(target)
    assert not row.target.error and row.state != '失败'
    root = ET.parse(nfo).getroot()
    ET.SubElement(root, 'set').text = '旧系列'
    nfo.write_bytes(ET.tostring(root, encoding='utf-8'))
    updated = save_edit(load_edit(str(nfo)), {'set_name': ''})
    assert updated.set_name == ''
