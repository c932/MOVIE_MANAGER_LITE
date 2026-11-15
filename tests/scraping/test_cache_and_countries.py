import json

from PyQt6.QtGui import QImage

from tests.scraping.test_scrape_dialog import app


def test_cache_users_share_pending_entries_and_invalidation(tmp_path, monkeypatch):
    from utils.poster_cache_manager import PosterCacheManager
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', tmp_path / 'posters')
    wall, detail = PosterCacheManager(), PosterCacheManager()
    path = r'\\nas\movie\poster.jpg'
    monkeypatch.setattr(wall, '_get_original_mtime', lambda _: None)
    image = QImage(280, 420, QImage.Format.Format_RGB32)
    image.fill(0xCC3333)
    assert wall.save_to_cache_from_image(path, 280, 420, image)
    assert detail.get_cached_image(path, 200, 300, True) is not None
    detail.flush_index()
    assert len(json.loads((tmp_path / 'posters/index.json').read_text())['entries']) == 1
    detail.invalidate_cache_for_path(path)
    assert wall.get_cached_image(path, 280, 420) is None


def test_offline_cache_recovers_existing_jpg_without_index(app, tmp_path, monkeypatch):
    from utils.poster_cache_manager import PosterCacheManager
    from ui import detail_panel
    from utils import image_loader
    directory = tmp_path / 'posters'
    directory.mkdir()
    monkeypatch.setattr(PosterCacheManager, 'CACHE_DIR', directory)
    path = r'\\nas\movie\poster.jpg'
    import hashlib
    key = hashlib.md5(f'{path}_280x420'.encode()).hexdigest()
    image = QImage(280, 420, QImage.Format.Format_RGB32)
    image.fill(0x3366CC)
    assert image.save(str(directory / f'{key}.jpg'))
    cache = PosterCacheManager()
    monkeypatch.setattr(cache, '_get_original_mtime', lambda _: (_ for _ in ()).throw(AssertionError('离线禁止探测 NAS')))
    monkeypatch.setattr(detail_panel, '_get_poster_cache_manager', lambda: cache)
    monkeypatch.setattr(detail_panel, 'is_offline_cache_only', lambda: True)
    monkeypatch.setattr(image_loader, 'get_poster_cache_manager', lambda: cache)
    monkeypatch.setattr(image_loader, 'is_offline_cache_only', lambda: True)
    loaded = []
    loader = image_loader.BatchImageLoader([(path, 200, 300)])
    loader.batch_loaded.connect(loaded.extend)
    loader.run()
    assert loaded and loaded[0][1].width() == 200
    assert not detail_panel._load_poster_with_cache(path, 280, 420).isNull()
    # 模拟下次启动：从已恢复的索引读取，不依赖 NAS。
    cache.flush_index()
    monkeypatch.setattr(PosterCacheManager, '_instances', {})
    restarted = PosterCacheManager()
    assert restarted.get_cached_image(path, 280, 420) is not None


def test_tmdb_countries_are_localized_before_nfo_write(monkeypatch):
    from scraper.metadata_sources import TmdbProvider
    from scraper.scrape_models import Candidate
    from scraper.scrape_settings import ScrapeSettings
    from tests.scraping.test_sources import transport, movie_record
    transport(monkeypatch, [dict(movie_record(), production_countries=[
        {'iso_3166_1': 'US', 'name': 'United States of America'},
        {'iso_3166_1': 'MX', 'name': 'Mexico'},
        {'iso_3166_1': 'ZA', 'name': 'South Africa'}]),
        {'imdb_id': None}, {'cast': [], 'crew': []}, {'posters': []}])
    result = TmdbProvider(ScrapeSettings(tmdb_api_key='fake')).details(Candidate('tmdb', '1', '电影'))
    assert result.fields['countries'] == ['美国', '墨西哥', '南非']


def test_cached_movie_and_old_nfo_countries_are_localized(tmp_path):
    from models.movie import Movie
    from parsers.nfo_parser import NFOParser
    from utils.cache_manager import CacheManager
    countries = ['Australia', 'Hong Kong', 'United States of America', 'Unknown Land']
    expected = ['澳大利亚', '中国香港', '美国', 'Unknown Land']
    assert Movie(countries=countries).countries == expected
    assert CacheManager()._deserialize_movie({'countries': countries}).countries == expected
    nfo = tmp_path / 'movie.nfo'
    nfo.write_text('<movie><title>电影</title><country>United Kingdom</country><country>United States of America</country></movie>', encoding='utf-8')
    assert NFOParser.parse(str(nfo)).countries == ['英国', '美国']
