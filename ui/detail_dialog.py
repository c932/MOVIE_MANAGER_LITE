"""
电影详情对话框
仿播放派风格的左右分栏布局：左侧海报+按钮，右侧详细信息
"""
import os
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QWidget, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QFont, QCursor

from models.movie import Movie
from utils.poster_cache_manager import PosterCacheManager
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_poster_with_cache(poster_path: str, target_width: int, target_height: int) -> QPixmap:
    """
    从缓存加载海报，支持离线模式
    
    在线模式：优先加载高清原图，只在精确尺寸缓存存在时使用缓存
    离线模式：原图不可访问时才使用跨尺寸缓存复用
    
    Args:
        poster_path: 海报路径
        target_width: 目标宽度
        target_height: 目标高度
    
    Returns:
        QPixmap 对象，失败返回空 QPixmap
    """
    if not poster_path:
        return QPixmap()
    
    cache_manager = PosterCacheManager()
    
    # 1. 先尝试从缓存加载（仅精确尺寸匹配，不允许跨尺寸复用）
    cached_pixmap = cache_manager.get_cached_pixmap(poster_path, target_width, target_height, allow_cross_size_reuse=False)
    if cached_pixmap is not None:
        logger.debug(f"从缓存加载对话框海报（精确尺寸）: {poster_path}")
        return cached_pixmap
    
    # 2. 精确缓存未命中，检查原图是否可访问
    file_accessible = False
    try:
        if Path(poster_path).exists():
            file_accessible = True
    except OSError:
        # 网络路径不可访问（离线模式）
        file_accessible = False
    
    if file_accessible:
        # 3. 加载原图并缓存（在线模式，优先高清）
        pixmap = QPixmap(poster_path)
        if not pixmap.isNull():
            # 缩放
            scaled = pixmap.scaled(
                target_width, target_height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # 保存到缓存
            cache_manager.save_to_cache(poster_path, target_width, target_height, scaled)
            logger.debug(f"从原图加载对话框海报: {poster_path}")
            return scaled
    else:
        # 4. 离线模式，尝试跨尺寸缓存复用
        cached_pixmap = cache_manager.get_cached_pixmap(poster_path, target_width, target_height, allow_cross_size_reuse=True)
        if cached_pixmap is not None:
            logger.debug(f"从缓存加载对话框海报（跨尺寸/离线模式）: {poster_path}")
            return cached_pixmap
        logger.warning(f"离线模式且无任何缓存: {poster_path}")
    
    return QPixmap()


class MovieDetailDialog(QDialog):
    """
    电影详情对话框 - 播放派风格
    左侧：海报 + 操作按钮
    右侧：详细信息（可滚动）
    """
    
    def __init__(self, movie: Movie, parent=None):
        super().__init__(parent)
        self.movie = movie
        self.init_ui()
    
    def init_ui(self):
        """初始化 UI - 左右分栏布局"""
        self.setWindowTitle(self.movie.get_display_title())
        self.setMinimumSize(1100, 700)
        self.setModal(True)
        self.setStyleSheet("background-color: #FFFFFF;")
        
        # 主布局（水平分割）
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ========== 左侧区域 ==========
        left_widget = QWidget()
        left_widget.setFixedWidth(380)
        left_widget.setStyleSheet("background-color: #F8F9FA;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(30, 30, 30, 30)
        left_layout.setSpacing(20)
        
        # 海报
        poster_label = QLabel()
        poster_label.setFixedSize(320, 480)
        poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #E9ECEF;
                border-radius: 8px;
                color: #999999;
                font-size: 14px;
            }
        """)
        
        if self.movie.has_poster():
            # 使用缓存加载海报（支持离线模式）
            pixmap = _load_poster_with_cache(self.movie.poster_path, 320, 480)
            if not pixmap.isNull():
                poster_label.setPixmap(pixmap)
                poster_label.setScaledContents(True)
            else:
                poster_label.setText("加载失败")
        else:
            poster_label.setText("暂无海报")
        
        left_layout.addWidget(poster_label)
        
        # 播放按钮
        play_button = QPushButton("▶ 播放")
        play_button.setFixedHeight(48)
        play_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        play_button.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
            QPushButton:pressed {
                background-color: #BD2130;
            }
        """)
        play_button.clicked.connect(self.play_movie)
        left_layout.addWidget(play_button)
        
        # 其他操作按钮（可选）
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)
        
        favorite_btn = QPushButton("💖 收藏")
        favorite_btn.setFixedHeight(40)
        favorite_btn.setStyleSheet(self._get_secondary_button_style())
        
        share_btn = QPushButton("📤 分享")
        share_btn.setFixedHeight(40)
        share_btn.setStyleSheet(self._get_secondary_button_style())
        
        actions_layout.addWidget(favorite_btn)
        actions_layout.addWidget(share_btn)
        left_layout.addLayout(actions_layout)
        
        left_layout.addStretch()
        main_layout.addWidget(left_widget)
        
        # ========== 右侧区域（滚动） ==========
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #FFFFFF;
            }
            QScrollBar:vertical {
                background: #F8F9FA;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #CED4DA;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #ADB5BD;
            }
        """)
        
        # 右侧内容容器
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(40, 30, 40, 30)
        right_layout.setSpacing(25)
        
        # === 标题 ===
        title_label = QLabel(self.movie.title)
        title_label.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #212529;")
        title_label.setWordWrap(True)
        right_layout.addWidget(title_label)
        
        # === 元信息行 ===
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(20)
        
        if self.movie.year:
            year_label = QLabel(f"📅 {self.movie.year}")
            year_label.setStyleSheet("color: #6C757D; font-size: 14px;")
            meta_layout.addWidget(year_label)
        
        if self.movie.genres:
            genres_text = " / ".join(self.movie.genres[:3])
            genre_label = QLabel(f"🎬 {genres_text}")
            genre_label.setStyleSheet("color: #6C757D; font-size: 14px;")
            meta_layout.addWidget(genre_label)
        
        if self.movie.rating:
            rating_icon = "🌟" if self.movie.rating_source == "douban" else "⭐"
            rating_label = QLabel(f"{rating_icon} {self.movie.rating:.1f}")
            rating_label.setStyleSheet("color: #FFC107; font-size: 16px; font-weight: bold;")
            meta_layout.addWidget(rating_label)
        
        meta_layout.addStretch()
        right_layout.addLayout(meta_layout)
        
        # === 分隔线 ===
        right_layout.addWidget(self._create_separator())
        
        # === 剧情简介 ===
        if self.movie.plot:
            plot_section = self._create_section("📖 剧情简介", self.movie.plot)
            right_layout.addWidget(plot_section)
        
        # === 演职人员 ===
        if self.movie.directors or self.movie.actors:
            cast_section = self._create_cast_section()
            right_layout.addWidget(cast_section)
        
        # === 技术参数 ===
        tech_section = self._create_tech_section()
        if tech_section:
            right_layout.addWidget(tech_section)
        
        # === 文件信息 ===
        if self.movie.video_path:
            file_section = self._create_file_section()
            right_layout.addWidget(file_section)
        
        right_layout.addStretch()
        right_scroll.setWidget(right_widget)
        main_layout.addWidget(right_scroll)
        right_layout.addStretch()
        right_scroll.setWidget(right_widget)
        main_layout.addWidget(right_scroll)
    
    def _create_separator(self):
        """创建分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #DEE2E6;")
        line.setFixedHeight(1)
        return line
    
    def _create_section(self, title: str, content: str):
        """创建通用信息区块"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 内容
        content_label = QLabel(content)
        content_label.setFont(QFont("Microsoft YaHei", 13))
        content_label.setStyleSheet("color: #6C757D; line-height: 1.6;")
        content_label.setWordWrap(True)
        layout.addWidget(content_label)
        
        return section
    
    def _create_cast_section(self):
        """创建演职人员区块"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("🎭 演职人员")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 导演
        if self.movie.directors:
            director_widget = QWidget()
            director_layout = QHBoxLayout(director_widget)
            director_layout.setContentsMargins(0, 0, 0, 0)
            director_layout.setSpacing(10)
            
            director_title = QLabel("导演：")
            director_title.setStyleSheet("color: #495057; font-size: 13px; font-weight: bold;")
            director_layout.addWidget(director_title)
            
            director_names = QLabel(" / ".join(self.movie.directors))
            director_names.setStyleSheet("color: #6C757D; font-size: 13px;")
            director_layout.addWidget(director_names)
            director_layout.addStretch()
            
            layout.addWidget(director_widget)
        
        # 演员（表格式展示，最多显示8个）
        if self.movie.actors:
            actors_grid = QGridLayout()
            actors_grid.setSpacing(15)
            
            for idx, actor in enumerate(self.movie.actors[:8]):
                row = idx // 2
                col = idx % 2
                
                actor_widget = QWidget()
                actor_layout = QHBoxLayout(actor_widget)
                actor_layout.setContentsMargins(0, 0, 0, 0)
                actor_layout.setSpacing(8)
                
                # 演员名字
                name_label = QLabel(actor.name)
                name_label.setStyleSheet("color: #495057; font-size: 13px; font-weight: bold;")
                actor_layout.addWidget(name_label)
                
                # 角色
                if actor.role:
                    role_label = QLabel(f"饰 {actor.role}")
                    role_label.setStyleSheet("color: #ADB5BD; font-size: 12px;")
                    actor_layout.addWidget(role_label)
                
                actor_layout.addStretch()
                actors_grid.addWidget(actor_widget, row, col)
            
            layout.addLayout(actors_grid)
        
        return section
    
    def _create_tech_section(self):
        """创建技术参数区块"""
        # 检查是否有技术参数
        has_tech_info = any([
            self.movie.resolution,
            self.movie.hdr_type,
            self.movie.video_codec,
            self.movie.audio_codec
        ])
        
        if not has_tech_info:
            return None
        
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("📊 技术参数")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 参数表格
        params_layout = QGridLayout()
        params_layout.setSpacing(10)
        row = 0
        
        if self.movie.resolution:
            params_layout.addWidget(self._create_param_label("分辨率:"), row, 0)
            params_layout.addWidget(self._create_param_value(self.movie.resolution), row, 1)
            row += 1
        
        if self.movie.hdr_type:
            params_layout.addWidget(self._create_param_label("HDR:"), row, 0)
            params_layout.addWidget(self._create_param_value(self.movie.hdr_type), row, 1)
            row += 1
        
        if self.movie.video_codec:
            params_layout.addWidget(self._create_param_label("视频编码:"), row, 0)
            params_layout.addWidget(self._create_param_value(self.movie.video_codec), row, 1)
            row += 1
        
        if self.movie.audio_codec:
            params_layout.addWidget(self._create_param_label("音频编码:"), row, 0)
            params_layout.addWidget(self._create_param_value(self.movie.audio_codec), row, 1)
            row += 1
        
        layout.addLayout(params_layout)
        return section
    
    def _create_file_section(self):
        """创建文件信息区块"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("📁 文件信息")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 文件路径
        path_label = QLabel(self.movie.video_path)
        path_label.setStyleSheet("color: #ADB5BD; font-size: 12px; font-family: 'Consolas', monospace;")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        
        return section
    
    def _create_param_label(self, text: str):
        """创建参数名称标签"""
        label = QLabel(text)
        label.setStyleSheet("color: #6C757D; font-size: 13px;")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setFixedWidth(80)
        return label
    
    def _create_param_value(self, text: str):
        """创建参数值标签"""
        label = QLabel(text)
        label.setStyleSheet("color: #495057; font-size: 13px; font-weight: bold;")
        return label
    
    def _get_secondary_button_style(self):
        """次要按钮样式"""
        return """
            QPushButton {
                background-color: #FFFFFF;
                color: #6C757D;
                border: 1px solid #CED4DA;
                border-radius: 8px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #F8F9FA;
                border-color: #ADB5BD;
            }
        """
    
    def play_movie(self):
        """播放电影（使用系统默认播放器）"""
        if not self.movie.video_path or not os.path.exists(self.movie.video_path):
            logger.warning(f"视频文件不存在: {self.movie.video_path}")
            return
        
        try:
            os.startfile(self.movie.video_path)
            logger.info(f"正在播放: {self.movie.video_path}")
        except Exception as e:
            logger.error(f"播放失败: {e}")
