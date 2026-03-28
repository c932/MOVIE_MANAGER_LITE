"""
海报缓存管理器
用于缓存海报缩略图，避免每次启动重复加载和缩放大图片
"""
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt

from utils.app_paths import ensure_data_dir

logger = logging.getLogger(__name__)


class PosterCacheManager:
    """海报缩略图缓存管理器"""
    
    CACHE_DIR = ensure_data_dir() / ".poster_cache"
    CACHE_VERSION = "1.0"
    
    def __init__(self):
        """初始化缓存管理器"""
        self._lock = threading.Lock()  # 线程锁保护缓存索引
        self._save_lock = threading.Lock()  # 仅用于索引文件写入串行化
        self._pending_index_updates = 0
        self._flush_threshold = 20
        self._ensure_cache_dir()
        self._cache_index_file = self.CACHE_DIR / "index.json"
        self._cache_index = self._load_cache_index()
        self._path_to_cache_keys = self._build_path_index()

    def _build_path_index(self) -> dict:
        """构建 original_path -> [cache_key, ...] 的快速索引。"""
        path_index = {}
        entries = self._cache_index.get("entries", {})
        for cache_key, entry in entries.items():
            original_path = entry.get("original_path")
            if not original_path:
                continue
            path_index.setdefault(original_path, []).append(cache_key)
        return path_index
    
    def _ensure_cache_dir(self):
        """确保缓存目录存在"""
        if not self.CACHE_DIR.exists():
            self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建海报缓存目录: {self.CACHE_DIR.absolute()}")
    
    def _load_cache_index(self) -> dict:
        """加载缓存索引文件"""
        if not self._cache_index_file.exists():
            return {"version": self.CACHE_VERSION, "entries": {}}
        
        try:
            with open(self._cache_index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get("version") != self.CACHE_VERSION:
                    logger.warning("缓存版本不匹配，清空缓存")
                    return {"version": self.CACHE_VERSION, "entries": {}}
                return data
        except Exception as e:
            logger.error(f"加载缓存索引失败: {e}")
            return {"version": self.CACHE_VERSION, "entries": {}}
    
    def _save_cache_index(self, data: Optional[dict] = None):
        """保存缓存索引文件（串行写入，避免并发覆盖）"""
        try:
            payload = data if data is not None else self._cache_index
            with self._save_lock:
                with open(self._cache_index_file, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存索引失败: {e}")

    def _flush_cache_index_snapshot(self):
        """在短锁内复制索引，锁外落盘，避免 UI 读取时长时间等待。"""
        with self._lock:
            snapshot = {
                "version": self._cache_index.get("version", self.CACHE_VERSION),
                "entries": dict(self._cache_index.get("entries", {}))
            }
            self._pending_index_updates = 0
        self._save_cache_index(snapshot)
    
    def _get_cache_key(self, image_path: str, width: int, height: int) -> str:
        """
        生成缓存键（基于图片路径和尺寸）
        
        Args:
            image_path: 原图路径
            width: 目标宽度
            height: 目标高度
        
        Returns:
            缓存键（MD5哈希）
        """
        key_string = f"{image_path}_{width}x{height}"
        return hashlib.md5(key_string.encode('utf-8')).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """
        获取缓存文件路径
        
        Args:
            cache_key: 缓存键
        
        Returns:
            缓存文件路径
        """
        return self.CACHE_DIR / f"{cache_key}.jpg"
    
    def _get_original_mtime(self, image_path: str) -> Optional[float]:
        """
        获取原图文件的修改时间
        
        Args:
            image_path: 原图路径
        
        Returns:
            修改时间戳，如果文件不存在或网络不可访问则返回 None
        """
        try:
            return Path(image_path).stat().st_mtime
        except (OSError, Exception):
            # 文件不存在或网络路径不可访问
            return None

    @staticmethod
    def _is_network_path(image_path: str) -> bool:
        """判断是否为网络路径（UNC）。"""
        if not image_path:
            return False
        return image_path.startswith("\\\\") or image_path.startswith("//")
    
    def has_valid_cache(self, image_path: str, width: int, height: int) -> bool:
        """
        检查是否存在有效的缓存
        
        Args:
            image_path: 原图路径
            width: 目标宽度
            height: 目标高度
        
        Returns:
            缓存是否存在且有效
        """
        cache_key = self._get_cache_key(image_path, width, height)
        
        # 检查缓存文件是否存在
        cache_path = self._get_cache_path(cache_key)
        if not cache_path.exists():
            return False
        
        # 检查索引中是否有记录
        entries = self._cache_index.get("entries", {})
        if cache_key not in entries:
            return False

        # 网络路径在离线场景下 stat 代价高（可能秒级阻塞），优先信任本地缓存。
        if self._is_network_path(image_path):
            return True
        
        # 检查原图是否被修改（支持离线模式）
        entry = entries[cache_key]
        original_mtime = self._get_original_mtime(image_path)
        
        if original_mtime is None:
            # 原图不可访问（网络断开等），但缓存存在，允许使用（离线模式）
            logger.debug(f"原图不可访问，使用离线缓存: {image_path}")
            return True
        
        cached_mtime = entry.get("original_mtime")
        if cached_mtime != original_mtime:
            # 原图已被修改，缓存过期
            return False
        
        return True
    
    def has_any_cache(self, image_path: str) -> bool:
        """
        快速检查是否存在任意尺寸的缓存（不检查文件系统）
        用于离线模式优化，避免超时的网络路径检查
        
        Args:
            image_path: 原图路径
        
        Returns:
            是否存在任意尺寸的缓存
        """
        try:
            with self._lock:
                keys = self._path_to_cache_keys.get(image_path, [])
                return len(keys) > 0
        except Exception:
            return False
    
    def get_cached_pixmap(self, image_path: str, width: int, height: int, 
                         allow_cross_size_reuse: bool = False) -> Optional[QPixmap]:
        """
        从缓存加载缩略图
        
        Args:
            image_path: 原图路径
            width: 目标宽度
            height: 目标高度
            allow_cross_size_reuse: 是否允许跨尺寸复用（离线模式时为True）
        
        Returns:
            缓存的 QPixmap，如果缓存无效则返回 None
        """
        # 1. 先尝试精确匹配
        if self.has_valid_cache(image_path, width, height):
            try:
                cache_key = self._get_cache_key(image_path, width, height)
                cache_path = self._get_cache_path(cache_key)
                
                pixmap = QPixmap(str(cache_path))
                if not pixmap.isNull():
                    logger.debug(f"从缓存加载海报（精确匹配）: {image_path} ({width}x{height})")
                    return pixmap
            except Exception as e:
                logger.error(f"加载精确缓存失败: {e}")
        
        # 2. 精确匹配失败，如果允许跨尺寸复用（离线模式），则查找其他尺寸的缓存
        if allow_cross_size_reuse:
            try:
                # 先从快速索引取候选，再做文件检查
                with self._lock:
                    entries = dict(self._cache_index.get("entries", {}))
                    candidate_keys = list(self._path_to_cache_keys.get(image_path, []))
                
                # 在锁外遍历候选，避免全表扫描
                found_cache = None
                for cache_key in candidate_keys:
                    entry = entries.get(cache_key)
                    if not entry:
                        continue
                    cache_path = self._get_cache_path(cache_key)
                    if cache_path.exists():
                        found_cache = (cache_path, entry)
                        break
                
                # 在循环外处理找到的缓存
                if found_cache:
                    cache_path, entry = found_cache
                    pixmap = QPixmap(str(cache_path))
                    if not pixmap.isNull():
                        # 重新缩放到目标尺寸
                        scaled = pixmap.scaled(
                            width, height,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        cached_width = entry.get("width", 0)
                        cached_height = entry.get("height", 0)
                        logger.debug(f"从缓存加载海报（跨尺寸复用/离线模式）: {image_path} ({cached_width}x{cached_height} -> {width}x{height})")
                        # 注意：这里可能在 UI 线程中被调用，避免同步写磁盘导致卡顿。
                        return scaled
            except Exception as e:
                logger.error(f"查找跨尺寸缓存失败: {e}")
        
        return None
    
    def get_cached_image(self, image_path: str, width: int, height: int,
                          allow_cross_size_reuse: bool = False) -> Optional[QImage]:
        """
        线程安全版本：使用 QImage 加载缓存（可在后台线程调用）。
        QPixmap 不是线程安全的，后台线程必须用此方法。
        """
        # 1. 先尝试精确匹配
        if self.has_valid_cache(image_path, width, height):
            try:
                cache_key = self._get_cache_key(image_path, width, height)
                cache_path = self._get_cache_path(cache_key)
                image = QImage(str(cache_path))
                if not image.isNull():
                    return image
            except Exception as e:
                logger.error(f"加载精确缓存（QImage）失败: {e}")

        if not allow_cross_size_reuse:
            return None

        # 2. 跨尺寸复用
        try:
            with self._lock:
                entries = dict(self._cache_index.get("entries", {}))
                candidate_keys = list(self._path_to_cache_keys.get(image_path, []))

            for cache_key in candidate_keys:
                entry = entries.get(cache_key)
                if not entry:
                    continue
                cache_path = self._get_cache_path(cache_key)
                if cache_path.exists():
                    image = QImage(str(cache_path))
                    if not image.isNull():
                        scaled = image.scaled(
                            width, height,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        return scaled
        except Exception as e:
            logger.error(f"查找跨尺寸缓存（QImage）失败: {e}")

        return None

    def save_to_cache(self, image_path: str, width: int, height: int, pixmap: QPixmap) -> bool:
        """
        保存缩略图到缓存
        
        Args:
            image_path: 原图路径
            width: 目标宽度
            height: 目标高度
            pixmap: 要缓存的 QPixmap
        
        Returns:
            是否保存成功
        """
        try:
            cache_key = self._get_cache_key(image_path, width, height)
            cache_path = self._get_cache_path(cache_key)
            
            # 保存为 JPG 格式（更小的文件大小）
            if not pixmap.save(str(cache_path), "JPG", quality=85):
                logger.warning(f"保存缓存失败: {cache_path}")
                return False
            
            # 更新索引（线程安全，尽量缩短持锁时间）
            should_flush = False
            with self._lock:
                original_mtime = self._get_original_mtime(image_path)
                if "entries" not in self._cache_index:
                    self._cache_index["entries"] = {}
                self._cache_index["entries"][cache_key] = {
                    "original_path": image_path,
                    "original_mtime": original_mtime,
                    "width": width,
                    "height": height,
                    "cache_path": str(cache_path)
                }
                keys = self._path_to_cache_keys.setdefault(image_path, [])
                if cache_key not in keys:
                    keys.append(cache_key)
                self._pending_index_updates += 1
                if self._pending_index_updates >= self._flush_threshold:
                    should_flush = True

            # 锁外落盘，避免阻塞读取路径
            if should_flush:
                self._flush_cache_index_snapshot()
            
            logger.debug(f"保存海报到缓存: {image_path} ({width}x{height}) -> {cache_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
            return False
    
    def save_to_cache_from_image(self, image_path: str, width: int, height: int, image: QImage) -> bool:
        """
        线程安全版本：将 QImage 保存到缓存（可在后台线程调用）。
        QPixmap.save() 不是线程安全的，后台线程必须用此方法。
        """
        try:
            cache_key = self._get_cache_key(image_path, width, height)
            cache_path = self._get_cache_path(cache_key)

            if not image.save(str(cache_path), "JPG", 85):
                logger.warning(f"保存缓存（QImage）失败: {cache_path}")
                return False

            should_flush = False
            with self._lock:
                original_mtime = self._get_original_mtime(image_path)
                if "entries" not in self._cache_index:
                    self._cache_index["entries"] = {}
                self._cache_index["entries"][cache_key] = {
                    "original_path": image_path,
                    "original_mtime": original_mtime,
                    "width": width,
                    "height": height,
                    "cache_path": str(cache_path)
                }
                keys = self._path_to_cache_keys.setdefault(image_path, [])
                if cache_key not in keys:
                    keys.append(cache_key)
                self._pending_index_updates += 1
                if self._pending_index_updates >= self._flush_threshold:
                    should_flush = True

            if should_flush:
                self._flush_cache_index_snapshot()

            logger.debug(f"保存海报到缓存（QImage）: {image_path} ({width}x{height})")
            return True

        except Exception as e:
            logger.error(f"保存缓存（QImage）失败: {e}")
            return False

    def clear_cache(self) -> Tuple[int, int]:
        """
        清除所有缓存
        
        Returns:
            (清除的文件数, 总大小MB)
        """
        try:
            total_size = 0
            file_count = 0
            
            # 删除所有缓存文件
            for cache_file in self.CACHE_DIR.glob("*.jpg"):
                try:
                    size = cache_file.stat().st_size
                    cache_file.unlink()
                    total_size += size
                    file_count += 1
                except Exception as e:
                    logger.error(f"删除缓存文件失败 {cache_file}: {e}")
            
            # 清空索引
            self._cache_index = {"version": self.CACHE_VERSION, "entries": {}}
            self._path_to_cache_keys = {}
            self._pending_index_updates = 0
            self._save_cache_index()
            
            total_size_mb = total_size / (1024 * 1024)
            logger.info(f"清除海报缓存: {file_count} 个文件, {total_size_mb:.2f} MB")
            return file_count, total_size_mb
            
        except Exception as e:
            logger.error(f"清除缓存失败: {e}")
            return 0, 0

    def invalidate_cache_for_path(self, image_path: str) -> int:
        """按原图路径删除对应的所有缓存项，返回删除数量。"""
        if not image_path:
            return 0

        removed = 0
        try:
            with self._lock:
                keys = list(self._path_to_cache_keys.get(image_path, []))

            for cache_key in keys:
                cache_path = self._get_cache_path(cache_key)
                try:
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception as e:
                    logger.debug(f"删除缓存文件失败（忽略）: {cache_path}, {e}")

                with self._lock:
                    entries = self._cache_index.get("entries", {})
                    if cache_key in entries:
                        del entries[cache_key]
                        removed += 1

            with self._lock:
                if image_path in self._path_to_cache_keys:
                    del self._path_to_cache_keys[image_path]

            if removed > 0:
                self._flush_cache_index_snapshot()

            return removed
        except Exception as e:
            logger.error(f"按路径失效海报缓存失败: {e}")
            return removed
    
    def get_cache_stats(self) -> dict:
        """
        获取缓存统计信息
        
        Returns:
            缓存统计字典 {"count": int, "size_mb": float}
        """
        try:
            total_size = 0
            file_count = 0
            
            for cache_file in self.CACHE_DIR.glob("*.jpg"):
                try:
                    total_size += cache_file.stat().st_size
                    file_count += 1
                except Exception:
                    pass
            
            return {
                "count": file_count,
                "size_mb": total_size / (1024 * 1024)
            }
            
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {"count": 0, "size_mb": 0.0}
    
    def cleanup_orphaned_cache(self) -> int:
        """
        清理孤立的缓存文件（原图已不存在）
        
        Returns:
            清理的文件数
        """
        try:
            cleaned_count = 0
            entries = self._cache_index.get("entries", {}).copy()
            
            for cache_key, entry in entries.items():
                original_path = entry.get("original_path")
                # 避免对 UNC/NAS 路径执行 exists()，离线时可能产生秒级阻塞。
                if original_path and self._is_network_path(original_path):
                    continue

                if not original_path or not Path(original_path).exists():
                    # 原图不存在，删除缓存
                    cache_path = self._get_cache_path(cache_key)
                    if cache_path.exists():
                        cache_path.unlink()
                    
                    # 从索引中移除
                    del self._cache_index["entries"][cache_key]
                    cleaned_count += 1
            
            if cleaned_count > 0:
                self._path_to_cache_keys = self._build_path_index()
                self._save_cache_index()
                logger.info(f"清理孤立缓存: {cleaned_count} 个文件")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"清理孤立缓存失败: {e}")
            return 0

    def flush_index(self):
        """主动落盘索引（如应用退出时调用）。"""
        self._flush_cache_index_snapshot()

