"""跨平台共享电影资料与三方同步协议；不依赖 Qt，也不访问媒体文件。"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterator
import uuid


def movie_key(path: str) -> str:
    return hashlib.sha1(ntpath.normpath(str(path)).casefold().encode('utf-8')).hexdigest()[:16]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class LibraryDatabase:
    """SQLite 是服务端事实来源；单事务合并、单调版本、保留删除墓碑。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS movies '
                       '(id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE INDEX IF NOT EXISTS movies_revision ON movies(revision)')
            db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('server_id', str(uuid.uuid4())))
            db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('revision', '0'))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self, since: int = 0) -> dict:
        with self.connect() as db:
            db.execute('BEGIN')
            meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
            rows = db.execute('SELECT * FROM movies WHERE revision > ? ORDER BY revision', (since,)).fetchall()
            return {'server_id': meta['server_id'], 'revision': int(meta['revision']), 'records': [
                {'id': row['id'], 'data': json.loads(row['data']), 'revision': row['revision'],
                 'deleted': bool(row['deleted'])} for row in rows]}

    def info(self) -> dict:
        with self.connect() as db:
            meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
            return {'server_id': meta['server_id'], 'revision': int(meta['revision'])}

    def push(self, changes: list[dict]) -> dict:
        accepted, conflicts = [], []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            revision = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            for change in changes:
                mid, base = change['id'], change.get('base')
                incoming = dict(change.get('data') or {})
                row = db.execute('SELECT * FROM movies WHERE id=?', (mid,)).fetchone()
                current = json.loads(row['data']) if row else None
                deleted = bool(change.get('deleted'))
                if deleted:
                    if not row or row['deleted']:
                        accepted.append(mid)
                        continue
                    if base is None or current != base:
                        conflicts.append({'id': mid, 'fields': ['删除'], 'data': current})
                        continue
                    merged = current
                elif row and row['deleted']:
                    conflicts.append({'id': mid, 'fields': ['已在服务器删除'], 'data': None})
                    continue
                elif current is None:
                    if base is not None:
                        conflicts.append({'id': mid, 'fields': ['服务器记录不存在'], 'data': None})
                        continue
                    merged = incoming
                else:
                    merged = dict(current)
                    blocked = []
                    for field, value in incoming.items():
                        if value == current.get(field):
                            continue
                        if base is None or current.get(field) != base.get(field):
                            blocked.append(field)
                        else:
                            merged[field] = value
                    if blocked:
                        conflicts.append({'id': mid, 'fields': blocked, 'data': current})
                if current != merged or (row and bool(row['deleted']) != deleted):
                    revision += 1
                    db.execute('INSERT INTO movies VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
                               'data=excluded.data, revision=excluded.revision, deleted=excluded.deleted',
                               (mid, json.dumps(merged, ensure_ascii=False), revision, int(deleted)))
                if not any(item['id'] == mid for item in conflicts):
                    accepted.append(mid)
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(revision),))
        return {'accepted': accepted, 'conflicts': conflicts, 'revision': revision}

    def replace(self, records: dict[str, dict]) -> None:
        """服务端主动修改：保留版本历史，仅实际变化产生版本。调用方持 MovieStore 锁。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = {row['id']: row for row in db.execute('SELECT * FROM movies')}
            revision = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            for mid in records.keys() | old.keys():
                previous = old.get(mid)
                deleted = mid not in records
                data = records[mid] if not deleted else json.loads(previous['data'])
                if previous and json.loads(previous['data']) == data and bool(previous['deleted']) == deleted:
                    continue
                revision += 1
                db.execute('INSERT INTO movies VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
                           'data=excluded.data, revision=excluded.revision, deleted=excluded.deleted',
                           (mid, json.dumps(data, ensure_ascii=False), revision, int(deleted)))
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(revision),))
