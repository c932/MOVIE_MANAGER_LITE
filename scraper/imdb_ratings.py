"""IMDb 官方免费评分数据集；24 小时磁盘缓存，有界下载与流式 gzip 校验。

仅用于个人、非商业用途，使用条件见 https://developer.imdb.com/non-commercial-datasets/ 。
"""
from __future__ import annotations

from collections import OrderedDict
import gzip
import io
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import BinaryIO
import zlib

from utils.app_paths import ensure_data_dir
from .metadata_sources import ProviderError
from .scrape_http import HttpClient, HttpError
from .scrape_settings import ScrapeSettings


_URL = 'https://datasets.imdbws.com/title.ratings.tsv.gz'
_MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_CACHE_TTL = 24 * 60 * 60
_cache_lock = threading.Lock()
_RecentKey = tuple[Path, int, int, str]
_recent: OrderedDict[_RecentKey, tuple[float | None, int | None]] = OrderedDict()


def _remember(key: _RecentKey, result: tuple[float | None, int | None]) -> tuple[float | None, int | None]:
    _recent[key] = result
    _recent.move_to_end(key)
    while len(_recent) > 128:
        _recent.popitem(last=False)
    return result


def _parse(stream: BinaryIO, identity: str) -> tuple[float | None, int | None]:
    """扫到 EOF 才接受结果，防止条目之后的截断、CRC 错误或重复身份。"""
    result: tuple[float | None, int | None] = (None, None)
    total = 0
    try:
        with gzip.GzipFile(fileobj=stream) as source:
            header = source.readline(256)
            total += len(header)
            if header.rstrip(b'\r\n') != b'tconst\taverageRating\tnumVotes':
                raise ProviderError('IMDb 官方评分数据集表头无效')
            while True:
                line = source.readline(256)
                total += len(line)
                if total > _MAX_UNCOMPRESSED_BYTES or len(line) >= 256:
                    raise ProviderError('IMDb 官方评分数据集解压内容超出大小上限')
                if not line:
                    break
                fields = line.rstrip(b'\r\n').split(b'\t')
                if len(fields) != 3 or not re.fullmatch(rb'tt[0-9]+', fields[0]):
                    raise ProviderError('IMDb 官方评分数据集条目格式无效')
                score = float(fields[1])
                if not re.fullmatch(rb'[0-9]+', fields[2]):
                    raise ProviderError('IMDb 官方评分数据集投票数无效')
                votes = int(fields[2])
                if not math.isfinite(score) or not 0 < score <= 10 or votes <= 0:
                    raise ProviderError('IMDb 官方评分数据集评分或投票数无效')
                if fields[0] == identity.encode('ascii'):
                    if result[0] is not None:
                        raise ProviderError('IMDb 官方评分数据集存在重复条目')
                    result = (score, votes)
    except ProviderError:
        raise
    except (OSError, EOFError, ValueError, zlib.error):
        raise ProviderError('IMDb 官方评分数据集 gzip 内容损坏或不完整') from None
    return result


def _write_cache(path: Path, data: bytes) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.ratings-', suffix='.tmp', delete=False) as target:
            temporary = Path(target.name)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except OSError:
        raise ProviderError('IMDb 官方评分缓存写入失败') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class ImdbRatings:
    """精确查询 ttID；无条目返回 (None, None)，下载或缓存失败抛 ProviderError。"""

    def __init__(self, settings: ScrapeSettings) -> None:
        self.http = HttpClient(settings)

    def rating(self, imdb_id: str) -> tuple[float | None, int | None]:
        if not isinstance(imdb_id, str) or not re.fullmatch(r'tt[0-9]+', imdb_id):
            raise ProviderError('IMDb ID 格式无效')
        with _cache_lock:
            try:
                cache = ensure_data_dir() / 'imdb' / 'title.ratings.tsv.gz'
                damaged = False
                if cache.exists():
                    stat = cache.stat()
                    if 0 <= time.time() - stat.st_mtime < _CACHE_TTL:
                        try:
                            if stat.st_size > _MAX_COMPRESSED_BYTES:
                                raise ProviderError('IMDb 官方评分缓存超出大小上限')
                            key = (cache, stat.st_mtime_ns, stat.st_size, imdb_id)
                            if key in _recent:
                                _recent.move_to_end(key)
                                return _recent[key]
                            with cache.open('rb') as stream:
                                return _remember(key, _parse(stream, imdb_id))
                        except ProviderError:
                            damaged = True
                try:
                    data = self.http.get_bytes(_URL, max_bytes=_MAX_COMPRESSED_BYTES)
                except HttpError:
                    detail = '缓存损坏，重新下载失败' if damaged else '数据集下载失败，未取得有效评分'
                    raise ProviderError(f'IMDb 官方评分{detail}') from None
                result = _parse(io.BytesIO(data), imdb_id)
                _write_cache(cache, data)
                stat = cache.stat()
                return _remember((cache, stat.st_mtime_ns, stat.st_size, imdb_id), result)
            except OSError:
                raise ProviderError('IMDb 官方评分缓存读取或创建失败') from None
