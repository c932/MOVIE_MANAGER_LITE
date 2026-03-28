"""
电影库缓存管理器
用于缓存扫描结果，避免每次启动都重新扫描NFO文件
"""
import json
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from models.movie import Movie, Actor
from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class CacheManager:
    """电影库缓存管理器"""
    
    def __init__(self, cache_file: str = None):
        self.cache_file = resolve_data_file("movie_cache.json") if cache_file is None else Path(cache_file)
    
    def save_cache(self, movies: List[Movie], movie_paths: List[str]) -> bool:
        """
        保存电影数据到缓存文件
        
        Args:
            movies: 电影列表
            movie_paths: 扫描的路径列表
        
        Returns:
            是否保存成功
        """
        try:
            cache_data = {
                'version': '1.0',
                'timestamp': datetime.now().isoformat(),
                'movie_paths': movie_paths,
                'movie_count': len(movies),
                'movies': [self._serialize_movie(movie) for movie in movies]
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"成功保存缓存: {len(movies)} 部电影 -> {self.cache_file}")
            return True
            
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
            return False
    
    def load_cache(self, current_movie_paths: List[str]) -> Optional[List[Movie]]:
        """
        从缓存文件加载电影数据
        
        Args:
            current_movie_paths: 当前配置的电影路径列表
        
        Returns:
            电影列表，如果缓存无效则返回 None
        """
        try:
            if not self.cache_file.exists():
                logger.info("缓存文件不存在，需要扫描")
                return None
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 验证缓存版本
            if cache_data.get('version') != '1.0':
                logger.warning("缓存版本不匹配，需要重新扫描")
                return None
            
            # 验证电影路径是否变化
            cached_paths = cache_data.get('movie_paths', [])
            if set(cached_paths) != set(current_movie_paths):
                logger.info("电影路径已变化，需要重新扫描")
                logger.info(f"  缓存路径: {cached_paths}")
                logger.info(f"  当前路径: {current_movie_paths}")
                return None
            
            # 反序列化电影数据
            movies = [self._deserialize_movie(movie_data) 
                     for movie_data in cache_data.get('movies', [])]
            
            timestamp = cache_data.get('timestamp', '')
            logger.info(f"成功加载缓存: {len(movies)} 部电影 (缓存时间: {timestamp})")
            return movies
            
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            return None
    
    def clear_cache(self) -> bool:
        """
        清除缓存文件
        
        Returns:
            是否清除成功
        """
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                logger.info("缓存已清除")
                return True
            return False
        except Exception as e:
            logger.error(f"清除缓存失败: {e}")
            return False
    
    def get_cache_info(self) -> Optional[dict]:
        """
        获取缓存信息（不加载完整数据）
        
        Returns:
            缓存信息字典，如果缓存不存在则返回 None
        """
        try:
            if not self.cache_file.exists():
                return None
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            return {
                'timestamp': cache_data.get('timestamp', ''),
                'movie_count': cache_data.get('movie_count', 0),
                'movie_paths': cache_data.get('movie_paths', [])
            }
        except:
            return None
    
    def _serialize_movie(self, movie: Movie) -> dict:
        """将Movie对象序列化为字典"""
        return {
            # 基础信息
            'title': movie.title,
            'original_title': movie.original_title,
            'year': movie.year,
            'premiered': movie.premiered,
            'plot': movie.plot,
            'tagline': movie.tagline,
            'runtime': movie.runtime,
            'file_size': movie.file_size,
            'set_name': movie.set_name,
            
            # 分类与评分
            'genres': movie.genres,
            'countries': movie.countries,
            'tags': movie.tags if hasattr(movie, 'tags') else [],
            'rating': movie.rating,
            'rating_source': movie.rating_source,
            'ratings': movie.ratings,
            
            # 观看状态
            'watched': movie.watched,
            
            # 演职员
            'directors': movie.directors,
            'actors': [{'name': actor.name, 'role': actor.role, 'thumb': actor.thumb} 
                      for actor in movie.actors],
            
            # 技术参数
            'resolution': movie.resolution,
            'hdr_type': movie.hdr_type,
            'video_codec': movie.video_codec,
            'audio_codec': movie.audio_codec,
            
            # 外部链接和ID
            'imdb_id': movie.imdb_id,
            'tmdb_id': movie.tmdb_id,
            'douban_url': movie.douban_url,
            
            # 本地文件路径
            'video_path': movie.video_path,
            'nfo_path': movie.nfo_path,
            'poster_path': movie.poster_path,

            # 加入时间
            'added_time': getattr(movie, 'added_time', 0.0),
        }
    
    def _deserialize_movie(self, data: dict) -> Movie:
        """从字典反序列化为Movie对象"""
        # 创建Actor对象
        actors = [Actor(name=a['name'], role=a['role'], thumb=a['thumb']) 
                 for a in data.get('actors', [])]
        
        # 创建Movie对象
        movie = Movie(
            # 基础信息
            title=data.get('title', ''),
            original_title=data.get('original_title', ''),
            year=data.get('year', ''),
            premiered=data.get('premiered', ''),
            plot=data.get('plot', ''),
            tagline=data.get('tagline', ''),
            runtime=data.get('runtime', ''),
            file_size=data.get('file_size', ''),
            set_name=data.get('set_name', ''),
            
            # 分类与评分
            genres=data.get('genres', []),
            countries=data.get('countries', []),
            tags=data.get('tags', []),
            rating=data.get('rating', 0.0),
            rating_source=data.get('rating_source', ''),
            ratings=data.get('ratings', {}),
            
            # 观看状态
            watched=data.get('watched', False),
            
            # 演职员
            directors=data.get('directors', []),
            actors=actors,
            
            # 技术参数
            resolution=data.get('resolution', ''),
            hdr_type=data.get('hdr_type', ''),
            video_codec=data.get('video_codec', ''),
            audio_codec=data.get('audio_codec', ''),
            
            # 外部链接和ID
            imdb_id=data.get('imdb_id', ''),
            tmdb_id=data.get('tmdb_id', ''),
            douban_url=data.get('douban_url', ''),
            
            # 本地文件路径
            video_path=data.get('video_path', ''),
            nfo_path=data.get('nfo_path', ''),
            poster_path=data.get('poster_path', ''),

            # 加入时间
            added_time=data.get('added_time', 0.0),
        )

        return movie
