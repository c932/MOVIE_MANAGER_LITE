"""官方评分数据集：缓存、精确 ID、损坏及下载/解压上限。"""
import gzip
import os
import time
from unittest.mock import patch

import pytest

from scraper.metadata_sources import ProviderError
from scraper.scrape_settings import ScrapeSettings


URL = 'https://datasets.imdbws.com/title.ratings.tsv.gz'
HEADER = b'tconst\taverageRating\tnumVotes\n'


def dataset(rows=b'tt0143145\t6.4\t223243\ntt0111161\t9.3\t3000000\n'):
    return gzip.compress(HEADER + rows, mtime=0)


def install_download(monkeypatch, payload=None, error=None):
    from scraper.scrape_http import HttpClient
    calls = []

    def get_bytes(self, url, max_bytes, **kwargs):
        calls.append((url, max_bytes))
        if error:
            raise error
        return payload if payload is not None else dataset()

    monkeypatch.setattr(HttpClient, 'get_bytes', get_bytes)
    return calls


def provider():
    from scraper.imdb_ratings import ImdbRatings
    return ImdbRatings(ScrapeSettings())


def cache_path(directory):
    return directory / 'imdb' / 'title.ratings.tsv.gz'


def test_download_then_reuse_cache_across_instances_and_titles(monkeypatch, scrape_data_dir):
    calls = install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    assert provider().rating('tt0111161') == (9.3, 3000000)
    assert calls == [(URL, 32 * 1024 * 1024)]
    assert cache_path(scrape_data_dir).read_bytes() == dataset()


def test_only_exact_id_is_returned_and_absence_is_explicit(monkeypatch):
    install_download(monkeypatch, dataset(b'tt01431450\t9.9\t9000\n'))
    assert provider().rating('tt0143145') == (None, None)


def test_cache_expires_after_24_hours(monkeypatch, scrape_data_dir):
    install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    cache = cache_path(scrape_data_dir)
    old = time.time() - 24 * 3600 - 1
    os.utime(cache, (old, old))
    calls = install_download(monkeypatch, dataset(b'tt0143145\t6.5\t223250\n'))
    assert provider().rating('tt0143145') == (6.5, 223250)
    assert len(calls) == 1


def test_corrupt_fresh_cache_is_refreshed_once(monkeypatch, scrape_data_dir):
    cache = cache_path(scrape_data_dir)
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'not gzip')
    calls = install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    assert len(calls) == 1
    assert cache.read_bytes() == dataset()


def test_bad_cache_and_download_failure_are_visible(monkeypatch, scrape_data_dir):
    from scraper.scrape_http import HttpError
    cache = cache_path(scrape_data_dir)
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'not gzip')
    install_download(monkeypatch, error=HttpError('下载失败', 403))
    with pytest.raises(ProviderError, match='缓存.*损坏|损坏.*缓存'):
        provider().rating('tt0143145')


def test_failed_refresh_does_not_serve_stale_or_replace_existing_cache(monkeypatch, scrape_data_dir):
    from scraper.scrape_http import HttpError
    install_download(monkeypatch)
    provider().rating('tt0143145')
    cache = cache_path(scrape_data_dir)
    before = cache.read_bytes()
    old = time.time() - 86401
    os.utime(cache, (old, old))
    install_download(monkeypatch, error=HttpError('网络请求失败'))
    with pytest.raises(ProviderError, match='下载'):
        provider().rating('tt0143145')
    assert cache.read_bytes() == before


@pytest.mark.parametrize('payload', [
    b'not gzip', dataset()[:-4], gzip.compress(b'wrong\theader\n'),
    dataset(b'tt0143145\tNaN\t100\n'), dataset(b'tt0143145\t6.4\t0\n'),
    dataset(b'tt0143145\t6.4\t100\ninvalid row\n'),
    dataset(b'tt0143145\t6.4\t100\ntt0143145\t7.4\t200\n'),
])
def test_invalid_download_is_never_cached_or_partially_returned(monkeypatch, scrape_data_dir, payload):
    install_download(monkeypatch, payload)
    with pytest.raises(ProviderError):
        provider().rating('tt0143145')
    assert not cache_path(scrape_data_dir).exists()


def test_gzip_decompression_is_bounded(monkeypatch, scrape_data_dir):
    from scraper import imdb_ratings
    install_download(monkeypatch, dataset(b'tt0143145\t6.4\t223243\n' + b' ' * 4096))
    monkeypatch.setattr(imdb_ratings, '_MAX_UNCOMPRESSED_BYTES', 1024)
    with pytest.raises(ProviderError, match='上限'):
        provider().rating('tt0143145')
    assert not cache_path(scrape_data_dir).exists()


def test_total_uncompressed_size_is_bounded_even_for_short_valid_rows(monkeypatch, scrape_data_dir):
    from scraper import imdb_ratings
    install_download(monkeypatch, dataset(b'tt0143145\t6.4\t223243\n' + b'tt0111161\t9.3\t3000000\n' * 100))
    monkeypatch.setattr(imdb_ratings, '_MAX_UNCOMPRESSED_BYTES', 1024)
    with pytest.raises(ProviderError, match='上限'):
        provider().rating('tt0143145')
    assert not cache_path(scrape_data_dir).exists()


def test_oversized_cache_is_refetched_without_reading_it(monkeypatch, scrape_data_dir):
    from scraper import imdb_ratings
    cache = cache_path(scrape_data_dir)
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'x' * 1000)
    monkeypatch.setattr(imdb_ratings, '_MAX_COMPRESSED_BYTES', 500)
    calls = install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    assert len(calls) == 1


def test_cache_write_uses_atomic_replace(monkeypatch, scrape_data_dir):
    install_download(monkeypatch)
    original = os.replace
    replacements = []

    def replace(source, destination):
        assert source.parent == destination.parent
        assert source.read_bytes() == dataset()
        replacements.append((source, destination))
        return original(source, destination)

    with patch('os.replace', side_effect=replace):
        assert provider().rating('tt0143145') == (6.4, 223243)
    assert len(replacements) == 1
    assert list(cache_path(scrape_data_dir).parent.iterdir()) == [cache_path(scrape_data_dir)]


def test_atomic_write_failure_is_visible_and_cleans_tempfile(monkeypatch, scrape_data_dir):
    install_download(monkeypatch)
    with patch('os.replace', side_effect=OSError('private path')):
        with pytest.raises(ProviderError, match='缓存') as error:
            provider().rating('tt0143145')
    assert 'private path' not in str(error.value)
    assert list(cache_path(scrape_data_dir).parent.iterdir()) == []


@pytest.mark.parametrize('identity', ['', 'tt0143145/ratings', None])
def test_invalid_id_does_not_download(monkeypatch, identity):
    calls = install_download(monkeypatch)
    with pytest.raises(ProviderError):
        provider().rating(identity)
    assert calls == []


@pytest.mark.parametrize('status', [202, 403, None])
def test_imdb_provider_uses_official_dataset_when_page_access_is_blocked(monkeypatch, status):
    from scraper.imdb_provider import ImdbProvider
    from scraper.scrape_http import HttpClient, HttpError
    calls = []

    def get_bytes(self, url, max_bytes, **kwargs):
        calls.append(url)
        if url == 'https://www.imdb.com/title/tt0143145/':
            raise HttpError('网页访问受限', status)
        assert url == URL
        return dataset()

    monkeypatch.setattr(HttpClient, 'get_bytes', get_bytes)
    assert ImdbProvider(ScrapeSettings()).rating('tt0143145') == (6.4, 223243)
    assert len(calls) == 2


def test_recent_query_reuses_parsed_result_and_file_change_invalidates_it(monkeypatch, scrape_data_dir):
    from scraper import imdb_ratings
    install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    original = imdb_ratings._parse
    with patch.object(imdb_ratings, '_parse', wraps=original) as parse:
        assert provider().rating('tt0143145') == (6.4, 223243)
        assert parse.call_count == 0
        cache = cache_path(scrape_data_dir)
        cache.write_bytes(dataset(b'tt0143145\t6.8\t12345\n'))
        assert provider().rating('tt0143145') == (6.8, 12345)
        assert parse.call_count == 1


def test_small_filesystem_clock_skew_does_not_redownload_older_ratings(monkeypatch, scrape_data_dir):
    from scraper import imdb_ratings
    calls = install_download(monkeypatch)
    assert provider().rating('tt0143145') == (6.4, 223243)
    cache = cache_path(scrape_data_dir)
    cache.write_bytes(dataset(b'tt0143145\t6.8\t12345\n'))
    now = cache.stat().st_mtime - 0.001
    monkeypatch.setattr(imdb_ratings.time, 'time', lambda: now)
    assert provider().rating('tt0143145') == (6.8, 12345)
    assert len(calls) == 1


def test_identity_error_and_normal_unrated_page_never_request_dataset(monkeypatch):
    from scraper.imdb_provider import ImdbProvider
    from scraper.scrape_http import HttpClient
    calls = []
    body = b'<script id="__NEXT_DATA__">{"props":{"pageProps":{"aboveTheFoldData":{"id":"tt0143145"}}}}</script>'

    def get_bytes(self, url, max_bytes, **kwargs):
        calls.append(url)
        return body

    monkeypatch.setattr(HttpClient, 'get_bytes', get_bytes)
    assert ImdbProvider(ScrapeSettings()).rating('tt0143145') == (None, None)
    assert len(calls) == 1
    body = body.replace(b'tt0143145', b'tt0111161')
    with pytest.raises(ProviderError):
        ImdbProvider(ScrapeSettings()).rating('tt0143145')
    assert len(calls) == 2


def test_challenge_page_uses_official_dataset(monkeypatch):
    from scraper.imdb_provider import ImdbProvider
    from scraper.scrape_http import HttpClient

    def get_bytes(self, url, max_bytes, **kwargs):
        if url == URL:
            return dataset()
        return b'<html><title>Robot Check</title><p>Verify you are human</p></html>'

    monkeypatch.setattr(HttpClient, 'get_bytes', get_bytes)
    assert ImdbProvider(ScrapeSettings()).rating('tt0143145') == (6.4, 223243)
