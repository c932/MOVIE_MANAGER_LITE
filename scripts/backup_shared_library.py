"""在线备份 SQLite（包含 WAL 已提交资料），不直接复制主数据库文件。"""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', type=Path)
    args = parser.parse_args()
    source = args.data_dir / 'library.sqlite3'
    if not source.is_file():
        parser.error('共享数据库不存在')
    directory = args.data_dir / 'backups'
    directory.mkdir(exist_ok=True)
    destination = directory / f"library-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dest:
        src.backup(dest)
        result = dest.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise RuntimeError('备份完整性校验失败：' + result)
    print(destination)
