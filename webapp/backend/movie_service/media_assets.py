"""NAS 海报读入共享副本；成功后原子替换，失败保留原图。"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from PIL import Image, ImageOps


def cache_source_poster(data_dir: Path, mid: str, source: str, *, force: bool = False) -> bool:
    if not source:
        return False
    src = Path(source)
    stamp = src.stat()
    if stamp.st_size > 20 * 1024 * 1024:
        raise ValueError('源海报超过 20 MB')
    directory = Path(data_dir) / 'shared_posters'
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f'{mid}.jpg'
    if dest.is_file() and not force and dest.stat().st_mtime >= stamp.st_mtime:
        with Image.open(dest) as old:
            if old.width >= 500:
                return False
    with Image.open(src) as image:
        if image.width * image.height > 25_000_000:
            raise ValueError('源海报像素超过限制')
        image.load()
        rendered = ImageOps.exif_transpose(image).convert('RGB')
        rendered.thumbnail((1000, 1500), Image.Resampling.LANCZOS)
        fd, name = tempfile.mkstemp(dir=directory, suffix='.tmp')
        os.close(fd)
        try:
            rendered.save(name, format='JPEG', quality=90)
            os.replace(name, dest)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return True
