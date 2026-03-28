"""
观看历史管理器
使用JSON文件持久化存储电影的观看状态
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Set

from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class WatchHistoryManager:
    """观看历史管理器"""
    
    def __init__(self, history_file: str = None):
        """
        初始化管理器
        
        Args:
            history_file: 历史记录文件路径（默认在项目根目录）
        """
        self.history_file = resolve_data_file("watch_history.json") if history_file is None else Path(history_file)
        self.watched_movies: Set[str] = set()  # 存储已观看电影的nfo路径
        self.load()
    
    @staticmethod
    def normalize_path(path: str) -> str:
        """
        规范化路径格式，确保路径比较的一致性
        
        Args:
            path: 原始路径
        
        Returns:
            str: 规范化后的路径（小写，统一分隔符）
        """
        # 使用 os.path.normpath 规范化路径（统一分隔符）
        # 然后转换为小写以忽略大小写差异
        normalized = os.path.normpath(path).lower()
        logger.debug(f"路径规范化: '{path}' -> '{normalized}'")
        return normalized
    
    def load(self):
        """从文件加载观看历史"""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 规范化所有加载的路径
                    raw_paths = data.get('watched', [])
                    self.watched_movies = {self.normalize_path(p) for p in raw_paths}
                logger.info(f"加载观看历史: {len(self.watched_movies)} 部已观看")
            else:
                logger.info("观看历史文件不存在，创建新文件")
                self.watched_movies = set()
        except Exception as e:
            logger.error(f"加载观看历史失败: {e}")
            self.watched_movies = set()
    
    def save(self):
        """保存观看历史到文件"""
        try:
            data = {
                'watched': list(self.watched_movies),
                'total': len(self.watched_movies)
            }
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"保存观看历史: {len(self.watched_movies)} 部")
        except Exception as e:
            logger.error(f"保存观看历史失败: {e}")
    
    def is_watched(self, nfo_path: str) -> bool:
        """
        检查电影是否已观看
        
        Args:
            nfo_path: NFO文件路径（作为唯一标识）
        
        Returns:
            bool: 是否已观看
        """
        normalized = self.normalize_path(nfo_path)
        result = normalized in self.watched_movies
        logger.debug(f"检查观看状态: {Path(nfo_path).name} -> {result}")
        return result
    
    def mark_watched(self, nfo_path: str):
        """
        标记电影为已观看
        
        Args:
            nfo_path: NFO文件路径
        """
        normalized = self.normalize_path(nfo_path)
        if normalized not in self.watched_movies:
            self.watched_movies.add(normalized)
            self.save()
            logger.info(f"标记已观看: {Path(nfo_path).stem}")
    
    def mark_unwatched(self, nfo_path: str):
        """
        标记电影为未观看
        
        Args:
            nfo_path: NFO文件路径
        """
        normalized = self.normalize_path(nfo_path)
        if normalized in self.watched_movies:
            self.watched_movies.discard(normalized)
            self.save()
            logger.info(f"标记未观看: {Path(nfo_path).stem}")
    
    def toggle_watched(self, nfo_path: str) -> bool:
        """
        切换观看状态
        
        Args:
            nfo_path: NFO文件路径
        
        Returns:
            bool: 切换后的状态（True=已观看，False=未观看）
        """
        normalized = self.normalize_path(nfo_path)
        if normalized in self.watched_movies:
            self.mark_unwatched(nfo_path)
            return False
        else:
            self.mark_watched(nfo_path)
            return True
    
    def clear_all(self):
        """清空所有观看记录"""
        self.watched_movies.clear()
        self.save()
        logger.info("已清空所有观看记录")
    
    def get_watched_count(self) -> int:
        """获取已观看电影数量"""
        return len(self.watched_movies)
