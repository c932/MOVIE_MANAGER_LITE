"""
游戏封面批量加载器
URL 封面加载：磁盘缓存优先，未命中时在线下载并回填缓存
"""
import gzip
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QImage, QPixmap

from utils.image_loader import get_poster_cache_manager

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 裁切填满模式的缓存键后缀：区别于旧版 KeepAspectRatio 产物的同尺寸缓存
_COVER_CACHE_SUFFIX = "#cv1"

# 并发下载数：串行下载时一张慢图（超时 8s）会拖住整面墙
_MAX_WORKERS = 6


def fit_cover(image: QImage, target_width: int, target_height: int) -> QImage:
    """
    裁切填满（cover 模式）：源图宽高比与目标不符时中心裁切再缩放，
    保证输出恰好铺满 target——竖版海报位不允许横版图留边
    """
    if image.isNull() or target_width <= 0 or target_height <= 0:
        return image
    target_ratio = target_width / target_height
    src_ratio = image.width() / image.height()
    if abs(src_ratio - target_ratio) <= 0.01:
        return image.scaled(target_width, target_height,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
    if src_ratio > target_ratio:   # 过宽 → 裁两侧
        new_w = max(1, round(image.height() * target_ratio))
        x = (image.width() - new_w) // 2
        cropped = image.copy(x, 0, new_w, image.height())
    else:                          # 过高 → 裁上下
        new_h = max(1, round(image.width() / target_ratio))
        y = (image.height() - new_h) // 2
        cropped = image.copy(0, y, image.width(), new_h)
    return cropped.scaled(target_width, target_height,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


def download_image_bytes(url: str, timeout: float = 8.0) -> bytes:
    """下载图片字节（自动处理 gzip），失败抛异常"""
    request = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "image/*,*/*;q=0.8",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        data = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


class BatchCoverLoader(QThread):
    """
    批量封面加载线程（小并发池，单张完成即发信号）
    tasks: [([候选url, ...], target_width, target_height), ...]
    每个任务按候选顺序尝试，成功后以实际命中的 url 发射信号
    """
    # 信号：单张加载完成 (url, QImage)
    image_loaded = pyqtSignal(str, object)
    # 信号：批量加载完成 ([(url, QImage), ...])
    batch_loaded = pyqtSignal(object)
    # 信号：全部任务结束
    all_loaded = pyqtSignal()

    def __init__(self, tasks: list, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.is_cancelled = False

    def _load_single(self, urls, target_width: int, target_height: int):
        """处理单个任务：磁盘缓存优先，未命中下载并回填。返回 (url, QImage) 或 None"""
        cache_manager = get_poster_cache_manager()
        for url in urls:
            if self.is_cancelled:
                return None
            if not url:
                continue
            cache_key = url + _COVER_CACHE_SUFFIX
            try:
                cached = cache_manager.get_cached_image(cache_key, target_width, target_height)
                if cached is not None and not cached.isNull():
                    # 在子线程里只传 QImage，QPixmap 不能在非 GUI 线程创建。
                    # 主线程的 apply_chunk 会用 QPixmap.fromImage() 转换。
                    self.image_loaded.emit(url, cached)
                    return url, cached

                data = download_image_bytes(url)
                image = QImage.fromData(data)
                if image.isNull():
                    logger.warning(f"封面数据无效: {url}")
                    continue
                scaled = fit_cover(image, target_width, target_height)
                cache_manager.save_to_cache_from_image(cache_key, target_width, target_height, scaled)
                self.image_loaded.emit(url, scaled)
                return url, scaled
            except Exception as e:
                logger.debug(f"封面下载失败 [{url}]: {e}")
        return None

    def run(self):
        loaded_items = []
        workers = max(1, min(_MAX_WORKERS, len(self.tasks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._load_single, urls, width, height): idx
                       for idx, (urls, width, height) in enumerate(self.tasks)}
            for future in as_completed(futures):
                if self.is_cancelled:
                    break
                try:
                    result = future.result()
                except Exception as e:
                    logger.debug(f"封面任务异常: {e}")
                    result = None
                if result:
                    loaded_items.append(result)

        if loaded_items:
            self.batch_loaded.emit(loaded_items)
        self.all_loaded.emit()

    def cancel(self):
        self.is_cancelled = True
