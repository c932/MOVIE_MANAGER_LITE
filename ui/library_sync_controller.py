"""桌面共享电影库控制器；后台网络和缓存 I/O，主线程合并显示。"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage

from utils.app_paths import ensure_data_dir
from utils.image_loader import ImageCache
from utils.library_sync import atomic_json, movie_key
from utils.sync_client import SyncClient, apply_patches, sync_settings
from .scrape_tasks import TaskRunner


class LibrarySyncController(QObject):
    message = pyqtSignal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.runner = TaskRunner(self)
        self.runner.result.connect(self._result)
        self.runner.error.connect(lambda channel, generation, message: self.message.emit('数据库同步失败：' + message))
        self.runner.progress.connect(lambda channel, generation, message: self.message.emit(str(message)))
        self.message.connect(window.status_label.setText)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.synchronize)
        self.configure()

    def configure(self):
        settings = sync_settings(self.window.config.get_value('library_sync', {}))
        self.timer.stop()
        if settings['enabled']:
            self.timer.start(settings['interval'] * 1000)
            QTimer.singleShot(0, self.synchronize)

    def snapshot(self) -> dict:
        window = self.window
        return {movie_key(movie.nfo_path): dict(window.cache_manager._serialize_movie(movie),
                    watched=window.watch_history.is_watched(movie.nfo_path),
                    _favorite=window.favorite_manager.is_favorite(movie.nfo_path))
                for movie in window.all_movies if movie.nfo_path}

    def synchronize(self):
        settings = sync_settings(self.window.config.get_value('library_sync', {}))
        if not settings['enabled']:
            self.message.emit('请先开启后端数据库同步')
            return
        scanner = getattr(self.window, 'scanner', None)
        if self.runner.busy or (scanner and scanner.isRunning()):
            self.message.emit('同步等待当前扫描或同步任务结束')
            return
        records = self.snapshot()
        client = SyncClient(settings['url'], ensure_data_dir())
        def work(context):
            from utils.poster_cache_manager import PosterCacheManager
            cache = PosterCacheManager()
            def load(mid, path):
                context.checkpoint()
                if not path:
                    return None
                # 只读本机缓存，绝不为同步扫描或探测 NAS。
                with cache._lock:
                    entries = [dict(cache._cache_index['entries'][key]) for key in cache._path_to_cache_keys.get(path, [])
                               if key in cache._cache_index['entries']]
                entries.sort(key=lambda entry: entry.get('width', 0) * entry.get('height', 0), reverse=True)
                for entry in entries:
                    from pathlib import Path
                    candidate = cache.CACHE_DIR / (Path(entry['cache_path']).stem + '.jpg')
                    if candidate.is_file():
                        return candidate.read_bytes()
                return None
            def save(mid, path, payload):
                context.checkpoint()
                if not path:
                    return
                image = QImage.fromData(payload)
                if image.isNull():
                    raise ValueError('后端海报无法解码')
                for width, height in ((200, 300), (280, 420)):
                    scaled = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
                    if not cache.save_to_cache_from_image(path, width, height, scaled, probe_source=False):
                        raise OSError('本机海报缓存写入失败')
            result = client.exchange(records, settings['mode'], load_asset=load, save_asset=save, progress=context.report)
            cache.flush_index()
            return client, result
        self.message.emit('正在同步共享电影库…')
        self.runner.start('sync', work)

    def _result(self, channel, generation, payload):
        if channel != 'sync':
            return
        scanner = getattr(self.window, 'scanner', None)
        if scanner and scanner.isRunning():
            QTimer.singleShot(500, lambda: self._result(channel, generation, payload))
            return
        client, result = payload
        window = self.window
        current = self.snapshot()
        merged = apply_patches(current, result['patches'])
        if result['patches']:
            # 同一路径保留 Movie 引用，当前详情和已建卡片不会指向过期对象。
            old = {movie_key(movie.nfo_path): movie for movie in window.all_movies}
            movies = []
            for mid, data in merged.items():
                updated = window.cache_manager._deserialize_movie(data)
                movie = old.get(mid, updated)
                vars(movie).update(vars(updated))
                movies.append(movie)
            window.all_movies = movies
            window.watch_history.watched_movies = {window.watch_history.normalize_path(item['nfo_path'])
                                                  for item in merged.values() if item.get('watched')}
            window.favorite_manager.favorites = {window.favorite_manager.normalize_path(item['nfo_path'])
                                                for item in merged.values() if item.get('_favorite')}
            for movie in movies:
                if movie.poster_path:
                    ImageCache().remove(movie.poster_path)
            for card in window._card_pool.values():
                card._poster_loaded = False
                card._poster_loading = False
            window.generate_filter_options()
            window.apply_filters()
            current_movie = window.detail_panel.current_movie
            if current_movie and movie_key(current_movie.nfo_path) in merged:
                window.detail_panel.show_movie(current_movie, window.watch_history, window.favorite_manager,
                                               movies, rank_info=window._get_movie_rank_info(current_movie))
            elif current_movie:
                window.detail_panel.current_movie = None
                window.detail_panel.hide()
        from datetime import datetime
        if result.get('asset_downloaded'):
            changed = set(result['asset_downloaded'])
            for movie in window.all_movies:
                if movie_key(movie.nfo_path) in changed and movie.poster_path:
                    ImageCache().remove(movie.poster_path)
                    window._sync_wall_poster_from_cache(movie.poster_path)
        report = {'time': datetime.now().isoformat(timespec='seconds'), 'uploaded': result['uploaded'],
                  'downloaded': result['downloaded'], 'conflicts': result['conflicts'], 'asset_errors': result['asset_errors']}
        def persist(context):
            if result['patches']:
                paths = window.config.get_movie_paths()
                # 使用捕获的合并快照，不在后台读取变化中的 UI 对象。
                cache_data = {'version': '1.0', 'timestamp': report['time'], 'movie_paths': paths,
                              'movie_count': len(merged), 'movies': list(merged.values())}
                atomic_json(window.cache_manager.cache_file, cache_data)
                atomic_json(window.watch_history.history_file, {'watched': [item['nfo_path'] for item in merged.values() if item.get('watched')],
                                                              'total': sum(bool(item.get('watched')) for item in merged.values())})
                atomic_json(window.favorite_manager.data_file, {'favorites': [item['nfo_path'] for item in merged.values() if item.get('_favorite')]})
            client.commit(result)
            atomic_json(ensure_data_dir() / 'library_sync_report.json', report)
        self.runner.start('persist', persist)
        suffix = f"；{len(result['conflicts'])} 部存在冲突，保留服务器版本" if result['conflicts'] else ''
        if result['asset_errors']:
            suffix += f"；{len(result['asset_errors'])} 张海报未同步，稍后可重试"
        self.message.emit(f"数据库同步完成：上传 {result['uploaded']} 部，下载 {result['downloaded']} 部{suffix}")
