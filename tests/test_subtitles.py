from io import BytesIO
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from parsers.nfo_parser import NFOParser
from utils.subtitle_sources import match_score, parse_candidates
from utils.subtitles import SubtitleError, archive_subtitles, save_subtitle


SRT = '1\n00:00:01,000 --> 00:00:03,000\n字幕测试\n'.encode()


def test_subtitles_saved_without_overwriting_and_reconciled(tmp_path):
    video = tmp_path / 'Film.2024.2160p.mkv'
    nfo = video.with_suffix('.nfo')
    video.touch()
    nfo.write_text('<movie><title>Film</title><fileinfo><streamdetails><subtitle>'
                   '<language>eng</language></subtitle></streamdetails></fileinfo></movie>')
    first = save_subtitle(video, nfo, archive_subtitles('caption.srt', SRT)[0])
    second = save_subtitle(video, nfo, archive_subtitles('caption.srt', SRT)[0])
    assert first.name == 'Film.2024.2160p.srt'
    assert second.name == 'Film.2024.2160p.zh-Hans.srt'
    assert len(ET.parse(nfo).findall('mmlsubtitles/subtitle')) == 2
    first.unlink()
    assert NFOParser.parse(str(nfo)).subtitles == [
        {'file': '', 'language': 'en'}, {'file': second.name, 'language': 'zh-Hans'},
    ]


def test_archive_uses_subtitle_members_only():
    archive = BytesIO()
    with ZipFile(archive, 'w') as package:
        package.writestr('nested/caption.chs.srt', SRT)
        package.writestr('ignore.exe', b'unrelated')
    tracks = archive_subtitles('download.zip', archive.getvalue())
    assert [(track.name, track.language) for track in tracks] == [
        ('nested/caption.chs.srt', 'zh-Hans'),
    ]
    with pytest.raises(SubtitleError):
        archive_subtitles('html.srt', b'<html>verification page</html>')


def test_pgs_subtitle_keeps_binary_content():
    payload = b'PG' + bytes(8) + b'\x80\x00\x00'
    tracks = archive_subtitles('film.cht.sup', payload)
    assert tracks[0].language == 'zh-Hant'
    assert tracks[0].data == payload


def test_release_name_is_prioritized_and_language_is_read():
    html = '''
    <a class="introtitle" href="/xml/sub/669/669637.xml">Film</a>
    <span>版本：<b>Film.2024.1080p.WEB-DL</b></span><span>语言：简 英</span>
    <a class="introtitle" href="/xml/sub/699/699637.xml">Film</a>
    <span>版本：<b>Film.2024.2160p.BluRay</b></span><span>语言：繁</span>
    '''
    candidates = parse_candidates('assrt', html, 'Film.2024.2160p.BluRay')
    assert candidates[0].language == 'zh-en'
    assert candidates[1].language == 'zh-Hant'
    assert candidates[1].score == 100 > candidates[0].score
    assert match_score('Film.2024.2160p.BluRay', 'Unrelated film') < candidates[1].score
