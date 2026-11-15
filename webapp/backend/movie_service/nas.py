"""NAS 配置适配与规范路径映射。Web 进程不直接提权、不保存密码。"""
from __future__ import annotations

import json
import ntpath
import os
from pathlib import Path, PurePosixPath
import socket

from utils.library_sync import atomic_json, read_json


class NASPaths:
    def __init__(self, data_dir: Path):
        self.file = Path(data_dir) / 'nas_libraries.json'

    def mappings(self):
        return read_json(self.file, {}).get('connections', [])

    def canonical(self, path: str) -> str:
        for item in self.mappings():
            try:
                relative = Path(path).relative_to(item['mount_path'])
            except (ValueError, TypeError):
                continue
            return '\\\\' + item['host'] + '\\' + item['share'] + ('\\' + str(relative).replace('/', '\\') if relative.parts else '')
        return path

    def source(self, path: str) -> str:
        normalized = ntpath.normpath(path).casefold()
        for item in self.mappings():
            prefix = '\\\\' + item['host'] + '\\' + item['share']
            prefix_key = ntpath.normpath(prefix).casefold()
            if normalized == prefix_key or normalized.startswith(prefix_key + '\\'):
                relative = ntpath.normpath(path)[len(prefix):].strip('\\')
                pieces = relative.split('\\') if relative else []
                return str(Path(item['mount_path']).joinpath(*pieces))
        return path

    def movie(self, movie):
        for key in ('nfo_path', 'video_path', 'poster_path', 'fanart_path'):
            value = getattr(movie, key, '')
            if value:
                setattr(movie, key, self.canonical(value))
        return movie

    def contains(self, path: str, roots: list[str]) -> bool:
        normalized = ntpath.normpath(self.canonical(path)).casefold()
        for root in roots:
            prefix = ntpath.normpath(self.canonical(root)).casefold().rstrip('\\')
            if normalized == prefix or normalized.startswith(prefix + '\\'):
                return True
        return False


class NASManager:
    def __init__(self, data_dir: Path, transport=None):
        self.data_dir = Path(data_dir)
        self.paths = NASPaths(data_dir)
        self.transport = transport or self._rpc

    def _rpc(self, request: dict):
        endpoint = os.environ.get('MML_NAS_SOCKET', '/run/movie-wall-nas/control.sock')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(35)
                connection.connect(endpoint)
                connection.sendall(json.dumps(request).encode() + b'\n')
                stream = connection.makefile('rb')
                payload = stream.readline(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError('NAS 连接组件响应过大')
                result = json.loads(payload)
        except (OSError, AttributeError) as exc:
            raise ValueError('NUC 的 NAS 连接服务不可用，请检查 movie-wall-nas-helper 服务') from exc
        if not result.get('ok'):
            raise ValueError(result.get('detail') or 'NAS 操作失败')
        return result['result']

    def status(self):
        status = self.transport({'action': 'status'})
        return dict(status, libraries=read_json(self.paths.file, {}).get('libraries', []))

    def connection(self, mid):
        for item in self.status()['connections']:
            if item['id'] == mid:
                return item
        raise ValueError('NAS 连接不存在，请先连接共享目录')

    def directory(self, mid: str, relative: str = '') -> tuple[dict, Path]:
        connection = self.connection(mid)
        if not connection['connected']:
            raise ValueError('NAS 尚未连接或不可达，请先连接共享目录')
        relative_path = PurePosixPath(relative.replace('\\', '/'))
        if relative_path.is_absolute() or '..' in relative_path.parts or '\x00' in relative:
            raise ValueError('媒体库目录必须位于所选 NAS 共享内')
        root = Path(connection['mount_path']).resolve()
        path = (root / Path(*relative_path.parts)).resolve()
        if not path.is_relative_to(root) or not path.is_dir():
            raise ValueError('媒体库目录不存在或超出共享范围')
        return connection, path

    def directories(self, mid: str, relative: str = '') -> dict:
        connection, path = self.directory(mid, relative)
        root = Path(connection['mount_path']).resolve()
        folders = []
        for item in sorted(path.iterdir(), key=lambda entry: entry.name.casefold()):
            try:
                if item.is_dir() and item.resolve().is_relative_to(root):
                    folders.append({'name': item.name, 'path': item.relative_to(root).as_posix()})
            except OSError:
                continue
        return {'path': '' if path == root else path.relative_to(root).as_posix(),
                'directories': folders}

    def save_libraries(self, selections: list[dict]) -> list[str]:
        directories, mappings, libraries = [], {}, []
        for selection in selections:
            connection, path = self.directory(selection['connection_id'], selection.get('path', ''))
            root = Path(connection['mount_path']).resolve()
            relative = '' if path == root else path.relative_to(root).as_posix()
            key = (connection['id'], relative)
            if key in {(item['connection_id'], item['path']) for item in libraries}:
                continue
            libraries.append({'connection_id': connection['id'], 'path': relative,
                              'label': f"//{connection['host']}/{connection['share']}" + ('/' + relative if relative else '')})
            mappings[connection['id']] = {field: connection[field] for field in ('id', 'host', 'share', 'mount_path', 'read_only')}
            directories.append(str(path))
        # 断开的旧映射保留，数据库里的原始 UNC 路径仍可正确识别。
        for item in self.paths.mappings():
            mappings.setdefault(item['id'], item)
        atomic_json(self.paths.file, {'connections': list(mappings.values()), 'libraries': libraries})
        return directories
