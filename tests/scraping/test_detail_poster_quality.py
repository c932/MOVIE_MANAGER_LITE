from PyQt6.QtGui import QImage, QPixmap

from tests.scraping.test_scrape_dialog import app


def test_detail_online_network_poster_does_not_reuse_wall_thumbnail(app, monkeypatch):
    from ui import detail_panel
    calls = []
    def cached(_path, _width, _height, *, allow_cross_size_reuse=False):
        calls.append(allow_cross_size_reuse)
        return QPixmap(20, 30) if allow_cross_size_reuse else None
    monkeypatch.setattr(detail_panel, "_get_poster_cache_manager",
                        lambda: type("Cache", (), {"get_cached_pixmap": staticmethod(cached)})())
    monkeypatch.setattr(detail_panel, "is_offline_cache_only", lambda: False)
    assert detail_panel._load_poster_with_cache(r"\\server\poster.jpg", 280, 420).isNull()
    assert calls == [False]


def test_detail_offline_network_poster_reuses_available_thumbnail(app, monkeypatch):
    from ui import detail_panel
    def cached(_path, _width, _height, *, allow_cross_size_reuse=False):
        return QPixmap(200, 300) if allow_cross_size_reuse else None
    monkeypatch.setattr(detail_panel, "_get_poster_cache_manager",
                        lambda: type("Cache", (), {"get_cached_pixmap": staticmethod(cached)})())
    monkeypatch.setattr(detail_panel, "is_offline_cache_only", lambda: True)
    pixmap = detail_panel._load_poster_with_cache(r"\\server\poster.jpg", 280, 420)
    assert pixmap.width() == 200 and pixmap.height() == 300


def test_single_image_loader_online_network_bypasses_cross_size_cache(app, monkeypatch):
    from utils import image_loader
    calls = []
    saved = []
    class Cache:
        @staticmethod
        def get_cached_pixmap(_path, _width, _height, *, allow_cross_size_reuse=False):
            calls.append(allow_cross_size_reuse)
            return QPixmap(20, 30) if allow_cross_size_reuse else None
        @staticmethod
        def save_to_cache(path, width, height, pixmap):
            saved.append((path, pixmap.width(), pixmap.height()))
    monkeypatch.setattr(image_loader, "get_poster_cache_manager", lambda: Cache())
    monkeypatch.setattr(image_loader, "is_offline_cache_only", lambda: False)
    def load_original(_path, width, height):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(0xCC3333)
        return image
    monkeypatch.setattr(image_loader, "_load_and_scale_image", load_original)
    loaded = []
    loader = image_loader.ImageLoader(r"\\server\poster.jpg", 280, 420)
    loader.image_loaded.connect(lambda path, pixmap: loaded.append((path, pixmap)))
    loader.run()
    assert loaded and loaded[0][1].width() == 280 and loaded[0][1].height() == 420
    assert calls == [False]
    assert saved == [(r"\\server\poster.jpg", 280, 420)]


def test_batch_loader_online_network_bypasses_cross_size_cache(app, monkeypatch):
    from utils import image_loader
    calls = []
    saved = []
    class Cache:
        @staticmethod
        def get_cached_image(_path, _width, _height, *, allow_cross_size_reuse=False):
            calls.append(allow_cross_size_reuse)
            if allow_cross_size_reuse:
                return QImage(20, 30, QImage.Format.Format_RGB32)
            return None
        @staticmethod
        def save_to_cache_from_image(path, width, height, image):
            saved.append((path, image.width(), image.height()))
    monkeypatch.setattr(image_loader, "get_poster_cache_manager", lambda: Cache())
    monkeypatch.setattr(image_loader, "is_offline_cache_only", lambda: False)
    def load_original(_path, width, height):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(0x3366CC)
        return image
    monkeypatch.setattr(image_loader, "_load_and_scale_image", load_original)
    batches = []
    loader = image_loader.BatchImageLoader([(r"\\server\poster.jpg", 200, 300)])
    loader.batch_loaded.connect(lambda items: batches.extend(items))
    loader.run()
    assert batches and batches[0][1].width() == 200
    assert calls == [False]
    assert saved == [(r"\\server\poster.jpg", 200, 300)]
