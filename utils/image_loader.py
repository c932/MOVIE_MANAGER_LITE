"""
异步图片加载器
使用多线程加载海报图片，避免阻塞 UI 主线程
支持海报缩略图本地缓存，大幅提升加载速度
"""
import logging
from collections import OrderedDict
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QPixmap, QImage
from utils.network_mode import is_offline_cache_only

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
_poster_cache_manager = None

def get_poster_cache_manager():
    """获取海报缓存管理器单例"""
    global _poster_cache_manager
    if _poster_cache_manager is None:
        from utils.poster_cache_manager import PosterCacheManager
        _poster_cache_manager = PosterCacheManager()
    return _poster_cache_manager


def _load_and_scale_image(image_path: str, target_width: int, target_height: int) -> QImage:
    """在工作线程中使用 QImage 加载并缩放图片（线程安全）"""
    image = QImage(image_path)
    if image.isNull():
        return QImage()
    return image.scaled(
        target_width, target_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )


def _is_network_path(image_path: str) -> bool:
    """判断是否为网络路径（UNC）。"""
    if not image_path:
        return False
    return image_path.startswith("\\\\") or image_path.startswith("//")


class ImageLoader(QThread):
    """
    图片异步加载线程
    用于在后台加载海报图片，避免 UI 卡顿
    """
    
    # 信号：图片加载完成 (图片路径, QPixmap对象)
    image_loaded = pyqtSignal(str, QPixmap)
    
    def __init__(self, image_path: str, target_width: int, target_height: int):
        """
        初始化图片加载器
        
        Args:
            image_path: 图片文件路径
            target_width: 目标宽度
            target_height: 目标高度
        """
        super().__init__()
        self.image_path = image_path
        self.target_width = target_width
        self.target_height = target_height
    
    def run(self):
        """线程执行入口：优先使用缓存，支持离线模式"""
        try:
            # 获取缓存管理器
            cache_manager = get_poster_cache_manager()
            offline_cache_only = is_offline_cache_only()
            
            # 1. 先尝试从磁盘缓存加载（仅精确尺寸）
            cached_pixmap = cache_manager.get_cached_pixmap(
                self.image_path, self.target_width, self.target_height, allow_cross_size_reuse=False
            )
            
            if cached_pixmap is not None:
                # 精确缓存命中
                logger.debug(f"从缓存加载海报（精确尺寸）: {self.image_path}")
                self.image_loaded.emit(self.image_path, cached_pixmap)
                return

            # 网络路径：离线时仅缓存；在线时允许读取网络原图并回填缓存。
            if _is_network_path(self.image_path):
                cached_pixmap = cache_manager.get_cached_pixmap(
                    self.image_path, self.target_width, self.target_height, allow_cross_size_reuse=True
                )
                if cached_pixmap is not None:
                    self.image_loaded.emit(self.image_path, cached_pixmap)
                    return

                if offline_cache_only:
                    self.image_loaded.emit(self.image_path, QPixmap())
                    return

                # 在线模式：直接读取网络原图。
                image = _load_and_scale_image(self.image_path, self.target_width, self.target_height)
                if image.isNull():
                    self.image_loaded.emit(self.image_path, QPixmap())
                    return

                pixmap = QPixmap.fromImage(image)
                cache_manager.save_to_cache(
                    self.image_path, self.target_width, self.target_height, pixmap
                )
                self.image_loaded.emit(self.image_path, pixmap)
                return

            # 2. 精确缓存未命中，检查原图是否可访问
            file_accessible = False
            try:
                if Path(self.image_path).exists():
                    file_accessible = True
            except OSError:
                # 网络路径不可访问（离线模式）
                file_accessible = False
            
            if file_accessible:
                # 3. 加载原图并缩放（在线模式，优先高清）
                image = _load_and_scale_image(self.image_path, self.target_width, self.target_height)
                
                if image.isNull():
                    logger.warning(f"图片加载失败: {self.image_path}")
                    self.image_loaded.emit(self.image_path, QPixmap())
                    return
                
                # 4. 转换为 QPixmap 并保存到缓存
                pixmap = QPixmap.fromImage(image)
                cache_manager.save_to_cache(
                    self.image_path, self.target_width, self.target_height, pixmap
                )
                logger.debug(f"从原图加载海报: {self.image_path}")
                self.image_loaded.emit(self.image_path, pixmap)
            else:
                # 5. 离线模式，尝试跨尺寸缓存复用
                cached_pixmap = cache_manager.get_cached_pixmap(
                    self.image_path, self.target_width, self.target_height, allow_cross_size_reuse=True
                )
                
                if cached_pixmap is not None:
                    logger.debug(f"从缓存加载海报（跨尺寸/离线模式）: {self.image_path}")
                    self.image_loaded.emit(self.image_path, cached_pixmap)
                else:
                    logger.warning(f"离线模式且无任何缓存: {self.image_path}")
                    self.image_loaded.emit(self.image_path, QPixmap())
            
        except Exception as e:
            logger.error(f"加载图片时出错 [{self.image_path}]: {e}")
            self.image_loaded.emit(self.image_path, QPixmap())


class BatchImageLoader(QThread):
    """
    批量图片加载线程 - 在单个线程中加载多张图片
    比为每张图片创建单独线程更高效
    """
    
    # 信号：单张图片加载完成 (图片路径, QImage对象)
    image_loaded = pyqtSignal(str, object)
    # 信号：批量图片加载完成（[(path, QImage), ...]）
    batch_loaded = pyqtSignal(object)
    # 信号：所有图片加载完成
    all_loaded = pyqtSignal()
    
    def __init__(self, tasks: list, parent=None):
        """
        Args:
            tasks: [(image_path, target_width, target_height), ...]
        """
        super().__init__(parent)
        self.tasks = tasks
        self.is_cancelled = False
    
    def run(self):
        """批量加载图片 - 优先使用缓存，支持离线模式"""
        cache_manager = get_poster_cache_manager()
        offline_cache_only = is_offline_cache_only()
        loaded_items = []
        
        for image_path, target_width, target_height in self.tasks:
            # 检查是否被取消
            if self.is_cancelled:
                break
            
            try:
                if not image_path:
                    continue
                
                # 使用线程安全的 QImage 版本读取缓存（QPixmap 不可在后台线程使用）
                cached_image = cache_manager.get_cached_image(
                    image_path, target_width, target_height, allow_cross_size_reuse=False
                )

                if cached_image is not None:
                    loaded_items.append((image_path, cached_image))
                    continue

                # 网络路径：离线时仅缓存；在线时允许后台线程直接读原图并回填缓存。
                if _is_network_path(image_path):
                    cached_image = cache_manager.get_cached_image(
                        image_path, target_width, target_height, allow_cross_size_reuse=True
                    )
                    if cached_image is not None:
                        loaded_items.append((image_path, cached_image))
                        continue

                    if offline_cache_only:
                        # 离线模式下不访问网络原图，避免阻塞。
                        continue

                    # 在线模式：允许直接读取网络原图。
                    image = _load_and_scale_image(image_path, target_width, target_height)
                    if image.isNull():
                        continue

                    # 使用线程安全的 QImage 缓存写入，避免在工作线程使用 QPixmap。
                    cache_manager.save_to_cache_from_image(
                        image_path, target_width, target_height, image
                    )
                    loaded_items.append((image_path, image))
                    continue
                
                # 2. 精确缓存未命中，检查原图是否可访问
                file_accessible = False
                try:
                    if Path(image_path).exists():
                        file_accessible = True
                except OSError:
                    # 网络路径不可访问（离线模式）
                    file_accessible = False
                
                if file_accessible:
                    # 3. 加载原图并缩放（在线模式，优先高清）
                    image = _load_and_scale_image(image_path, target_width, target_height)
                    if image.isNull():
                        continue
                    
                    # 4. 保存到缓存并发送
                    pixmap = QPixmap.fromImage(image)
                    cache_manager.save_to_cache(
                        image_path, target_width, target_height, pixmap
                    )
                    loaded_items.append((image_path, image))
                else:
                    # 5. 离线模式，尝试跨尺寸缓存复用
                    cached_pixmap = cache_manager.get_cached_pixmap(
                        image_path, target_width, target_height, allow_cross_size_reuse=True
                    )
                    
                    if cached_pixmap is not None:
                        loaded_items.append((image_path, cached_pixmap.toImage()))
                    # 离线模式且无缓存时，不发送信号，继续下一张
                
            except Exception as e:
                logger.error(f"批量加载图片出错 [{image_path}]: {e}")
                # 出错后继续处理下一张图片

        if loaded_items:
            self.batch_loaded.emit(loaded_items)

        self.all_loaded.emit()
    
    def cancel(self):
        """取消加载"""
        self.is_cancelled = True


class ImageCache:
    """
    图片缓存管理器（单例）
    使用 LRU 策略限制内存占用
    """
    
    _instance = None
    MAX_SIZE = 500  # 最多缓存500张海报
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = OrderedDict()
        return cls._instance
    
    def get(self, path: str) -> QPixmap:
        """从缓存获取图片（LRU: 访问后移到最近）"""
        if path in self._cache:
            self._cache.move_to_end(path)
            return self._cache[path]
        return QPixmap()
    
    def set(self, path: str, pixmap: QPixmap):
        """缓存图片（超过上限则淘汰最久未使用的）"""
        if path in self._cache:
            self._cache.move_to_end(path)
        self._cache[path] = pixmap
        while len(self._cache) > self.MAX_SIZE:
            self._cache.popitem(last=False)
    
    def has(self, path: str) -> bool:
        """检查缓存中是否存在"""
        return path in self._cache
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()

    def remove(self, path: str):
        """移除单张缓存图片（若存在）。"""
        if path in self._cache:
            del self._cache[path]
