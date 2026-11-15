"""首次迁移只读导出/导入。只包含电影资料、观看收藏、海报及榜单，不包含任何凭据。"""
from __future__ import annotations

import argparse
import io
import json
import ntpath
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.library_sync import LibraryDatabase, atomic_json, movie_key, read_json


def export_library(source: Path, archive: Path) -> dict:
    data = read_json(source / 'movie_cache.json', {})
    watched = {ntpath.normpath(path).casefold() for path in read_json(source / 'watch_history.json', {}).get('watched', [])}
    favorites = {ntpath.normpath(path).casefold() for path in read_json(source / 'favorites.json', {}).get('favorites', [])}
    index = read_json(source / '.poster_cache' / 'index.json', {}).get('entries', {})
    by_path = {}
    for key, entry in index.items():
        path = ntpath.normpath(entry.get('original_path', '')).casefold()
        by_path.setdefault(path, []).append((key, entry))
    records, count = {}, 0
    with tarfile.open(archive, 'w:gz') as bundle:
        for item in data.get('movies', []):
            if not item.get('nfo_path'):
                continue
            item = dict(item)
            mid = movie_key(item['nfo_path'])
            item['watched'] = ntpath.normpath(item['nfo_path']).casefold() in watched
            item['_favorite'] = ntpath.normpath(item['nfo_path']).casefold() in favorites
            records[mid] = item
            choices = sorted(by_path.get(ntpath.normpath(item.get('poster_path', '')).casefold(), []),
                             key=lambda pair: pair[1].get('width', 0) * pair[1].get('height', 0), reverse=True)
            for key, entry in choices:
                path = source / '.poster_cache' / f'{key}.jpg'
                if path.is_file():
                    bundle.add(path, arcname=f'posters/{mid}.jpg')
                    count += 1
                    break
        payload = json.dumps(records, ensure_ascii=False).encode('utf-8')
        info = tarfile.TarInfo('records.json')
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
        for name in ('douban_ranking_cache.json', 'new_movie_cache.json'):
            if (source / name).is_file():
                bundle.add(source / name, arcname=name)
    return {'movies': len(records), 'posters': count, 'archive': str(archive)}


def import_library(archive: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    database = LibraryDatabase(destination / 'library.sqlite3')
    # 初始迁移不覆盖服务器现有资料；重复运行按首次上传的冲突规则处理。
    with tarfile.open(archive, 'r:gz') as bundle:
        records = json.load(bundle.extractfile('records.json'))
        result = database.push([{'id': mid, 'base': None, 'data': data} for mid, data in records.items()])
        target = destination / 'shared_posters'
        target.mkdir(exist_ok=True)
        count = 0
        for mid in result['accepted']:
            try:
                payload = bundle.extractfile(f'posters/{mid}.jpg').read()
            except KeyError:
                continue
            path = target / f'{mid}.jpg'
            if not path.exists():
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(payload)
                temporary.replace(path)
            count += 1
        for name in ('douban_ranking_cache.json', 'new_movie_cache.json'):
            try:
                value = json.load(bundle.extractfile(name))
            except KeyError:
                continue
            if not (destination / name).exists():
                atomic_json(destination / name, value)
    return {'imported': len(result['accepted']), 'posters': count, 'conflicts': len(result['conflicts'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['export', 'import'])
    parser.add_argument('data_dir', type=Path)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    result = export_library(args.data_dir, args.archive) if args.mode == 'export' else import_library(args.archive, args.data_dir)
    print(json.dumps(result, ensure_ascii=False))
