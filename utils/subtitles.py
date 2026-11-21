"""外挂字幕识别、压缩包读取与源文件保存，供桌面和网页共用。"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import locale
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Timer
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

MAX_PACKAGE = 48 * 1024 * 1024
MAX_SUBTITLE = 4 * 1024 * 1024
MAX_EXTRACTED = 96 * 1024 * 1024
MAX_PGS = MAX_EXTRACTED
TEXT_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.smi'}
SAVE_EXTENSIONS = TEXT_EXTENSIONS | {'.sup'}
EXTENSIONS = SAVE_EXTENSIONS | {'.idx'}
IMPORT_EXTENSIONS = SAVE_EXTENSIONS | {'.zip', '.rar', '.7z'}
LANGUAGES = {
    'zh-Hans': '简中', 'zh-Hant': '繁中', 'zh': '中文', 'zh-en': '中英',
    'en': '英语', 'ja': '日语', 'ko': '韩语', 'fr': '法语', 'de': '德语',
    'es': '西语', 'it': '意语', 'pt': '葡语', 'ru': '俄语', 'und': '语言未知',
}
_ALIASES = {
    'zh-hans': 'zh-Hans', 'zh-cn': 'zh-Hans', 'chs': 'zh-Hans', 'sc': 'zh-Hans',
    'zh-hant': 'zh-Hant', 'zh-tw': 'zh-Hant', 'zh-hk': 'zh-Hant', 'cht': 'zh-Hant', 'tc': 'zh-Hant',
    'chi': 'zh', 'zho': 'zh', 'cn': 'zh', 'zh': 'zh', 'zh-en': 'zh-en',
    'eng': 'en', 'en': 'en', 'english': 'en', 'jpn': 'ja', 'ja': 'ja',
    'kor': 'ko', 'ko': 'ko', 'fre': 'fr', 'fra': 'fr', 'fr': 'fr',
    'ger': 'de', 'deu': 'de', 'de': 'de', 'spa': 'es', 'es': 'es', 'ita': 'it', 'it': 'it',
    'por': 'pt', 'pt': 'pt', 'rus': 'ru', 'ru': 'ru',
}


class SubtitleError(ValueError):
    pass


@dataclass(frozen=True)
class SubtitleFile:
    name: str
    language: str
    data: bytes


def language_from_name(name: str) -> str:
    normalized = name.casefold()
    words = set(re.findall(r'[a-z]+(?:-[a-z]+)?', normalized))
    if (
        any(word in normalized for word in ('双语', '雙語', '中英', 'bilingual'))
        or 'zh-en' in words
        or (words & {'en', 'eng', 'english'} and
            (words & {'chs', 'cht', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'chi', 'zho', 'zh'}
             or any(marker in normalized for marker in ('简体', '簡體', '繁体', '繁體', '中文'))))
    ):
        return 'zh-en'
    for markers, language in ((('简体', '簡體', '简中', '簡中'), 'zh-Hans'),
                              (('繁体', '繁體', '繁中'), 'zh-Hant'),
                              (('中文', '国语', '國語'), 'zh')):
        if any(marker in normalized for marker in markers):
            return language
    return next((_ALIASES[word] for word in reversed(re.findall(r'[a-z]+(?:-[a-z]+)?', normalized))
                 if word in _ALIASES), 'und')


def _decode(data: bytes) -> str:
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16', errors='replace')
    for encoding in ('utf-8-sig', 'gb18030', 'big5'):
        try:
            return data.decode(encoding)
        except UnicodeError:
            pass
    return data.decode('cp1252', errors='replace')


def _dialogue(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if line.startswith('Dialogue:'):
            line = line.split(',', 9)[-1].replace('\\N', '\n')
        elif (not line.strip() or '-->' in line or line.strip().isdigit()
              or line.startswith(('[', 'WEBVTT', 'NOTE', 'Style:', 'Format:'))):
            continue
        lines.extend(re.sub(r'<[^>]*>|\{[^}]*\}', '', line).splitlines())
    return lines


def _language(name: str, data: bytes, hint: str = '') -> str:
    named = language_from_name(name)
    if named != 'und':
        return named
    text = _decode(data)
    if re.search(r'[\u3040-\u30ff]', text):
        return 'ja'
    if re.search(r'[\uac00-\ud7a3]', text):
        return 'ko'
    sections = _dialogue(text)
    chinese = ''.join(re.findall(r'[\u3400-\u9fff]', '\n'.join(sections)))
    if chinese:
        english = sum(bool(re.fullmatch(r"[\w\s,.!?'\"–—-]+", line, re.ASCII)
                           and len(re.findall(r'[A-Za-z]+', line)) >= 2) for line in sections)
        if english >= max(2, len(sections) // 5):
            return 'zh-en'
        simplified = sum(c in '这说们过让语爱为实试测后还发觉应点经长读谢谁时从见给么对会听' for c in chinese)
        traditional = sum(c in '這說們過讓語愛為實試測還發覺應點經長讀謝誰時從見給麼對會聽' for c in chinese)
        return 'zh-Hant' if traditional > simplified else 'zh-Hans' if simplified else 'zh'
    if hint in LANGUAGES and hint != 'und':
        return hint
    if re.search(r'[А-Яа-яЁё]', text):
        return 'ru'
    words = set(re.findall(r'[a-zà-ÿ]+', ' '.join(sections).casefold()))
    common = {
        'en': 'you the this what would should where there they have thank please',
        'fr': 'vous nous avec pourquoi merci toujours quand suis êtes dans',
        'de': 'ich nicht das warum danke und können sind mein jetzt',
        'es': 'usted nosotros gracias porque cómo dónde estoy eres para',
        'it': 'sono questo grazie perché quando dove siamo abbiamo',
        'pt': 'você obrigado obrigada vocês não estão agora também',
    }
    matches = sorted(((len(words.intersection(terms.split())), code) for code, terms in common.items()),
                     reverse=True)
    return matches[0][1] if matches[0][0] >= 2 and matches[0][0] > matches[1][0] else 'und'


def inspect_subtitles(video: Path | None, root: ET.Element | None = None) -> list[dict[str, str]] | None:
    """在线时以文件为准；离线时回退到 NFO 上次同步的外挂字幕清单。"""
    embedded = []
    recorded = {}
    if root is not None:
        embedded = [{'file': '', 'language': language_from_name(node.findtext('language', ''))}
                    for node in root.findall('fileinfo/streamdetails/subtitle')]
        recorded = {node.get('file', ''): node.findtext('language', 'und')
                    for node in root.findall('mmlsubtitles/subtitle') if node.get('file')}
    if video is None:
        tracks = embedded + [{'file': name, 'language': lang if lang in LANGUAGES else 'und'}
                             for name, lang in recorded.items()]
        return tracks or None
    try:
        stem = video.stem.casefold()
        paths = [p for p in video.parent.iterdir()
                 if p.suffix.casefold() in EXTENSIONS and
                 (p.stem.casefold() == stem or p.stem.casefold().startswith(stem + '.'))
                 and not p.is_symlink() and p.is_file()]
    except OSError:
        return inspect_subtitles(None, root)
    idx_stems = {p.stem.casefold() for p in paths if p.suffix.casefold() == '.idx'}
    for path in sorted(paths, key=lambda p: p.name.casefold()):
        suffix = path.suffix.casefold()
        if suffix == '.sub' and path.stem.casefold() in idx_stems:
            continue
        label = path.stem[len(video.stem):]
        hint = recorded.get(path.name, 'und')
        try:
            with path.open('rb') as stream:
                sample = stream.read(65536) if suffix in TEXT_EXTENSIONS or suffix == '.idx' else b''
        except OSError:
            sample = b''
        if suffix == '.idx':
            label = label + ' ' + ' '.join(re.findall(r'^id:\s*([a-z]{2,3})\b', _decode(sample), re.M | re.I))
        language = hint if hint in LANGUAGES and hint != 'und' else _language(label, sample)
        embedded.append({'file': path.name, 'language': language})
    return embedded


def subtitle_summary(tracks: list[dict[str, str]] | None) -> str:
    if tracks is None:
        return '字幕未检测'
    labels = dict.fromkeys(LANGUAGES.get(track['language'], '语言未知') for track in tracks)
    return '字幕 ' + ' / '.join(labels) if labels else '无外挂字幕'


def _valid_text(suffix: str, data: bytes) -> bool:
    text = _decode(data[:65536]).lstrip()
    if suffix == '.vtt':
        return text.startswith('WEBVTT')
    if suffix in {'.ass', '.ssa'}:
        return bool(re.search(r'^\[Events\]', text, re.M | re.I))
    if suffix == '.smi':
        return bool(re.search(r'<SYNC\s+Start\s*=', text, re.I))
    if suffix == '.sub':
        return bool(re.search(r'^\{\d+\}\{\d+\}', text, re.M))
    return bool(re.search(r'\d\d:\d\d:\d\d[,.]\d{1,3}\s+-->\s+\d\d:', text))


def _valid_pgs(data: bytes) -> bool:
    offset = 0
    while offset + 13 <= len(data):
        if data[offset:offset + 2] != b'PG' or data[offset + 10] not in {0x14, 0x15, 0x16, 0x17, 0x80}:
            return False
        offset += 13 + int.from_bytes(data[offset + 11:offset + 13], 'big')
    return 0 < offset == len(data)


def _track(name: str, data: bytes, hint: str) -> SubtitleFile | None:
    suffix = PurePosixPath(name.replace('\\', '/')).suffix.casefold()
    if suffix == '.sup' and len(data) <= MAX_PGS and _valid_pgs(data):
        return SubtitleFile(name, _language(name.rsplit('.', 1)[0], b'', hint), data)
    if suffix in TEXT_EXTENSIONS and data and len(data) <= MAX_SUBTITLE and _valid_text(suffix, data):
        return SubtitleFile(name, _language(name.rsplit('.', 1)[0], data, hint), data)
    return None


def _tar_output(command: list[str], limit: int) -> bytes:
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
            timer = Timer(12, process.kill)
            timer.start()
            try:
                output = process.stdout.read(limit + 1)
                if len(output) > limit:
                    process.kill()
                    raise SubtitleError('压缩包内容超出大小限制')
                if process.wait():
                    raise SubtitleError('无法解压字幕包，文件可能损坏或需要密码')
            finally:
                timer.cancel()
    except OSError as exc:
        raise SubtitleError('无法运行系统解压工具') from exc
    return output


def _archive_members(data: bytes):
    tool = shutil.which('bsdtar') or (shutil.which('tar.exe') if os.name == 'nt' else None)
    if not tool:
        raise SubtitleError('RAR 和 7z 解压需要系统安装 bsdtar')
    with TemporaryDirectory(prefix='mml-subtitles-') as directory:
        archive = Path(directory) / 'subtitle.archive'
        archive.write_bytes(data)
        listing = _tar_output([tool, '-tf', str(archive)], 512 * 1024)
        try:
            names = listing.decode('utf-8').splitlines()
        except UnicodeDecodeError:
            names = listing.decode(locale.getpreferredencoding(False), 'replace').splitlines()
        entries = list(dict.fromkeys(name for name in names if
                     PurePosixPath(name).suffix.casefold() in SAVE_EXTENSIONS and
                     not re.search(r'[\x00-\x1f\x7f*?\[\]\\]', name)))
        if len(entries) > 80:
            raise SubtitleError('压缩包内字幕太多，请先选择所需电影的字幕')
        for name in entries:
            limit = MAX_PGS if PurePosixPath(name).suffix.casefold() == '.sup' else MAX_SUBTITLE
            yield name, _tar_output([tool, '-xOf', str(archive), '--', name], limit)


def _zip_members(data: bytes):
    with ZipFile(BytesIO(data)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()
                   and PurePosixPath(item.filename).suffix.casefold() in SAVE_EXTENSIONS
                   and item.file_size <= (MAX_PGS if item.filename.lower().endswith('.sup') else MAX_SUBTITLE)]
        if len(entries) > 80:
            raise SubtitleError('压缩包内字幕太多，请先选择所需电影的字幕')
        for item in entries:
            with archive.open(item) as stream:
                yield item.filename, stream.read(item.file_size + 1)


def archive_subtitles(name: str, data: bytes, hint: str = '') -> list[SubtitleFile]:
    if not data or len(data) > MAX_PACKAGE:
        raise SubtitleError('字幕文件为空或超过 48 MB')
    if data.startswith(b'PK\x03\x04'):
        members = _zip_members(data)
    elif data.startswith((b'Rar!\x1a\x07', b'7z\xbc\xaf\x27\x1c')):
        members = _archive_members(data)
    else:
        members = iter([(name, data)])
    tracks = []
    total = 0
    try:
        for member, payload in members:
            total += len(payload)
            if total > MAX_EXTRACTED:
                raise SubtitleError('字幕包解压后超过 96 MB，请选择文件较少的字幕包')
            track = _track(member, payload, hint)
            if track:
                tracks.append(track)
    except (BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise SubtitleError('无法解压字幕包，文件可能损坏或需要密码') from exc
    if not tracks:
        raise SubtitleError('没有找到可用字幕，请确认下载的是 SRT、ASS、SSA、VTT、文本 SUB、SMI、SUP 或字幕压缩包')
    return tracks


def _write_records(video: Path, nfo: Path, original: bytes, root: ET.Element,
                   override: tuple[str, str] | None = None) -> list[dict[str, str]]:
    from parsers.nfo_writer import write_tree

    tracks = inspect_subtitles(video, root)
    if tracks is None:
        raise SubtitleError('无法读取电影目录')
    for track in tracks:
        if override and track['file'] == override[0]:
            track['language'] = override[1]
    current = root.find('mmlsubtitles')
    records = ET.Element('mmlsubtitles')
    for track in tracks:
        if track['file']:
            node = ET.SubElement(records, 'subtitle', file=track['file'])
            ET.SubElement(node, 'language').text = track['language']
    if nfo.read_bytes() != original:
        raise SubtitleError('NFO 正被其他操作更新，请重试')
    new_records = {node.get('file'): node.findtext('language') for node in records}
    old_records = {node.get('file'): node.findtext('language') for node in current} if current is not None else {}
    if old_records != new_records:
        if current is not None:
            root.remove(current)
        root.append(records)
        write_tree(ET.ElementTree(root), str(nfo))
    return tracks


def _read_nfo(video: Path, nfo: Path) -> tuple[bytes, ET.Element]:
    if not video.is_file() or not nfo.is_file() or video.is_symlink() or nfo.is_symlink():
        raise SubtitleError('电影或 NFO 不可访问')
    try:
        original = nfo.read_bytes()
        root = ET.fromstring(original, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except ET.ParseError as exc:
        raise SubtitleError('请先修复电影的 NFO，再保存字幕') from exc
    if root.tag != 'movie':
        raise SubtitleError('电影 NFO 格式无效')
    return original, root


def sync_subtitles(video: Path, nfo: Path) -> list[dict[str, str]]:
    original, root = _read_nfo(video, nfo)
    return _write_records(video, nfo, original, root)


def detect_subtitles(video: Path, nfo: Path) -> list[dict[str, str]]:
    _, root = _read_nfo(video, nfo)
    tracks = inspect_subtitles(video, root)
    if tracks is None:
        raise SubtitleError('无法读取电影目录')
    return tracks


def save_subtitle(video: Path, nfo: Path, subtitle: SubtitleFile, language: str = '') -> Path:
    original, root = _read_nfo(video, nfo)
    language = language or subtitle.language
    if language not in LANGUAGES:
        raise SubtitleError('请选择有效的字幕语言')
    suffix = PurePosixPath(subtitle.name).suffix.casefold()
    if not _track(subtitle.name, subtitle.data, language):
        raise SubtitleError('字幕格式无效')
    exists = any(track['file'] for track in inspect_subtitles(video, root) or [])
    stem = f'{video.stem}.{language}' if exists else video.stem
    for number in range(1, 100):
        label = stem if number == 1 else f'{video.stem}.{language}.{number}'
        path = video.with_name(label + suffix)
        try:
            stream = path.open('xb')
        except FileExistsError:
            continue
        try:
            with stream:
                stream.write(subtitle.data)
            _write_records(video, nfo, original, root, (path.name, language))
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise
    raise SubtitleError('该语言的同名字幕过多，请先整理电影目录')
