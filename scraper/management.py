"""刮削管理的本地快照、文件状态及安全编辑。不得依赖 Qt。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
import json
import math
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from models.movie import Actor, Movie
from parsers.nfo_parser import NFOParser
from parsers.nfo_writer import _atomic_write, apply_fields
from scraper.scrape_models import ScrapeError, VideoTarget, capture_target_version, validate_target_version
from scraper.nfo_inspection import inspect_nfo
from scraper.scrape_persistence import (
    _LOCK, _normalize_tmdb_rating, _prepare_nfo_replace, _restore_files,
    ensure_writable_file, fingerprint, jpeg_bytes, read_ids, sync_ids, validate_score,
)
from utils.app_paths import resolve_data_file


def path_key(path: str | Path) -> str:
    return str(path).replace('\\', '/').casefold()


def _is_douban_url(value: str) -> bool:
    try:
        host = urlsplit(value).hostname or ''
        return host == 'douban.com' or host.endswith('.douban.com')
    except ValueError:
        return False


@dataclass
class ManagementRow:
    target: VideoTarget
    movie: Movie
    metadata_valid: bool = True
    poster_exists: bool | None = None
    subtitle_count: int = 0
    subtitle_known: bool = False
    checked_at: float = 0
    outcome: str = ''
    message: str = ''
    inferred_tech: bool = False

    @property
    def key(self) -> str:
        return path_key(self.target.video_path)

    @property
    def is_new(self) -> bool:
        return not self.metadata_valid

    def score(self, source: str) -> float | None:
        names = ('tmdb', 'themoviedb') if source == 'tmdb' else (source,)
        for name in names:
            try:
                value = float(self.movie.ratings.get(name, 0))
                if math.isfinite(value) and 0 < value <= 10:
                    return value
            except (TypeError, ValueError):
                pass
        return None

    @property
    def missing(self) -> list[str]:
        result = [label for label, value in [('标题', self.movie.title), ('年份', self.movie.year), ('简介', self.movie.plot)] if not value]
        for source, label, identity in [('douban', '豆瓣', self.movie.douban_url),
                                        ('imdb', 'IMDb', self.movie.imdb_id), ('tmdb', 'TMDB', self.movie.tmdb_id)]:
            if self.score(source) is None:
                result.append(label + '评分')
            if not identity:
                result.append(label + '链接/ID')
        if self.poster_exists is False:
            result.append('海报')
        return result

    @property
    def douban_missing(self) -> bool:
        return self.metadata_valid and (self.score('douban') is None or not self.movie.douban_url)

    @property
    def state(self) -> str:
        if self.outcome == '失败' or self.target.error:
            return '失败'
        if self.outcome == '处理中':
            return self.outcome
        if self.outcome == '已保存':
            return '已保存 · 待补' if self.missing else '已保存'
        return '未刮削' if self.is_new else ('待补信息' if self.missing else '已有资料')


def row_from_movie(movie: Movie) -> ManagementRow:
    nfo = Path(movie.nfo_path)
    video = Path(movie.video_path) if movie.video_path else nfo.with_suffix('.mkv')
    target = VideoTarget(video, nfo, movie.title, movie.year, existing=True,
                         douban_complete=bool(movie.ratings.get('douban') and movie.douban_url))
    return ManagementRow(target, copy.deepcopy(movie))


def inspect_target(target: VideoTarget) -> ManagementRow:
    """仅在后台执行：扫描实际文件状态，保留未检测与不存在的区别。"""
    target = copy.deepcopy(target)
    if target.error_kind != 'path_conflict':
        target.error = target.error_kind = target.error_detail = ''
    target.existing = target.nfo_path.is_file()
    root = inspect_nfo(target) if target.existing else None
    movie = NFOParser.parse(str(target.nfo_path), include_user_rating=True) if root is not None else None
    valid = movie is not None
    movie = movie or Movie(title=target.title, year=target.year, video_path=str(target.video_path), nfo_path=str(target.nfo_path))
    movie.video_path = str(target.video_path)
    row = ManagementRow(target, movie, metadata_valid=valid, checked_at=time.time())
    if not valid:
        for candidate in (target.video_path.with_name(target.video_path.stem + '-poster.jpg'), target.video_path.parent / 'poster.jpg'):
            if candidate.is_file():
                movie.poster_path = str(candidate)
                break
    row.poster_exists = bool(movie.poster_path and Path(movie.poster_path).is_file())
    embedded = root.findall('fileinfo/streamdetails/subtitle') if root is not None else []
    stem = target.video_path.stem.casefold()
    external = [p for p in target.video_path.parent.iterdir()
                if p.suffix.lower() in {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx'}
                and (p.stem.casefold() == stem or p.stem.casefold().startswith(stem + '.'))]
    # VobSub 的 .idx/.sub 为一组。
    row.subtitle_count = len(embedded) + len({p.with_suffix('').name.casefold() for p in external})
    row.subtitle_known = bool(embedded)  # 只有 NFO 记录才知道内嵌字幕；无轨信息不等于没有。
    if not movie.resolution:
        match = re.search(r'(?i)(4320p|2160p|1440p|1080p|720p|480p|[248]k)', target.video_path.name)
        if match:
            movie.resolution = match.group(1).upper() if match.group(1).lower().endswith('k') else match.group(1).lower()
            row.inferred_tech = True
    if not movie.hdr_type:
        match = re.search(r'(?i)(HDR10\+?|Dolby[ ._-]?Vision|DoVi|HDR)', target.video_path.name)
        if match:
            movie.hdr_type = match.group(1).upper()
            row.inferred_tech = True
    target.douban_complete = not row.douban_missing if valid else False
    return row


def scan_rows(paths, *, check_cancelled: Callable | None = None, progress: Callable | None = None,
              blacklist_folders=(), blacklist_patterns=()) -> list[ManagementRow]:
    from scraper.media_discovery import discover_videos
    from scraper.scrape_models import ScanProgress
    targets = discover_videos(paths, blacklist_folders, blacklist_patterns, check_cancelled, progress)
    rows = []
    for index, target in enumerate(targets, 1):
        if check_cancelled and check_cancelled():
            raise InterruptedError('扫描已取消')
        rows.append(inspect_target(target))
        if progress:
            progress(ScanProgress('检查媒体状态', index, len(targets), str(target.video_path.parent), len(targets)))
    return rows


def save_library(rows: list[ManagementRow], ui_state: dict | None = None) -> None:
    result = []
    for row in rows:
        data = asdict(row)
        data['target'].update(video_path=str(row.target.video_path), nfo_path=str(row.target.nfo_path))
        result.append(data)
    _atomic_write(resolve_data_file('scrape_management.json'), json.dumps(
        {'version': 1, 'rows': result, 'ui': ui_state or {}}, ensure_ascii=False).encode('utf-8'))


def load_library(with_state: bool = False):
    path = resolve_data_file('scrape_management.json')
    if not path.exists():
        return ([], {}) if with_state else []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise ValueError('未知列表版本')
        rows = []
        for raw in data['rows']:
            item = dict(raw)
            target = dict(item.pop('target'))
            if target.get('nfo_stamp') is not None:
                target['nfo_stamp'] = tuple(target['nfo_stamp'])
            movie = dict(item.pop('movie'))
            movie['actors'] = [Actor(**actor) for actor in movie.get('actors', [])]
            rows.append(ManagementRow(VideoTarget(**target), Movie(**movie), **item))
        return (rows, data.get('ui', {})) if with_state else rows
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ScrapeError('无法恢复刮削管理列表，请重新扫描；原列表文件未改动') from exc


@dataclass
class EditSnapshot:
    target: VideoTarget
    root: ET.Element
    movie: Movie
    expected: dict[str, str | None]
    poster_path: Path
    votes: dict[str, int] = field(default_factory=dict)


def load_edit(nfo_path: str, video_path: str = '') -> EditSnapshot:
    nfo = Path(nfo_path)
    movie = NFOParser.parse(nfo_path, include_user_rating=True)
    if movie is None:
        raise ScrapeError('原 NFO 无法读取，请先搜索匹配或备份重建')
    target = capture_target_version(VideoTarget(Path(video_path or movie.video_path), nfo, movie.title, movie.year, True))
    payload = nfo.read_bytes()
    import hashlib
    if hashlib.sha256(payload).hexdigest() != target.nfo_fingerprint:
        raise ScrapeError('NFO 已改变，请重新加载')
    root = ET.fromstring(payload)
    poster = Path(movie.poster_path) if movie.poster_path else target.video_path.with_name(target.video_path.stem + '-poster.jpg')
    votes = {}
    normalized = copy.deepcopy(root)
    _normalize_tmdb_rating(normalized)
    info = NFOParser._extract_rating(normalized, include_user_rating=True) or {}
    movie.ratings = info.get('all_ratings', {})
    for rating in normalized.findall('ratings/rating'):
        try:
            votes[rating.get('name', '').casefold()] = int(rating.findtext('votes', '0'))
        except ValueError:
            pass
    return EditSnapshot(target, root, movie, {str(nfo): target.nfo_fingerprint, str(poster): fingerprint(poster)}, poster, votes)


def save_edit(snapshot: EditSnapshot, changes: dict, *, votes: dict | None = None, poster_data: bytes | None = None) -> Movie:
    """只修改明确字段；包含可清空值，使用现有备份、冲突和恢复原语。"""
    changes = copy.deepcopy(changes)
    if 'title' in changes and not str(changes['title']).strip():
        raise ScrapeError('标题不能为空')
    for value in changes.get('ratings', {}).values():
        if value is not None:
            validate_score(value)
    if votes is not None and any(type(v) is not int or v < 0 for v in votes.values()):
        raise ScrapeError('评分人数必须是非负整数')
    image = jpeg_bytes(poster_data) if poster_data is not None else None
    root = copy.deepcopy(snapshot.root)
    if 'tmdb' in changes.get('ratings', {}) or 'tmdb' in (votes or {}):
        _normalize_tmdb_rating(root)
    apply_fields(root, changes)
    if 'set_name' in changes and not changes['set_name']:
        for node in list(root.findall('set')):
            root.remove(node)
    sync_ids(root, {k: v for k, v in changes.get('uniqueids', {}).items() if v})
    for source, value in changes.get('uniqueids', {}).items():
        if value:
            continue
        for node in list(root.findall('uniqueid')):
            if node.get('type', '').casefold() == source:
                root.remove(node)
        for tag in {'douban': ('doubanid', 'doubanurl'), 'imdb': ('id',), 'tmdb': ('tmdbid', 'tmdbId')}.get(source, ()):
            for node in list(root.findall(tag)):
                root.remove(node)
        if source == 'douban':
            for node in list(root.findall('url')):
                if _is_douban_url(node.text or ''):
                    root.remove(node)
    for source, count in (votes or {}).items():
        node = root.find(f"ratings/rating[@name='{source}']")
        if node is not None:
            child = node.find('votes')
            if child is None:
                child = ET.SubElement(node, 'votes')
            child.text = str(count)
    if image is not None:
        for thumb in list(root.findall('thumb')):
            if thumb.get('aspect', 'poster') == 'poster':
                root.remove(thumb)
        ET.SubElement(root, 'thumb', {'aspect': 'poster'}).text = snapshot.poster_path.name
    path = snapshot.target.nfo_path
    with _LOCK:
        validate_target_version(snapshot.target)
        for name, expected in snapshot.expected.items():
            if fingerprint(Path(name)) != expected:
                raise ScrapeError('NFO 或海报已改变，请重新加载后编辑')
        if not changes and not votes and image is None:
            return snapshot.movie
        if image is not None:
            ensure_writable_file(snapshot.poster_path, '海报')
        old = {path: path.read_bytes()}
        if image is not None:
            old[snapshot.poster_path] = snapshot.poster_path.read_bytes() if snapshot.poster_path.exists() else None
        changed, modes = [], {}
        try:
            for filename, content in old.items():
                if content is not None:
                    _atomic_write(filename.with_name(filename.name + '.mml-backup-' + uuid.uuid4().hex[:12]), content)
            _prepare_nfo_replace(path, snapshot.expected[str(path)], modes)
            if image is not None:
                _atomic_write(snapshot.poster_path, image)
                changed.append(snapshot.poster_path)
            ET.indent(root, space='  ')
            _atomic_write(path, ET.tostring(root, encoding='utf-8', xml_declaration=True))
            changed.append(path)
            movie = NFOParser.parse(str(path), include_user_rating=True)
            if movie is None:
                raise ScrapeError('保存校验失败')
        except Exception as exc:
            failed = _restore_files(old, changed, modes)
            raise ScrapeError(('恢复失败，请使用 .mml-backup 备份：' + '、'.join(failed)) if failed else '保存失败，原文件已保留/恢复：' + str(exc)) from exc
        return movie
