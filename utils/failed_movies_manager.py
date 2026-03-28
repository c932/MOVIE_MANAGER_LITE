"""
失败电影记录管理器
用于记录豆瓣匹配失败的电影，避免重复尝试
"""
import json
import logging
from pathlib import Path
from typing import Set, Dict
from datetime import datetime

from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class FailedMoviesManager:
    """管理豆瓣匹配失败的电影记录"""
    
    def __init__(self, file_path: str = None):
        self.file_path = resolve_data_file("failed_movies.json") if file_path is None else Path(file_path)
        self.failed_movies: Dict[str, dict] = {}  # key: nfo_file, value: {title, year, failed_at, retry_count}
        self.load()
    
    def load(self):
        """加载失败记录"""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.failed_movies = json.load(f)
                logger.info(f"已加载 {len(self.failed_movies)} 个失败电影记录")
            except Exception as e:
                logger.error(f"加载失败记录出错: {e}")
                self.failed_movies = {}
        else:
            logger.info("未找到失败记录文件，创建新记录")
            self.failed_movies = {}
    
    def save(self):
        """保存失败记录"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.failed_movies, f, indent=2, ensure_ascii=False)
            logger.info(f"已保存 {len(self.failed_movies)} 个失败电影记录")
        except Exception as e:
            logger.error(f"保存失败记录出错: {e}")
    
    def add_failed(self, nfo_file: str, title: str, year: str = ""):
        """添加失败记录"""
        # 使用规范化的路径作为 key
        nfo_path = str(Path(nfo_file).resolve())
        
        if nfo_path in self.failed_movies:
            # 增加重试计数
            self.failed_movies[nfo_path]['retry_count'] = self.failed_movies[nfo_path].get('retry_count', 0) + 1
            self.failed_movies[nfo_path]['last_failed_at'] = datetime.now().isoformat()
        else:
            # 新增记录
            self.failed_movies[nfo_path] = {
                'title': title,
                'year': year,
                'failed_at': datetime.now().isoformat(),
                'last_failed_at': datetime.now().isoformat(),
                'retry_count': 1
            }
        
        self.save()
        logger.info(f"添加失败记录: {title} ({year})")
    
    def is_failed(self, nfo_file: str) -> bool:
        """检查电影是否在失败列表中"""
        nfo_path = str(Path(nfo_file).resolve())
        return nfo_path in self.failed_movies
    
    def remove_failed(self, nfo_file: str):
        """从失败记录中移除（例如手动匹配成功后）"""
        nfo_path = str(Path(nfo_file).resolve())
        if nfo_path in self.failed_movies:
            title = self.failed_movies[nfo_path]['title']
            del self.failed_movies[nfo_path]
            self.save()
            logger.info(f"移除失败记录: {title}")
    
    def get_failed_count(self) -> int:
        """获取失败记录总数"""
        return len(self.failed_movies)
    
    def get_failed_info(self, nfo_file: str) -> dict:
        """获取失败记录详情"""
        nfo_path = str(Path(nfo_file).resolve())
        return self.failed_movies.get(nfo_path, {})
    
    def clear_all(self):
        """清空所有失败记录"""
        count = len(self.failed_movies)
        self.failed_movies = {}
        self.save()
        logger.info(f"已清空 {count} 个失败记录")
    
    def get_all_failed(self) -> Dict[str, dict]:
        """获取所有失败记录"""
        return self.failed_movies.copy()
