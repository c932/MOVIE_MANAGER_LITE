"""
游戏封面批量加载器
URL 封面加载：磁盘缓存优先，未命中时在线下载并回填缓存
"""
import gzip
import logging
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QImage, QPixmap, QColor

from utils.image_loader import get_poster_cache_manager

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 裁切填满模式的缓存键后缀：v2 表示 contain 模式改进版（横版图居中显示）
_COVER_CACHE_SUFFIX = "#cv2"
_LEGACY_COVER_CACHE_SUFFIX = "#cv1"


def cover_cache_keys(url: str) -> tuple[str, str]:
    return url + _COVER_CACHE_SUFFIX, url + _LEGACY_COVER_CACHE_SUFFIX

# 并发下载数：串行下载时一张慢图（超时 8s）会拖住整面墙
_MAX_WORKERS = 8


def fit_cover(image: QImage, target_width: int, target_height: int) -> QImage:
    """
    智能裁切填满：
    - 竖版图片（宽高比接近目标）：直接缩放
    - 横版图片（明显宽于目标）：contain 模式居中显示，上下留深色边
    - 竖版图片（明显窄于目标）：center-crop 裁切后缩放
    """
    if image.isNull() or target_width <= 0 or target_height <= 0:
        return image
    target_ratio = target_width / target_height
    src_ratio = image.width() / image.height()

    # 横版图片（宽高比 > 1.5）：contain 模式居中显示，不裁切
    # 这样可以显示完整图片，虽然上下有边但比被裁切丢失内容好
    if src_ratio > 1.5:
        result = QImage(target_width, target_height, QImage.Format.Format_ARGB32)
        result.fill(QColor(30, 30, 30))  # 深灰背景
        scaled = image.scaled(target_width, target_height,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        x = (target_width - scaled.width()) // 2
        y = (target_height - scaled.height()) // 2
        from PyQt6.QtGui import QPainter
        painter = QPainter(result)
        painter.drawImage(x, y, scaled)
        painter.end()
        return result

    # 接近目标比例：直接缩放
    if abs(src_ratio - target_ratio) <= 0.01:
        return image.scaled(target_width, target_height,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)

    # 竖版但比例不匹配：center-crop 裁切后缩放
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


def download_image_bytes(url: str, timeout: float = 6.0) -> bytes:
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
        urls = tuple(dict.fromkeys(filter(None, urls)))

        def publish(url, image):
            if self.is_cancelled:
                return None
            self.image_loaded.emit(url, image)
            return url, image

        # 检查所有候选的本地数据，避免为了已有备用图的游戏等待 CDN。
        for url in urls:
            if self.is_cancelled:
                return None
            try:
                key, legacy_key = cover_cache_keys(url)
                cached = cache_manager.get_cached_image(key, target_width, target_height)
                if cached is not None and not cached.isNull():
                    return publish(url, cached)
                if os.path.exists(url):
                    image = QImage(url)
                    if not image.isNull():
                        scaled = fit_cover(image, target_width, target_height)
                        cache_manager.save_to_cache_from_image(key, target_width, target_height, scaled)
                        return publish(url, scaled)
                for key in (key, legacy_key):
                    cached = cache_manager.get_cached_image(
                        key, target_width, target_height, allow_cross_size_reuse=True)
                    if cached is not None and not cached.isNull():
                        return publish(url, cached)
            except Exception as e:
                logger.debug(f"读取封面缓存失败 [{url}]: {e}")

        for url in urls:
            if self.is_cancelled:
                return None
            if not url.lower().startswith(("https://", "http://")):
                continue
            try:
                image = QImage.fromData(download_image_bytes(url))
                if image.isNull():
                    logger.warning(f"封面数据无效: {url}")
                    continue
                if self.is_cancelled:
                    return None
                scaled = fit_cover(image, target_width, target_height)
                cache_key = url + _COVER_CACHE_SUFFIX
                cache_manager.save_to_cache_from_image(cache_key, target_width, target_height, scaled)
                return publish(url, scaled)
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
