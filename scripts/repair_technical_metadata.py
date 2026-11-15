"""核对疑似误标清的既有电影，仅修复共享库技术字段，不修改 NAS/NFO。"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'webapp/backend'))

from parsers.nfo_parser import NFOParser
from utils.library_sync import LibraryDatabase, atomic_json
from utils.video_technical import technical_from_filename
from movie_service.nas import NASPaths

TECH_FIELDS = ('resolution', 'hdr_type', 'video_width', 'video_height')


def plan_repairs(data_dir: Path) -> dict:
    database = LibraryDatabase(data_dir / 'library.sqlite3')
    mapper = NASPaths(data_dir)
    result = {'changes': [], 'checked': 0, 'unreadable': 0}
    for record in database.snapshot()['records']:
        if record['deleted']:
            continue
        before = record['data']
        inferred, _ = technical_from_filename(before.get('video_path') or before.get('nfo_path', ''))
        if not inferred or str(before.get('resolution', '')).upper() not in {'', 'SD', '480P'}:
            continue
        result['checked'] += 1
        parsed = NFOParser.parse(mapper.source(before.get('nfo_path', '')))
        if parsed is None:
            result['unreadable'] += 1
            continue
        changes = {key: getattr(parsed, key) for key in TECH_FIELDS if before.get(key) != getattr(parsed, key)}
        if changes:
            result['changes'].append({'id': record['id'], 'title': before.get('title', ''), 'data': changes,
                                      'base': {key: before.get(key) for key in TECH_FIELDS}})
    return result


def apply_repairs(data_dir: Path, plan: dict) -> dict:
    backups = data_dir / 'backups'
    backups.mkdir(exist_ok=True)
    destination = backups / f'library-technical-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.sqlite3'
    with sqlite3.connect(data_dir / 'library.sqlite3') as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    result = LibraryDatabase(data_dir / 'library.sqlite3').push([
        {key: value for key, value in change.items() if key != 'title'} for change in plan['changes']])
    return dict(result, backup=str(destination))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    plan = plan_repairs(args.data_dir)
    if args.apply:
        plan['applied'] = apply_repairs(args.data_dir, plan)
    atomic_json(args.report, plan)
    print(f"checked={plan['checked']} changes={len(plan['changes'])} unreadable={plan['unreadable']}")
    if args.apply:
        print('Backup:', plan['applied']['backup'])
        print('Conflicts:', len(plan['applied'].get('conflicts', [])))
