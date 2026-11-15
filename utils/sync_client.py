"""有基线的桌面同步客户端。网络在调用方后台线程运行，结果在主线程合并。"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from .library_sync import atomic_json, read_json

DEFAULT_SYNC = {'enabled': False, 'url': 'http://movie.nuc.local', 'mode': 'both', 'interval': 120}
MODES = {'download', 'upload', 'both'}


def sync_settings(config: dict | None) -> dict:
    value = dict(DEFAULT_SYNC, **(config or {}))
    parts = urlsplit(str(value['url']).strip())
    if parts.scheme not in {'http', 'https'} or not parts.netloc or parts.username or parts.password:
        raise ValueError('后端地址应为 http:// 或 https:// 地址')
    value['url'] = value['url'].strip().rstrip('/')
    if value['mode'] not in MODES:
        raise ValueError('请选择仅下载、仅上传或双向同步')
    value['interval'] = max(30, min(3600, int(value['interval'])))
    return value


class SyncClient:
    def __init__(self, url: str, data_dir: Path, transport: Callable | None = None):
        self.url = sync_settings({'url': url})['url']
        tag = hashlib.sha256(self.url.encode()).hexdigest()[:16]
        self.state_path = Path(data_dir) / f'library_sync_{tag}.json'
        self.transport = transport or self._request

    def _request(self, method: str, path: str, body=None, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8') if body is not None else None
        request = Request(self.url + '/api/movie' + path, data=data, method=method,
                          headers={'Content-Type': 'application/octet-stream' if isinstance(body, bytes) else 'application/json', **(headers or {})})
        try:
            # 局域网后端不继承客户端全局代理。
            with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
                payload = response.read(64 * 1024 * 1024 + 1)
                if len(payload) > 64 * 1024 * 1024:
                    raise ValueError('后端响应超出大小限制')
                return json.loads(payload) if 'json' in response.headers.get('Content-Type', '') else payload
        except HTTPError as exc:
            try:
                message = json.loads(exc.read()).get('detail', str(exc))
            except (ValueError, OSError):
                message = f'HTTP {exc.code}'
            raise ValueError(str(message)) from exc

    def exchange(self, records: dict[str, dict], mode: str = 'both', *,
                 load_asset: Callable | None = None, save_asset: Callable | None = None,
                 progress: Callable[[str], None] = lambda message: None,
                 deleted_ids: set[str] | None = None) -> dict:
        if mode not in MODES:
            raise ValueError('未知同步方向')
        state = copy.deepcopy(read_json(self.state_path, {}))
        info = self.transport('GET', '/sync/changes?since=9223372036854775807')
        if state.get('server_id') != info['server_id']:
            state = {'server_id': info['server_id'], 'cursor': 0, 'base': {}, 'assets': {}}
        baseline = state.setdefault('base', {})
        conflicts, sent, patches = [], 0, []
        if mode != 'download':
            changes = []
            for mid, data in records.items():
                base = baseline.get(mid)
                delta = data if base is None else {key: value for key, value in data.items() if value != base.get(key)}
                if delta:
                    changes.append({'id': mid, 'base': base, 'data': delta})
            for mid in deleted_ids or ():
                base = baseline.get(mid)
                if mid not in records and base is not None:
                    changes.append({'id': mid, 'base': base, 'deleted': True})
            if changes:
                progress(f'正在上传 {len(changes)} 部电影的变更')
                pushed = self.transport('POST', '/sync/push', {'server_id': state['server_id'], 'changes': changes})
                conflicts.extend(pushed['conflicts'])
                blocked = {item['id']: set(item['fields']) for item in conflicts}
                for change in changes:
                    mid = change['id']
                    if mid in pushed['accepted']:
                        if change.get('deleted'):
                            baseline.pop(mid, None)
                        else:
                            baseline[mid] = copy.deepcopy(records[mid])
                        sent += 1
                    elif baseline.get(mid) is not None:
                        for key, value in change.get('data', {}).items():
                            if key not in blocked.get(mid, set()):
                                baseline[mid][key] = copy.deepcopy(value)
        if mode != 'upload':
            progress('正在下载后端电影资料')
            remote = self.transport('GET', f"/sync/changes?since={state.get('cursor', 0)}")
            if remote['server_id'] != state['server_id']:
                raise ValueError('同步期间后端数据库已更换，请重试')
            for item in remote['records']:
                mid = item['id']
                patches.append({'id': mid, 'data': item['data'], 'deleted': item['deleted'],
                                'before': copy.deepcopy(records.get(mid))})
                if item['deleted']:
                    baseline.pop(mid, None)
                else:
                    baseline[mid] = copy.deepcopy(item['data'])
            # 本机缓存文件丢失不代表删除共享库；直接从已下载基线恢复缺失记录。
            changed_ids = {patch['id'] for patch in patches}
            for mid, data in baseline.items():
                if mid not in records and mid not in changed_ids and mid not in (deleted_ids or ()):
                    patches.append({'id': mid, 'data': copy.deepcopy(data), 'deleted': False, 'before': None})
            state['cursor'] = remote['revision']
        effective = copy.deepcopy(records)
        for patch in patches:
            if patch['deleted']:
                effective.pop(patch['id'], None)
            else:
                effective[patch['id']] = patch['data']
        asset_errors, asset_downloaded = [], []
        if load_asset or save_asset:
            manifest = self.transport('GET', '/sync/assets')
            blocked_ids = {item['id'] for item in conflicts}
            for index, (mid, data) in enumerate(effective.items()):
                if index % 50 == 0:
                    progress(f'正在同步海报：{index}/{len(effective)}')
                try:
                    if mode != 'download' and load_asset and mid not in blocked_ids:
                        payload = load_asset(mid, data.get('poster_path', ''))
                        if payload:
                            digest = hashlib.sha256(payload).hexdigest()
                            previous = state.get('assets', {}).get(mid, '')
                            local_previous = state.get('local_assets', {}).get(mid, '')
                            if digest == manifest.get(mid):
                                state.setdefault('assets', {})[mid] = digest
                                state.setdefault('local_assets', {})[mid] = digest
                            if digest != manifest.get(mid) and digest != local_previous:
                                result = self.transport('PUT', f'/sync/assets/{mid}', payload, {'If-Match': previous})
                                manifest[mid] = result['sha256']
                                state.setdefault('assets', {})[mid] = result['sha256']
                                state.setdefault('local_assets', {})[mid] = digest
                    if mode != 'upload' and save_asset and mid in manifest:
                        # 即使基线相同，本机图片被清理后仍应能重新获取。
                        if not load_asset or not load_asset(mid, data.get('poster_path', '')) or state.get('assets', {}).get(mid) != manifest[mid]:
                            payload = self.transport('GET', f'/sync/assets/{mid}')
                            save_asset(mid, data.get('poster_path', ''), payload)
                            asset_downloaded.append(mid)
                            local = load_asset(mid, data.get('poster_path', '')) if load_asset else None
                            if local:
                                state.setdefault('local_assets', {})[mid] = hashlib.sha256(local).hexdigest()
                        state.setdefault('assets', {})[mid] = manifest[mid]
                except (OSError, ValueError) as exc:
                    asset_errors.append({'id': mid, 'message': str(exc)})
        return {'patches': patches, 'state': state, 'uploaded': sent, 'downloaded': len(patches),
                'conflicts': conflicts, 'asset_errors': asset_errors, 'asset_downloaded': asset_downloaded}

    def commit(self, result: dict) -> None:
        atomic_json(self.state_path, result['state'])


def apply_patches(current: dict[str, dict], patches: list[dict]) -> dict[str, dict]:
    """仅替换请求以来没在本机改过的字段，避免网络返回覆盖用户刚编辑的资料。"""
    merged = copy.deepcopy(current)
    for patch in patches:
        mid, before = patch['id'], patch['before']
        now = merged.get(mid)
        if patch['deleted']:
            if now == before:
                merged.pop(mid, None)
        elif before is None:
            if now is None:
                merged[mid] = copy.deepcopy(patch['data'])
        elif now is not None:
            for key, value in patch['data'].items():
                if now.get(key) == before.get(key):
                    now[key] = copy.deepcopy(value)
    return merged
