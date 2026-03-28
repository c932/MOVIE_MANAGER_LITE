"""
电影数据模型
定义电影对象的所有属性字段
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Actor:
    """演员信息数据类"""
    name: str
    role: str = ""
    thumb: str = ""  # 演员头像路径


@dataclass
class Movie:
    """
    电影完整数据模型
    存储从 NFO 文件解析出的所有电影信息
    """
    # 基础信息
    title: str = ""
    original_title: str = ""  # 原始标题
    year: str = ""
    premiered: str = ""  # 上映日期
    plot: str = ""  # 剧情简介
    tagline: str = ""
    runtime: str = ""  # 片长(分钟)
    file_size: str = ""  # 文件大小
    set_name: str = ""  # 系列电影名称（如：变形金刚系列）
    
    # 分类与评分
    genres: List[str] = field(default_factory=list)  # 类型标签列表
    countries: List[str] = field(default_factory=list)  # 国家列表
    tags: List[str] = field(default_factory=list)  # 自定义标签列表
    rating: float = 0.0  # 主评分（豆瓣优先，否则 IMDb）
    rating_source: str = ""  # 主评分来源（douban/imdb）
    ratings: dict = field(default_factory=dict)  # 所有评分来源 {'douban': 7.4, 'imdb': 6.2, 'tmdb': 6.9}
    
    # 观看状态
    watched: bool = False  # 是否已观看
    
    # 演职员
    directors: List[str] = field(default_factory=list)
    actors: List[Actor] = field(default_factory=list)
    
    # 技术参数（从 fileinfo 提取）
    resolution: str = ""  # 如 4K, 1080p
    hdr_type: str = ""  # 如 dolbyvision, HDR10
    video_codec: str = ""  # 如 HEVC
    audio_codec: str = ""  # 如 TrueHD, DTS-HD
    
    # 外部链接和ID
    imdb_id: str = ""  # IMDb ID
    tmdb_id: str = ""  # TMDB ID
    douban_url: str = ""  # 豆瓣链接
    
    # 本地文件路径
    video_path: str = ""  # 视频文件绝对路径
    nfo_path: str = ""  # NFO 文件路径
    poster_path: str = ""  # 海报图片路径 (poster.jpg)
    fanart_path: str = ""  # 背景图路径 (fanart.jpg)

    # 加入时间（文件 mtime，需联网时在后台更新）
    added_time: float = 0.0
    
    def __post_init__(self):
        """初始化后处理，确保数据类型正确"""
        if isinstance(self.rating, str):
            try:
                self.rating = float(self.rating)
            except ValueError:
                self.rating = 0.0
    
    def get_display_title(self) -> str:
        """获取显示标题（含年份）"""
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title
    
    def get_tech_badges(self) -> List[str]:
        """获取技术参数徽章列表（用于 UI 展示）"""
        badges = []
        if self.resolution:
            badges.append(self.resolution.upper())
        if self.hdr_type:
            # 处理常见的 HDR 类型
            hdr_display = self.hdr_type.replace("dolbyvision", "Dolby Vision").replace("hdr10", "HDR10")
            badges.append(hdr_display)
        if self.audio_codec:
            # 提取音频编码简称
            audio = self.audio_codec.upper()
            if 'TRUEHD' in audio or 'ATMOS' in audio:
                badges.append('Atmos')
            elif 'DTS' in audio:
                badges.append('DTS-HD')
        return badges
    
    def get_genres_string(self) -> str:
        """获取类型字符串（用逗号分隔）"""
        return " / ".join(self.genres) if self.genres else "未分类"
    
    def has_poster(self) -> bool:
        """是否有海报图片"""
        return bool(self.poster_path)
    
    def has_fanart(self) -> bool:
        """是否有背景图"""
        return bool(self.fanart_path)
