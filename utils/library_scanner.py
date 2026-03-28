"""
媒体库扫描器
使用多线程扫描电影目录，解析 NFO 文件，避免阻塞 UI 主线程
"""
import re
import logging
from pathlib import Path
from typing import List
from PyQt6.QtCore import QThread, pyqtSignal

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class LibraryScanner(QThread):
    """
    媒体库扫描线程
    在后台线程中递归扫描电影目录，解析 NFO 文件
    """
    
    # 信号定义
    progress_updated = pyqtSignal(int, int)  # (当前进度, 总数)
    movie_found = pyqtSignal(Movie)  # 发现一部电影
    scan_completed = pyqtSignal(int)  # 扫描完成（电影总数）
    scan_error = pyqtSignal(str)  # 扫描错误
    
    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.is_cancelled = False
    
    def run(self):
        """线程执行入口"""
        try:
            logger.info("开始扫描媒体库...")
            movie_paths = self.config.get_movie_paths()
            
            if not movie_paths:
                self.scan_error.emit("未配置电影目录，请在 config.json 中设置 movie_paths")
                return
            
            # 收集所有 NFO 文件
            nfo_files = []
            for movie_path in movie_paths:
                path = Path(movie_path)
                if not path.exists():
                    logger.warning(f"电影目录不存在: {movie_path}")
                    continue
                
                found_nfos = self._scan_directory(path)
                nfo_files.extend(found_nfos)
            
            total = len(nfo_files)
            logger.info(f"发现 {total} 个 NFO 文件，开始解析...")
            
            # 解析每个 NFO 文件
            success_count = 0
            for idx, nfo_path in enumerate(nfo_files):
                if self.is_cancelled:
                    logger.info("扫描已取消")
                    break
                
                # 解析 NFO
                movie = NFOParser.parse(str(nfo_path))
                if movie and movie.video_path:  # 只有找到视频文件的才算有效
                    self.movie_found.emit(movie)
                    success_count += 1
                
                # 更新进度
                self.progress_updated.emit(idx + 1, total)
            
            logger.info(f"扫描完成，成功解析 {success_count} 部电影")
            self.scan_completed.emit(success_count)
            
        except Exception as e:
            logger.error(f"扫描过程中出现异常: {e}")
            self.scan_error.emit(f"扫描错误: {str(e)}")
    
    def _scan_directory(self, directory: Path) -> List[Path]:
        """
        递归扫描目录，查找 NFO 文件
        应用黑名单过滤
        
        Args:
            directory: 要扫描的目录
        
        Returns:
            NFO 文件路径列表
        """
        nfo_files = []
        blacklist_folders = self.config.get_blacklist_folders()
        blacklist_patterns = self.config.get_blacklist_patterns()
        
        # 编译正则表达式
        compiled_patterns = [re.compile(pattern) for pattern in blacklist_patterns]
        
        try:
            for item in directory.rglob('*.nfo'):
                # 跳过检查（避免扫描被取消后继续）
                if self.is_cancelled:
                    break
                
                # 黑名单文件夹过滤
                if any(blacklist in str(item) for blacklist in blacklist_folders):
                    logger.debug(f"跳过黑名单文件夹中的文件: {item}")
                    continue
                
                # 黑名单文件名模式过滤
                filename = item.name
                if any(pattern.match(filename) for pattern in compiled_patterns):
                    logger.debug(f"跳过黑名单文件: {filename}")
                    continue
                
                nfo_files.append(item)
                
        except PermissionError as e:
            logger.warning(f"无权限访问目录: {directory}")
        except Exception as e:
            logger.error(f"扫描目录时出错 [{directory}]: {e}")
        
        return nfo_files
    
    def cancel(self):
        """取消扫描"""
        self.is_cancelled = True
        logger.info("正在取消扫描...")
