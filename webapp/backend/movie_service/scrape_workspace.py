"""网页刮削会话，复用桌面领域服务；客户端不能提交任意文件路径或候选元数据。"""
from __future__ import annotations
from dataclasses import asdict, fields
from collections.abc import Iterable
from typing import Any
from models.movie import Movie
from wall_common.jobs import JobContext
import copy
import os
from pathlib import Path
import threading
import time
import uuid

from scraper.scrape_models import ScrapeError, VideoTarget, capture_target_version, can_rebuild_nfo
from scraper.scrape_service import ScrapeService
from scraper.scrape_settings import ScrapeSettings
from scraper.management import inspect_target, load_edit, save_edit, scan_rows
from scraper.scrape_persistence import read_ids
from utils.library_sync import atomic_json, read_json, movie_key
from .nas import NASManager, NASPaths
from .store import MovieStore, movie_to_dto, movie_id

WRITE_FIELDS = {'title', 'original_title', 'year', 'premiered', 'plot', 'tagline', 'runtime',
                'genres', 'countries', 'directors', 'actors', 'set_name', 'ratings', 'uniqueids', 'poster'}


class ScrapeWorkspace:
    def __init__(self, store: MovieStore) -> None:
        self.store = store
        self.data_dir = store.settings.data_dir
        self.paths = NASPaths(self.data_dir)
        self.file = self.data_dir / 'web_scrape_library.json'
        self.settings_file = Path(os.environ.get('MML_SCRAPE_CONFIG', str(self.data_dir / 'scrape_config.json')))
        self.lock = threading.RLock()
        self.tokens = {}
        self.operation_lock = threading.Lock()

    def settings(self) -> ScrapeSettings:
        data = read_json(self.settings_file, {})
        settings = ScrapeSettings(**{field.name: data[field.name] for field in fields(ScrapeSettings) if field.name in data})
        settings.validate()
        return settings

    def public_settings(self) -> dict[str, Any]:
        import shutil
        config = asdict(self.settings())
        for key in ('tmdb_api_key', 'tmdb_token', 'omdb_api_key'):
            config['has_' + key] = bool(config.pop(key))
        config['douban_available'] = bool(shutil.which('node') and shutil.which('npx'))
        return config

    def save_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        config = asdict(self.settings())
        for key, value in changes.items():
            if key not in config:
                raise ScrapeError('未知刮削配置字段')
            if key in {'tmdb_api_key', 'tmdb_token', 'omdb_api_key'} and value == '':
                continue  # 掩码表单留空保留已有凭据。
            config[key] = value
        settings = ScrapeSettings(**config)
        settings.validate()
        atomic_json(self.settings_file, config)
        self.settings_file.chmod(0o600)
        return self.public_settings()

    def token(self, kind: str, value: Any) -> str:
        with self.lock:
            now = time.monotonic()
            self.tokens = {key: item for key, item in self.tokens.items() if now - item['time'] < 1800}
            if len(self.tokens) > 1000:
                raise ScrapeError('刮削会话过多，请稍后重新打开')
            key = uuid.uuid4().hex
            self.tokens[key] = {'kind': kind, 'value': value, 'time': now}
            return key

    def require(self, key: str, kind: str) -> Any:
        with self.lock:
            item = self.tokens.get(key)
            if not item or item['kind'] != kind or time.monotonic() - item['time'] > 1800:
                raise ScrapeError('候选或草稿已过期，请重新搜索/预览')
            return item['value']

    def rows(self) -> list[dict[str, Any]]:
        rows = {row['id']: row for row in read_json(self.file, {'rows': []})['rows']}
        for movie in self.store.snapshot():
            tid = movie_key(movie.video_path or movie.nfo_path)
            old = rows.get(tid, {})
            rows[tid] = dict(old, id=tid, movie= self.store.dto(movie, detail=True), movie_id=movie_id(movie.nfo_path),
                             is_new=False, status=old.get('status') if old.get('error_kind') else '已有资料',
                             poster_exists=old.get('poster_exists'), subtitle_count=old.get('subtitle_count'),
                             error_kind=old.get('error_kind', ''), error=old.get('error', ''))
        return list(rows.values())

    def target(self, tid: str) -> VideoTarget:
        row = next((row for row in self.rows() if row['id'] == tid), None)
        if not row:
            raise ScrapeError('电影不在当前管理列表，请重新扫描')
        movie = row['movie']
        video = Path(self.paths.source(movie['video_path'])).resolve()
        nfo = Path(self.paths.source(movie['nfo_path'])).resolve()
        roots = [Path(path).resolve() for path in self.store.movie_paths()]
        if not any(video.is_relative_to(root) and nfo.is_relative_to(root) for root in roots):
            raise ScrapeError('电影不在已配置的媒体库目录内，请先配置 NAS 或媒体库')
        target = VideoTarget(video, nfo, movie['title'], movie['year'], nfo.is_file())
        if row.get('error_kind') == 'path_conflict':
            target.error_kind, target.error = 'path_conflict', row.get('error') or '多个视频共用 NFO 路径，禁止保存'
        return inspect_target(target).target

    def writable(self, target: VideoTarget) -> None:
        if target.error_kind == 'path_conflict':
            raise ScrapeError(target.error)
        for mapping in self.paths.mappings():
            if Path(target.nfo_path).is_relative_to(mapping['mount_path']):
                try:
                    connection = NASManager(self.data_dir).connection(mapping['id'])
                except ValueError as exc:
                    raise ScrapeError(str(exc)) from None
                if not connection['connected']:
                    raise ScrapeError('NAS 不可访问，请先连接共享')
                if connection['read_only']:
                    raise ScrapeError('NAS 共享为只读，请在设置中允许刮削写入 NFO 和海报')
                return
        if not os.access(target.nfo_path.parent, os.W_OK):
            raise ScrapeError('媒体目录不可写')

    def validate_files(self, names: Iterable[str]) -> None:
        roots = [Path(path).resolve() for path in self.store.movie_paths()]
        if any(not any(Path(name).resolve().is_relative_to(root) for root in roots) for name in names):
            raise ScrapeError('NFO 或海报指向媒体库目录之外，禁止读写，请修正原文件路径')

    def scan(self, context: JobContext) -> dict[str, int]:
        from .tasks import run_library_refresh
        run_library_refresh(self.store, context, force=False)
        cfg = self.store.config()
        def progress(value):
            context.update(stage=value.stage, current=value.current, total=value.total,
                           message=self.paths.canonical(value.directory))
        inspected = scan_rows(self.store.movie_paths(), check_cancelled=context.check_cancelled, progress=progress,
                              blacklist_folders=cfg.get_blacklist_folders(), blacklist_patterns=cfg.get_blacklist_patterns())
        rows = []
        for row in inspected:
            self.paths.movie(row.movie)
            rows.append({'id': movie_key(row.movie.video_path), 'movie_id': movie_id(row.movie.nfo_path),
                         'movie': movie_to_dto(row.movie, detail=True), 'is_new': row.is_new, 'status': row.state,
                         'poster_exists': row.poster_exists, 'subtitle_count': row.subtitle_count if row.subtitle_known or row.subtitle_count else None,
                         'error_kind': row.target.error_kind, 'error': row.target.error_detail or row.target.error})
        atomic_json(self.file, {'rows': rows})
        return {'count': len(rows)}

    def search(self, source: str, query: str, year: str, page: int) -> list[dict[str, Any]]:
        service = ScrapeService(self.settings())
        return [{'token': self.token('candidate', candidate), **asdict(candidate)}
                for candidate in service.search(source, query, year, page) if candidate.media_type == 'movie']

    def preview(self, tid: str, candidate_token: str, previous: str | None = None, plot_source: str | None = None) -> dict[str, Any]:
        target = capture_target_version(self.target(tid))
        candidate = self.require(candidate_token, 'candidate')
        service = ScrapeService(self.settings())
        metadata = service.details(candidate)
        related = service.automatic_tmdb_metadata(metadata)
        if not related:
            metadata = service.enrich_metadata(metadata)
        sources = []
        if previous:
            old = self.require(previous, 'draft')
            if old['tid'] != tid or not old['draft'].confirmed:
                raise ScrapeError('请先确认当前电影的匹配，再补充其他来源')
            sources = [item for item in old['sources'] if item.source != metadata.source]
        sources += [metadata]
        sources += [item for item in related if item.source not in {source.source for source in sources}]
        selected_plot = plot_source or candidate.source
        draft = service.build_draft(target, sources, selected_plot)
        if metadata.source == 'tmdb' and not draft.fields.get('ratings', {}).get('douban'):
            lookup = copy.deepcopy(metadata)
            lookup.ids.update(draft.fields.get('uniqueids', {}))
            sources += [item for item in service.automatic_douban_metadata(lookup) if item.source not in {source.source for source in sources}]
            draft = service.build_draft(target, sources, selected_plot)
        key = self.token('draft', {'tid': tid, 'draft': draft, 'sources': sources, 'plot_source': selected_plot, 'service': service, 'saved': False})
        return self.view(key)

    def view(self, key: str) -> dict[str, Any]:
        value = self.require(key, 'draft')
        draft = value['draft']
        try:
            self.writable(draft.target)
            reason = ''
        except ScrapeError as exc:
            reason = str(exc)
        return {'session': key, 'target_id': value['tid'], 'fields': draft.fields, 'votes': draft.votes,
                'artwork': [asdict(artwork) for artwork in draft.artwork], 'warnings': draft.warnings,
                'poster_index': draft.artwork.index(draft.poster) if draft.poster in draft.artwork else None,
                'confirmed': draft.confirmed, 'replace_identity': draft.replace_identity,
                'can_rebuild': can_rebuild_nfo(draft.target), 'plot_source': value['plot_source'],
                'source_plots': {item.source: item.fields.get('plot', '') for item in value['sources']},
                'sources': [item.source for item in value['sources']], 'write_blocked': reason,
                'target_path': self.paths.canonical(str(draft.target.nfo_path))}

    def confirm(self, key: str, options: dict[str, Any]) -> dict[str, Any]:
        value = self.require(key, 'draft')
        if value['saved']:
            raise ScrapeError('该草稿已保存，请重新获取电影资料')
        plot_source = options.get('plot_source') or value['plot_source']
        if plot_source not in {item.source for item in value['sources']}:
            raise ScrapeError('该简介来源尚未取得资料')
        draft = value['service'].build_draft(value['draft'].target, value['sources'], plot_source)
        for name in ('title', 'plot'):
            if name in options:
                draft.fields[name] = options[name]
        if not str(draft.fields.get('title', '')).strip():
            raise ScrapeError('电影标题不能为空')
        index = options.get('poster_index')
        if index is not None and not 0 <= index < len(draft.artwork):
            raise ScrapeError('海报选择无效')
        draft.poster = draft.artwork[index] if index is not None else None
        draft.rebuild_nfo = bool(options.get('rebuild_nfo') and can_rebuild_nfo(draft.target))
        draft.confirmed = True
        value.update(draft=draft, plot_source=plot_source)
        return self.view(key)

    def publish(self, movie: Movie, target_id: str) -> dict[str, Any]:
        physical_poster = movie.poster_path
        self.paths.movie(movie)
        with self.store.lock:
            current = self.store.snapshot()
            old = next((item for item in current if movie_id(item.nfo_path) == movie_id(movie.nfo_path)), None)
            movie.watched = self.store.watch.is_watched(movie.nfo_path)
            movie.added_time = old.added_time if old and old.added_time else time.time()
            current = [item for item in current if movie_id(item.nfo_path) != movie_id(movie.nfo_path)] + [movie]
            self.store.replace_all(current)
        if physical_poster:
            from .media_assets import cache_source_poster
            try:
                cache_source_poster(self.data_dir, movie_id(movie.nfo_path), physical_poster, force=True)
            except (OSError, ValueError):
                pass
        data = read_json(self.file, {'rows': []})
        data['rows'] = [row for row in data['rows'] if row['id'] != target_id]
        atomic_json(self.file, data)
        return self.store.dto(movie, detail=True)

    def save(self, key: str, options: dict[str, Any]) -> dict[str, Any]:
        value = self.require(key, 'draft')
        draft = value['draft']
        if value['saved'] or not draft.confirmed:
            raise ScrapeError('请先确认匹配；已保存草稿不可重复写入')
        self.writable(draft.target)
        self.validate_files(draft.expected_files)
        selected = set(options['selected_fields'])
        if not selected or selected - WRITE_FIELDS:
            raise ScrapeError('请选择有效写入字段')
        if draft.replace_identity and not options.get('replace_identity_ack'):
            raise ScrapeError('电影身份发生变化，请明确确认替换旧资料')
        movie = value['service'].save(draft, selected, options.get('overwrite', False), options.get('metadata_only', False))
        value['saved'] = True
        return self.publish(movie, value['tid'])

    def edit(self, tid: str) -> dict[str, Any]:
        target = self.target(tid)
        snapshot = load_edit(str(target.nfo_path), str(target.video_path))
        self.validate_files(snapshot.expected)
        key = self.token('edit', {'snapshot': snapshot, 'tid': tid})
        return {'session': key, 'movie': movie_to_dto(self.paths.movie(copy.deepcopy(snapshot.movie)), detail=True),
                'uniqueids': read_ids(snapshot.root), 'votes': snapshot.votes}

    def save_editor(self, key: str, changes: dict[str, Any], votes: dict[str, int], poster_base64: str | None = None) -> dict[str, Any]:
        value = self.require(key, 'edit')
        self.writable(value['snapshot'].target)
        self.validate_files(value['snapshot'].expected)
        if set(changes) - (WRITE_FIELDS - {'poster'}):
            raise ScrapeError('编辑字段无效')
        image = None
        if poster_base64 is not None:
            import base64
            try:
                image = base64.b64decode(poster_base64, validate=True)
            except ValueError:
                raise ScrapeError('海报文件格式无效') from None
        movie = save_edit(value['snapshot'], changes, votes=votes, poster_data=image)
        return self.publish(movie, value['tid'])
