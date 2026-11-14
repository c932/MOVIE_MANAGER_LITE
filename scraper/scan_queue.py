"""仅持久化已扫描的目标列表；恢复列表不访问视频目录，也不恢复保存授权。"""
from __future__ import annotations

from dataclasses import asdict, fields
import json

from parsers.nfo_writer import _atomic_write
from scraper.scrape_models import ScrapeError, VideoTarget
from utils.app_paths import resolve_data_file


def load_queue() -> list[VideoTarget]:
    path = resolve_data_file('scrape_queue.json')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('targets'), list):
            raise ValueError('不支持的列表格式')
        result: dict[str, VideoTarget] = {}
        allowed = {field.name for field in fields(VideoTarget)}
        for row in value['targets']:
            if not isinstance(row, dict):
                raise ValueError('无效电影条目')
            data = {key: val for key, val in row.items() if key in allowed}
            for key in ('title', 'year', 'error', 'error_kind', 'error_detail'):
                if key in data and not isinstance(data[key], str):
                    raise ValueError('无效电影状态')
            for key in ('existing', 'version_captured'):
                if key in data and type(data[key]) is not bool:
                    raise ValueError('无效版本状态')
            if data.get('nfo_fingerprint') is not None and not isinstance(data['nfo_fingerprint'], str):
                raise ValueError('无效文件指纹')
            for key in ('video_path', 'nfo_path'):
                if not isinstance(data.get(key), str) or not data[key]:
                    raise ValueError('缺少文件路径')
            stamp = data.get('nfo_stamp')
            if stamp is not None:
                if not isinstance(stamp, list) or len(stamp) != 2 or any(type(v) is not int for v in stamp):
                    raise ValueError('无效文件版本')
                data['nfo_stamp'] = tuple(stamp)
            target = VideoTarget(**data)
            result[str(target.video_path).casefold()] = target
        return list(result.values())
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError) as exc:
        raise ScrapeError('无法恢复待处理列表，请手动扫描电影目录刷新列表') from exc


def save_queue(targets: list[VideoTarget]) -> None:
    rows = []
    for target in targets:
        row = asdict(target)
        row.update(video_path=str(target.video_path), nfo_path=str(target.nfo_path))
        rows.append(row)
    _atomic_write(resolve_data_file('scrape_queue.json'),
                  json.dumps({'version': 1, 'targets': rows}, ensure_ascii=False).encode('utf-8'))
