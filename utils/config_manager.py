"""
配置文件管理器
负责读取和管理 config.json 配置
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器，单例模式"""
    
    _instance = None
    _config: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._config:  # 避免重复加载
            self.load_config()
    
    def load_config(self, config_path: str = None):
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径，默认为当前目录的 config.json
        """
        try:
            config_file = resolve_data_file("config.json") if config_path is None else Path(config_path)
            if not config_file.exists():
                logger.warning(f"配置文件不存在: {config_file}，使用默认配置")
                self._set_default_config()
                return
            
            with open(config_file, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            
            logger.info(f"配置文件加载成功: {config_file}")
            
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式错误: {e}")
            self._set_default_config()
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self._set_default_config()
    
    def _set_default_config(self):
        """设置默认配置"""
        self._config = {
            "movie_paths": [],
            "blacklist_folders": ["Extras-Grym", "Extras-Grym@BTNET"],
            "blacklist_patterns": [r".*[Ss]ample.*", r".*【.*请访问.*"],
            "poster_width": 200,
            "poster_height": 300,
            "grid_columns": 5
        }
    
    def get_movie_paths(self) -> List[str]:
        """获取电影目录列表"""
        return self._config.get("movie_paths", [])
    
    def get_blacklist_folders(self) -> List[str]:
        """获取黑名单文件夹列表"""
        return self._config.get("blacklist_folders", [])
    
    def get_blacklist_patterns(self) -> List[str]:
        """获取黑名单文件名正则模式"""
        return self._config.get("blacklist_patterns", [])
    
    def get_poster_size(self) -> tuple:
        """获取海报尺寸 (宽, 高)"""
        width = self._config.get("poster_width", 200)
        height = self._config.get("poster_height", 300)
        return (width, height)
    
    def get_grid_columns(self) -> int:
        """获取网格列数"""
        return self._config.get("grid_columns", 5)
    
    def get_poster_scale(self) -> int:
        """获取海报缩放比例（50-200，默认100）"""
        return self._config.get("poster_scale", 100)
    
    def set_poster_scale(self, scale: int):
        """设置海报缩放比例"""
        self._config["poster_scale"] = scale
    
    def save_config(self, config_path: str = None):
        """
        保存配置到文件
        
        Args:
            config_path: 配置文件保存路径
        """
        try:
            config_file = resolve_data_file("config.json") if config_path is None else Path(config_path)
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {config_file}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def set_movie_paths(self, paths: List[str]):
        """设置电影目录"""
        self._config["movie_paths"] = paths
    
    def add_movie_path(self, path: str):
        """添加电影目录"""
        if path not in self._config["movie_paths"]:
            self._config["movie_paths"].append(path)
    
    def get_last_opened_movie(self) -> str:
        """获取上次打开的电影 nfo 路径"""
        return self._config.get("last_opened_movie_nfo", "")
    
    def set_last_opened_movie(self, nfo_path: str):
        """保存当前打开的电影 nfo 路径"""
        self._config["last_opened_movie_nfo"] = nfo_path
    
    def get_splitter_sizes(self) -> dict:
        """获取分割器尺寸"""
        return self._config.get("splitter_sizes", {
            "main": [],
            "right": []
        })
    
    def set_splitter_sizes(self, main_sizes: list, right_sizes: list):
        """保存分割器尺寸"""
        self._config["splitter_sizes"] = {
            "main": main_sizes,
            "right": right_sizes
        }
