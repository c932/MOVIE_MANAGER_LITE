"""
收藏管理器 - 管理电影收藏状态
使用 JSON 文件持久化存储
"""
import json
import os
from pathlib import Path
from typing import Set
import logging

from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class FavoriteManager:
    """电影收藏管理器（基于 NFO 路径）"""
    
    def __init__(self, data_file: str = None):
        """
        初始化收藏管理器
        
        Args:
            data_file: 数据文件路径（相对于程序根目录）
        """
        self.data_file = resolve_data_file("favorites.json") if data_file is None else Path(data_file)
        self.favorites: Set[str] = set()
        self.load()
    
    @staticmethod
    def normalize_path(path: str) -> str:
        """
        标准化路径格式（统一分隔符、大小写）
        
        Args:
            path: 原始路径
        
        Returns:
            标准化后的路径（小写）
        """
        return os.path.normpath(path).lower()
    
    def load(self):
        """从 JSON 文件加载收藏数据"""
        if not self.data_file.exists():
            logger.info(f"收藏数据文件不存在，初始化为空: {self.data_file}")
            self.favorites = set()
            return
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 加载时标准化所有路径
                raw_favorites = data.get('favorites', [])
                self.favorites = {self.normalize_path(p) for p in raw_favorites}
                logger.info(f"已加载 {len(self.favorites)} 个收藏电影")
        except Exception as e:
            logger.error(f"加载收藏数据失败: {e}")
            self.favorites = set()
    
    def save(self):
        """保存收藏数据到 JSON 文件"""
        try:
            data = {
                'favorites': list(self.favorites)
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"收藏数据已保存: {len(self.favorites)} 个电影")
        except Exception as e:
            logger.error(f"保存收藏数据失败: {e}")
    
    def is_favorite(self, nfo_path: str) -> bool:
        """
        检查电影是否已收藏
        
        Args:
            nfo_path: NFO 文件路径
        
        Returns:
            是否已收藏
        """
        normalized = self.normalize_path(nfo_path)
        return normalized in self.favorites
    
    def add_favorite(self, nfo_path: str):
        """
        添加收藏
        
        Args:
            nfo_path: NFO 文件路径
        """
        normalized = self.normalize_path(nfo_path)
        if normalized not in self.favorites:
            self.favorites.add(normalized)
            self.save()
            logger.info(f"已添加收藏: {nfo_path}")
    
    def remove_favorite(self, nfo_path: str):
        """
        移除收藏
        
        Args:
            nfo_path: NFO 文件路径
        """
        normalized = self.normalize_path(nfo_path)
        if normalized in self.favorites:
            self.favorites.remove(normalized)
            self.save()
            logger.info(f"已移除收藏: {nfo_path}")
    
    def toggle_favorite(self, nfo_path: str) -> bool:
        """
        切换收藏状态
        
        Args:
            nfo_path: NFO 文件路径
        
        Returns:
            新的收藏状态（True=已收藏, False=未收藏）
        """
        normalized = self.normalize_path(nfo_path)
        if normalized in self.favorites:
            self.favorites.remove(normalized)
            self.save()
            logger.info(f"已取消收藏: {nfo_path}")
            return False
        else:
            self.favorites.add(normalized)
            self.save()
            logger.info(f"已添加收藏: {nfo_path}")
            return True
    
    def get_favorites(self) -> Set[str]:
        """
        获取所有收藏的 NFO 路径
        
        Returns:
            收藏路径集合
        """
        return self.favorites.copy()
    
    def clear(self):
        """清空所有收藏"""
        self.favorites.clear()
        self.save()
        logger.info("已清空所有收藏")
