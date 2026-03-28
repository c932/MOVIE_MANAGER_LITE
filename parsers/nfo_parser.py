"""
NFO 文件解析器
使用 xml.etree.ElementTree 解析 Kodi 标准的 NFO 文件
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import logging

from models.movie import Movie, Actor

logger = logging.getLogger(__name__)


class NFOParser:
    """NFO XML 文件解析引擎"""
    
    @staticmethod
    def parse(nfo_path: str) -> Optional[Movie]:
        """
        解析 NFO 文件，返回 Movie 对象
        
        Args:
            nfo_path: NFO 文件的绝对路径
        
        Returns:
            Movie 对象，解析失败返回 None
        """
        try:
            nfo_file = Path(nfo_path)
            if not nfo_file.exists():
                logger.warning(f"NFO 文件不存在: {nfo_path}")
                return None
            
            # 解析 XML
            tree = ET.parse(nfo_path)
            root = tree.getroot()
            
            # 创建 Movie 对象
            movie = Movie()
            movie.nfo_path = nfo_path
            
            # === 提取基础信息 ===
            movie.title = NFOParser._get_text(root, 'title')
            movie.original_title = NFOParser._get_text(root, 'originaltitle')
            movie.year = NFOParser._get_text(root, 'year')
            movie.premiered = NFOParser._get_text(root, 'premiered')
            movie.plot = NFOParser._get_text(root, 'plot')
            movie.tagline = NFOParser._get_text(root, 'tagline')
            movie.runtime = NFOParser._get_text(root, 'runtime')
            
            # 提取系列电影信息（兼容多种格式）
            set_elem = root.find('set')
            if set_elem is not None:
                # 格式1: <set><name>系列名</name></set>
                name_elem = set_elem.find('name')
                if name_elem is not None and name_elem.text:
                    movie.set_name = name_elem.text.strip()
                # 格式2: <set>系列名</set>
                elif set_elem.text and set_elem.text.strip():
                    movie.set_name = set_elem.text.strip()
            
            # 提取文件大小（如果存在）
            fileinfo = root.find('fileinfo')
            if fileinfo is not None:
                streamdetails = fileinfo.find('streamdetails')
                if streamdetails is not None:
                    # 尝试从 video 节点获取文件大小
                    video = streamdetails.find('video')
                    if video is not None:
                        size_elem = video.find('filesize')
                        if size_elem is not None and size_elem.text:
                            movie.file_size = size_elem.text.strip()
            
            # === 提取多值字段 ===
            # 类型（genre）
            for genre in root.findall('genre'):
                if genre.text:
                    movie.genres.append(genre.text.strip())
            
            # 国家（country）
            for country in root.findall('country'):
                if country.text:
                    movie.countries.append(country.text.strip())
            
            # 用户自定义标签（custom元素）
            # 注意：NFO中的<tag>通常是媒体服务器从 TMDB 获取的电影关键词，
            # 不是用户自定义标签，所以不解析它们，以免筛选栏出现大量无意义标签
            # 用户自定义标签使用<custom>元素存储
            for custom in root.findall('custom'):
                if custom.text:
                    movie.tags.append(custom.text.strip())
            
            # === 提取评分（豆瓣优先，否则 IMDb）===
            rating_info = NFOParser._extract_rating(root)
            if rating_info:
                movie.rating = rating_info['value']
                movie.rating_source = rating_info['source']
                movie.ratings = rating_info.get('all_ratings', {})
            
            # === 提取外部ID和链接 ===
            # IMDb ID
            imdb_elem = root.find("uniqueid[@type='imdb']")
            if imdb_elem is not None and imdb_elem.text:
                movie.imdb_id = imdb_elem.text.strip()
            else:
                # 尝试从旧格式的 id 标签获取
                id_elem = root.find('id')
                if id_elem is not None and id_elem.text and id_elem.text.startswith('tt'):
                    movie.imdb_id = id_elem.text.strip()
            
            # TMDB ID
            tmdb_elem = root.find("uniqueid[@type='tmdb']")
            if tmdb_elem is not None and tmdb_elem.text:
                movie.tmdb_id = tmdb_elem.text.strip()
            
            # 豆瓣URL（支持多种NFO格式）
            douban_url = ''
            # 1. 尝试 <doubanurl> 标签
            douban_url_elem = root.find('doubanurl')
            if douban_url_elem is not None and douban_url_elem.text:
                douban_url = douban_url_elem.text.strip()
            # 2. 尝试 <url> 标签（含豆瓣链接）
            if not douban_url:
                url_elem = root.find('url')
                if url_elem is not None and url_elem.text and 'douban.com' in url_elem.text:
                    douban_url = url_elem.text.strip()
            # 3. 尝试从 <uniqueid type="douban"> 构造URL
            if not douban_url:
                douban_id_elem = root.find("uniqueid[@type='douban']")
                if douban_id_elem is not None and douban_id_elem.text:
                    douban_url = f"https://movie.douban.com/subject/{douban_id_elem.text.strip()}/"
            if douban_url:
                movie.douban_url = douban_url
            
            # === 提取导演 ===
            for director in root.findall('director'):
                if director.text:
                    movie.directors.append(director.text.strip())
            
            # === 提取演员列表 ===
            for actor_elem in root.findall('actor'):
                actor = Actor(
                    name=NFOParser._get_text(actor_elem, 'name'),
                    role=NFOParser._get_text(actor_elem, 'role'),
                    thumb=NFOParser._get_text(actor_elem, 'thumb')
                )
                if actor.name:  # 只添加有名字的演员
                    movie.actors.append(actor)
            
            # === 提取技术参数（fileinfo 节点）===
            fileinfo = root.find('fileinfo')
            if fileinfo is not None:
                streamdetails = fileinfo.find('streamdetails')
                if streamdetails is not None:
                    # 视频流信息
                    video = streamdetails.find('video')
                    if video is not None:
                        # 分辨率
                        width = NFOParser._get_text(video, 'width')
                        height = NFOParser._get_text(video, 'height')
                        if width and height:
                            try:
                                movie.resolution = NFOParser._determine_resolution(int(width), int(height))
                            except (ValueError, TypeError):
                                logger.warning(f"无法解析分辨率: width={width}, height={height}")
                        
                        # HDR 类型
                        movie.hdr_type = NFOParser._get_text(video, 'hdrtype')
                        
                        # 视频编码
                        movie.video_codec = NFOParser._get_text(video, 'codec')
                    
                    # 音频流信息（取第一条）
                    audio = streamdetails.find('audio')
                    if audio is not None:
                        movie.audio_codec = NFOParser._get_text(audio, 'codec')
            
            # === 推断视频文件路径（与 NFO 同名同目录）===
            nfo_dir = nfo_file.parent
            nfo_stem = nfo_file.stem
            
            # 常见视频扩展名
            video_extensions = ['.mkv', '.mp4', '.avi', '.mov', '.m2ts', '.ts']
            for ext in video_extensions:
                potential_video = nfo_dir / f"{nfo_stem}{ext}"
                if potential_video.exists():
                    movie.video_path = str(potential_video)
                    break
            
            # === 绑定本地资产（海报和背景图）===
            # 支持两种命名方式：
            # 1. poster.jpg / fanart.jpg（标准命名）
            # 2. {nfo_stem}-poster.jpg / {nfo_stem}-fanart.jpg（带前缀命名）
            
            # 查找海报
            poster_standard = nfo_dir / 'poster.jpg'
            poster_prefixed = nfo_dir / f'{nfo_stem}-poster.jpg'
            
            if poster_standard.exists():
                movie.poster_path = str(poster_standard)
            elif poster_prefixed.exists():
                movie.poster_path = str(poster_prefixed)
            
            # 查找背景图
            fanart_standard = nfo_dir / 'fanart.jpg'
            fanart_prefixed = nfo_dir / f'{nfo_stem}-fanart.jpg'
            
            if fanart_standard.exists():
                movie.fanart_path = str(fanart_standard)
            elif fanart_prefixed.exists():
                movie.fanart_path = str(fanart_prefixed)
            
            logger.info(f"成功解析电影: {movie.get_display_title()}")
            return movie
            
        except ET.ParseError as e:
            logger.error(f"NFO XML 解析错误 [{nfo_path}]: {e}")
            return None
        except Exception as e:
            logger.error(f"NFO 解析异常 [{nfo_path}]: {e}")
            return None
    
    @staticmethod
    def _get_text(element: ET.Element, tag: str) -> str:
        """安全获取子元素的文本内容"""
        child = element.find(tag)
        return child.text.strip() if child is not None and child.text else ""
    
    @staticmethod
    def _extract_rating(root: ET.Element) -> Optional[dict]:
        """
        提取评分信息，豆瓣优先
        同时提取所有评分源到 ratings 字典
        
        Returns:
            {'source': 'douban'/'imdb', 'value': float, 'all_ratings': {...}} 或 None
        """
        ratings_elem = root.find('ratings')
        if ratings_elem is None:
            return None
        
        all_ratings = {}  # 存储所有评分源
        primary_rating = None
        
        # 提取所有评分
        for rating in ratings_elem.findall('rating'):
            rating_name = rating.get('name', '').lower()
            value_elem = rating.find('value')
            if value_elem is not None and value_elem.text:
                try:
                    rating_value = float(value_elem.text)
                    all_ratings[rating_name] = rating_value
                except ValueError:
                    pass
        
        # 优先返回豆瓣评分
        if 'douban' in all_ratings:
            primary_rating = {'source': 'douban', 'value': all_ratings['douban']}
        elif 'imdb' in all_ratings:
            primary_rating = {'source': 'imdb', 'value': all_ratings['imdb']}
        elif 'themoviedb' in all_ratings or 'tmdb' in all_ratings:
            tmdb_value = all_ratings.get('themoviedb') or all_ratings.get('tmdb')
            primary_rating = {'source': 'tmdb', 'value': tmdb_value}
        
        if primary_rating:
            primary_rating['all_ratings'] = all_ratings
        
        return primary_rating
    
    @staticmethod
    def _determine_resolution(width: int, height: int) -> str:
        """根据宽高判断分辨率等级"""
        if width >= 3840 or height >= 2160:
            return "4K"
        elif width >= 1920 or height >= 1080:
            return "1080p"
        elif width >= 1280 or height >= 720:
            return "720p"
        else:
            return "SD"
    
    @staticmethod
    def update_user_rating(nfo_path: str, rating: float) -> bool:
        """
        更新NFO文件中的用户评分
        
        Args:
            nfo_path: NFO文件路径
            rating: 用户评分 (0-10)
        
        Returns:
            是否更新成功
        """
        try:
            # 解析NFO文件
            tree = ET.parse(nfo_path)
            root = tree.getroot()
            
            # 查找或创建ratings元素
            ratings_elem = root.find('ratings')
            if ratings_elem is None:
                ratings_elem = ET.SubElement(root, 'ratings')
            
            # 查找或创建user rating元素
            user_rating = None
            for rating_elem in ratings_elem.findall('rating'):
                if rating_elem.get('name') == 'user':
                    user_rating = rating_elem
                    break
            
            if user_rating is None:
                user_rating = ET.SubElement(ratings_elem, 'rating')
                user_rating.set('name', 'user')
                user_rating.set('max', '10')
            
            # 更新value
            value_elem = user_rating.find('value')
            if value_elem is None:
                value_elem = ET.SubElement(user_rating, 'value')
            value_elem.text = str(rating)
            
            # 格式化并保存XML
            NFOParser._save_formatted_xml(tree, nfo_path)
            
            logger.info(f"已更新用户评分: {nfo_path} -> {rating}")
            return True
            
        except Exception as e:
            logger.error(f"更新用户评分失败: {e}")
            return False
    
    @staticmethod
    def _save_formatted_xml(tree: ET.ElementTree, file_path: str):
        """保存格式化的XML文件"""
        # 使用 ET.indent 格式化（Python 3.9+，不会破坏文本节点内容）
        ET.indent(tree, space="  ")
        tree.write(file_path, encoding='utf-8', xml_declaration=True)
