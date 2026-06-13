"""
电影详情面板组件 - 嵌入式版本
显示在主窗口右侧的固定详情区域
"""
import os
import logging
import time
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QFrame, QGridLayout, QDialog, QSpinBox, QDialogButtonBox, QMessageBox, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QFont, QCursor

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from utils.poster_cache_manager import PosterCacheManager
from utils.image_loader import ImageLoader
from utils.network_mode import is_offline_cache_only
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PLOT_CHARS = 1600

_poster_cache_manager = None
_logged_missing_cache_paths = set()


def _get_poster_cache_manager() -> PosterCacheManager:
    """详情页复用同一个缓存管理器，避免重复加载索引文件。"""
    global _poster_cache_manager
    if _poster_cache_manager is None:
        _poster_cache_manager = PosterCacheManager()
    return _poster_cache_manager


def _is_network_path(path: str) -> bool:
    """判断是否为 UNC 网络路径。"""
    if not path:
        return False
    return path.startswith("\\\\") or path.startswith("//")


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
    
    cache_manager = _get_poster_cache_manager()
    
    # 1. 先尝试从缓存加载（仅精确尺寸匹配，不允许跨尺寸复用）
    cached_pixmap = cache_manager.get_cached_pixmap(poster_path, target_width, target_height, allow_cross_size_reuse=False)
    if cached_pixmap is not None:
        logger.debug(f"从缓存加载详情页海报（精确尺寸）: {poster_path}")
        return cached_pixmap

    # 网络路径离线时 exists/stat 可能长时间阻塞，优先走跨尺寸缓存兜底。
    if _is_network_path(poster_path):
        cached_pixmap = cache_manager.get_cached_pixmap(
            poster_path, target_width, target_height, allow_cross_size_reuse=True
        )
        if cached_pixmap is not None:
            logger.debug(f"从缓存加载详情页海报（网络路径跨尺寸复用）: {poster_path}")
            return cached_pixmap
        if poster_path not in _logged_missing_cache_paths:
            _logged_missing_cache_paths.add(poster_path)
            if is_offline_cache_only():
                logger.warning(f"仅缓存模式：网络路径无缓存可用: {poster_path}")
            else:
                logger.warning(f"网络路径且无缓存可用: {poster_path}")
        return QPixmap()
    
    # 2. 非阻塞策略：不在 UI 线程探测原图或解码大图，只做跨尺寸缓存复用。
    cached_pixmap = cache_manager.get_cached_pixmap(
        poster_path, target_width, target_height, allow_cross_size_reuse=True
    )
    if cached_pixmap is not None:
        logger.debug(f"从缓存加载详情页海报（跨尺寸复用）: {poster_path}")
        return cached_pixmap
    
    return QPixmap()


class MovieDetailPanel(QWidget):
    """
    电影详情嵌入式面板
    左侧：大海报
    右侧：详细信息（可滚动）
    """
    
    # 观看状态改变信号 (nfo_path, is_watched)
    watch_status_changed = pyqtSignal(str, bool)
    # 收藏状态改变信号 (nfo_path, is_favorite)
    favorite_status_changed = pyqtSignal(str, bool)
    # 用户评分改变信号 (nfo_path, rating)
    user_rating_changed = pyqtSignal(str, float)
    # 系列电影点击信号 (movie)
    series_movie_clicked = pyqtSignal(object)
    # 电影信息更新信号 (movie) - NFO编辑后触发
    movie_updated = pyqtSignal(object)
    # 删除请求信号 (movie) - 由主窗口执行“仅本地数据库删除”
    delete_requested = pyqtSignal(object)
    # 更新海报请求信号 (movie) - 由主窗口执行缓存失效与重拉
    refresh_poster_requested = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_movie = None
        self.watch_history = None
        self.favorite_manager = None
        self.all_movies = []  # 所有电影列表（用于查找系列电影）
        self._detail_poster_loader = None
        self._detail_render_generation = 0
        self.init_ui()

    def _load_detail_poster_async(self, movie: Movie, poster_label: QLabel):
        """异步加载详情海报，避免点击时阻塞主线程。"""
        if not movie or not movie.has_poster():
            return

        # 终止旧加载任务，避免快速切换时回写错图
        if self._detail_poster_loader is not None and self._detail_poster_loader.isRunning():
            self._detail_poster_loader.requestInterruption()

        loader = ImageLoader(movie.poster_path, 280, 420)
        self._detail_poster_loader = loader

        def _on_loaded(path: str, pixmap: QPixmap, expected_nfo=movie.nfo_path, label=poster_label):
            # 仅在仍是同一部电影时更新 UI
            if not self.current_movie or self.current_movie.nfo_path != expected_nfo:
                return
            if pixmap is not None and not pixmap.isNull():
                label.setPixmap(pixmap)
                label.setScaledContents(True)
            else:
                label.setText("暂无海报")

        loader.image_loaded.connect(_on_loaded)
        loader.start()
    
    def init_ui(self):
        """初始化UI - 空状态"""
        self.setStyleSheet("background-color: #FFFFFF;")
        
        # 主布局
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 显示空状态占位符
        self.show_empty_state()
    
    def show_empty_state(self):
        """显示空状态"""
        # 清空现有内容
        self._clear_layout()
        
        empty_label = QLabel("👈 点击左侧电影查看详情")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("""
            QLabel {
                color: #999999;
                font-size: 18px;
                padding: 100px;
            }
        """)
        self.main_layout.addWidget(empty_label)

    def show_loading_state(self, title: str = ""):
        """显示轻量加载状态，避免点击后主线程卡住。"""
        self._clear_layout()
        text = "正在加载详情..."
        if title:
            text = f"正在加载《{title}》详情..."
        loading_label = QLabel(text)
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_label.setStyleSheet("""
            QLabel {
                color: #6C757D;
                font-size: 16px;
                padding: 60px;
            }
        """)
        self.main_layout.addWidget(loading_label)
    
    def show_movie(self, movie: Movie, watch_history=None, favorite_manager=None, all_movies=None, rank_info=None):
        """显示电影详情

        Args:
            rank_info: 排名信息，可以是 dict 或 list[dict]
                       每个 dict: {"rank": int, "total": int, "source": "douban"|"imdb"}
        """
        t0 = time.perf_counter()
        self._detail_render_generation += 1
        render_generation = self._detail_render_generation
        self.current_movie = movie
        self.watch_history = watch_history
        self.favorite_manager = favorite_manager
        if all_movies is not None:
            self.all_movies = all_movies
        self._clear_layout()
        
        # === 左侧海报区域 ===
        left_widget = QWidget()
        left_widget.setFixedWidth(320)
        left_widget.setStyleSheet("background-color: #F8F9FA;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)
        
        # 海报
        poster_label = QLabel()
        poster_label.setFixedSize(280, 420)
        poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #E9ECEF;
                border-radius: 8px;
                color: #999999;
            }
        """)
        
        if movie.has_poster():
            # 使用缓存加载海报（支持离线模式）
            pixmap = _load_poster_with_cache(movie.poster_path, 280, 420)
            if not pixmap.isNull():
                poster_label.setPixmap(pixmap)
                poster_label.setScaledContents(True)
            else:
                poster_label.setText("加载中...")
                self._load_detail_poster_async(movie, poster_label)
        else:
            poster_label.setText("暂无海报")
        
        left_layout.addWidget(poster_label)
        
        # 观看状态按钮
        watch_btn = QPushButton()
        watch_btn.setFixedHeight(40)
        watch_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        watch_btn.clicked.connect(self._toggle_watch_status)
        
        if movie.watched:
            watch_btn.setText("✓ 已观看")
            watch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28A745;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
        else:
            watch_btn.setText("• 未观看")
            watch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6C757D;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #5A6268;
                }
            """)
        
        left_layout.addWidget(watch_btn)
        
        # 播放按钮
        play_btn = QPushButton("▶ 播放")
        play_btn.setFixedHeight(44)
        play_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        play_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        play_btn.clicked.connect(lambda: self._play_movie(movie))
        left_layout.addWidget(play_btn)
        
        left_layout.addStretch()
        self.main_layout.addWidget(left_widget)
        
        # === 右侧详情滚动区域 ===
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #FFFFFF;
            }
            QScrollBar:vertical {
                background: #F8F9FA;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #CED4DA;
                border-radius: 4px;
            }
        """)
        
        # 内容容器
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(25, 20, 25, 20)
        content_layout.setSpacing(20)
        
        # === 功能按钮栏 ===
        button_bar = self._create_button_bar(movie)
        content_layout.addWidget(button_bar)
        
        # 标题
        title_label = QLabel(movie.title)
        title_label.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #212529;")
        title_label.setWordWrap(True)
        content_layout.addWidget(title_label)

        # 排名角标（支持豆瓣+IMDB多源）
        # 规范化为列表
        rank_list = []
        if rank_info:
            if isinstance(rank_info, dict):
                rank_list = [rank_info]
            elif isinstance(rank_info, list):
                rank_list = rank_info
        
        for ri in rank_list:
            rank = ri.get('rank', 0)
            total = ri.get('total', 250)
            source = ri.get('source', 'douban')
            if source == 'imdb':
                label_text = f"🏆 IMDB TOP{total}  排名 第{rank}名"
            else:
                label_text = f"🏆 豆瓣TOP{total}  排名 第{rank}名"
            rank_label = QLabel(label_text)
            rank_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
            rank_label.setStyleSheet("""
                QLabel {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #D4A017, stop:0.5 #F5C842, stop:1 #D4A017);
                    color: #1C1C1E;
                    padding: 4px 12px;
                    border-radius: 12px;
                }
            """)
            rank_label.setFixedHeight(28)
            rank_label.setFixedWidth(rank_label.sizeHint().width() + 4)
            content_layout.addWidget(rank_label)
        
        # 元信息行
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(15)
        
        # 上映日期（优先显示完整日期，否则仅年份）
        date_text = movie.premiered if movie.premiered else movie.year
        if date_text:
            year_label = QLabel(f"📅 上映时间  {date_text}")
            year_label.setStyleSheet("color: #6C757D; font-size: 13px;")
            meta_layout.addWidget(year_label)
        
        # 类型（中文显示）
        if movie.genres:
            genre_translation = {
                'Action': '动作', 'Adventure': '冒险', 'Animation': '动画',
                'Comedy': '喜剧', 'Crime': '犯罪', 'Documentary': '纪录片',
                'Drama': '剧情', 'Family': '家庭', 'Fantasy': '奇幻',
                'History': '历史', 'Horror': '恐怖', 'Music': '音乐',
                'Mystery': '悬疑', 'Romance': '爱情', 'Science Fiction': '科幻',
                'TV Movie': '电视电影', 'Thriller': '惊悚', 'War': '战争',
                'Western': '西部',
            }
            translated = [genre_translation.get(g, g) for g in movie.genres[:3]]
            genres_text = " / ".join(translated)
            genre_label = QLabel(f"🎬 {genres_text}")
            genre_label.setStyleSheet("color: #6C757D; font-size: 13px;")
            meta_layout.addWidget(genre_label)
        
        meta_layout.addStretch()
        content_layout.addLayout(meta_layout)

        # 先显示轻量占位，重内容分阶段异步渲染，避免点击瞬时卡顿。
        loading_more = QLabel("正在加载更多信息...")
        loading_more.setStyleSheet("color: #999; font-size: 12px;")
        content_layout.addWidget(loading_more)

        def _stage1_render():
            if render_generation != self._detail_render_generation:
                return
            if not self.current_movie or self.current_movie.nfo_path != movie.nfo_path:
                return

            # === 评分 + 剧情简介（阶段1） ===
            if movie.ratings or movie.plot:
                rating_plot_layout = QHBoxLayout()
                rating_plot_layout.setSpacing(20)
                rating_plot_layout.setContentsMargins(0, 0, 0, 0)

                if movie.ratings:
                    ratings_section = self._create_ratings_section(movie)
                    rating_plot_layout.addWidget(ratings_section)

                if movie.plot:
                    plot_widget = QWidget()
                    plot_inner = QVBoxLayout(plot_widget)
                    plot_inner.setContentsMargins(0, 0, 0, 0)
                    plot_inner.setSpacing(6)

                    plot_title = QLabel("📖 剧情简介")
                    plot_title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
                    plot_title.setStyleSheet("color: #495057;")
                    plot_inner.addWidget(plot_title)

                    plot_text = movie.plot or ""
                    if len(plot_text) > MAX_PLOT_CHARS:
                        plot_text = plot_text[:MAX_PLOT_CHARS].rstrip() + "..."

                    plot_label = QLabel(plot_text)
                    plot_label.setFont(QFont("Microsoft YaHei", 11))
                    plot_label.setStyleSheet("color: #6C757D; line-height: 1.6;")
                    plot_label.setWordWrap(True)
                    plot_inner.addWidget(plot_label)
                    plot_inner.addStretch()

                    rating_plot_layout.addWidget(plot_widget, 1)

                content_layout.insertLayout(content_layout.count() - 1, rating_plot_layout)

            # === 系列电影区域（阶段1尾） ===
            if movie.set_name:
                series_section = self._create_series_section(movie)
                if series_section:
                    content_layout.insertWidget(content_layout.count() - 1, series_section)

            logger.info(f"详情阶段1完成: {(time.perf_counter() - t0) * 1000:.1f} ms - {movie.title}")

            QTimer.singleShot(0, _stage2_render)

        def _stage2_render():
            if render_generation != self._detail_render_generation:
                return
            if not self.current_movie or self.current_movie.nfo_path != movie.nfo_path:
                return

            content_layout.insertWidget(content_layout.count() - 1, self._create_separator())

            # === 详细信息（阶段2） ===
            info_section = self._create_info_section(movie)
            content_layout.insertWidget(content_layout.count() - 1, info_section)

            content_layout.insertWidget(content_layout.count() - 1, self._create_separator())

            # === 演职人员与技术参数（阶段2尾） ===
            if movie.directors or movie.actors:
                cast_section = self._create_cast_section(movie)
                content_layout.insertWidget(content_layout.count() - 1, cast_section)

            tech_section = self._create_tech_section(movie)
            if tech_section:
                content_layout.insertWidget(content_layout.count() - 1, tech_section)

            loading_more.deleteLater()
            logger.info(f"详情阶段2完成: {(time.perf_counter() - t0) * 1000:.1f} ms - {movie.title}")

        QTimer.singleShot(0, _stage1_render)
        
        content_layout.addStretch()
        right_scroll.setWidget(content_widget)
        self.main_layout.addWidget(right_scroll)
    
    def _create_rating_logo(self, source: str) -> QLabel:
        """创建评分来源Logo标签 - 优先使用图片文件"""
        import sys
        # Logo图片文件映射
        logo_files = {
            'imdb': 'IMDB.png',
            'themoviedb': 'TMDB.jpg',
            'douban': '豆瓣.png',
        }
        
        # 获取logo目录路径
        if getattr(sys, 'frozen', False):
            # PyInstaller打包后，资源在_MEIPASS临时目录
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_dir = os.path.join(base_dir, 'logo')
        
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        
        if source in logo_files:
            logo_path = os.path.join(logo_dir, logo_files[source])
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                # 统一缩放：高度18px，宽度上限60px
                scaled = pixmap.scaledToHeight(18, Qt.TransformationMode.SmoothTransformation)
                if scaled.width() > 60:
                    scaled = pixmap.scaled(60, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                logo.setPixmap(scaled)
                logo.setFixedSize(64, 22)
                return logo
        
        # 回退：用户评分或未知来源使用文本标签
        fallback_config = {
            'user': {'text': '我的评分', 'bg': '#DC3545', 'fg': '#FFFFFF'},
        }
        config = fallback_config.get(source, {'text': source.upper(), 'bg': '#6C757D', 'fg': '#FFFFFF'})
        logo.setText(config['text'])
        logo.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        logo.setFixedSize(64, 22)
        logo.setStyleSheet(f"""
            QLabel {{
                background-color: {config['bg']};
                color: {config['fg']};
                border-radius: 4px;
                padding: 2px 6px;
            }}
        """)
        return logo

    def _create_ratings_section(self, movie: Movie):
        """创建评分展示区块 - 紧凑卡片式"""
        section = QWidget()
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # 定义显示顺序：用户评分优先
        display_order = ['user', 'douban', 'imdb', 'themoviedb']
        
        for source in display_order:
            if source not in movie.ratings:
                continue
            value = movie.ratings[source]
            card = self._create_single_rating_card(source, value)
            layout.addWidget(card)
        
        # 显示不在预定义顺序中的其他评分
        for source, value in movie.ratings.items():
            if source in display_order:
                continue
            card = self._create_single_rating_card(source, value)
            layout.addWidget(card)
        
        layout.addStretch()
        return section
    
    def _create_single_rating_card(self, source: str, value: float):
        """创建单个评分卡片"""
        card = QWidget()
        card.setFixedSize(90, 70)
        card_bg = '#FFF0F0' if source == 'user' else '#F5F6F8'
        card.setStyleSheet(f"""
            QWidget {{
                background-color: {card_bg};
                border-radius: 8px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(2)
        card_layout.setContentsMargins(6, 8, 6, 6)
        
        # Logo
        logo = self._create_rating_logo(source)
        card_layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 分数
        value_label = QLabel(f"{value:.1f}")
        value_label.setFont(QFont("Microsoft YaHei", 17, QFont.Weight.Bold))
        score_color = '#DC3545' if source == 'user' else '#2C3E50'
        value_label.setStyleSheet(f"color: {score_color}; background: transparent;")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(value_label)
        
        return card
    
    def _create_series_section(self, movie: Movie):
        """创建系列电影区块 - 轻量列表模式（避免同步海报加载导致卡顿）"""
        if not movie.set_name:
            return None
        
        # 查找同系列所有电影（包含当前电影）
        series_movies = [
            m for m in self.all_movies 
            if m.set_name == movie.set_name
        ]
        
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 5, 0, 5)
        section_layout.setSpacing(10)
        
        # 标题行
        header = QLabel(f"🎬 {movie.set_name}（共 {len(series_movies)} 部）")
        header.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        header.setStyleSheet("color: #212529;")
        section_layout.addWidget(header)
        
        if len(series_movies) <= 1:
            hint = QLabel("暂无同系列的其他电影")
            hint.setStyleSheet("color: #999; font-size: 12px;")
            section_layout.addWidget(hint)
            return section
        
        # 按年份排序
        series_movies.sort(key=lambda m: m.year or "0000")

        # 使用轻量按钮列表，避免同步海报解码/缓存读取压住主线程。
        chips_wrap = QWidget()
        chips_layout = QHBoxLayout(chips_wrap)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(8)

        for m in series_movies:
            is_current = (m.nfo_path == movie.nfo_path)
            year_text = f" ({m.year})" if m.year else ""
            btn = QPushButton(f"{m.title}{year_text}")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                "background-color: #CCE8FF; color: #007AFF; border: 1px solid #9CCCF7; border-radius: 12px; padding: 4px 10px;"
                if is_current else
                "background-color: #F1F3F5; color: #495057; border: 1px solid #DEE2E6; border-radius: 12px; padding: 4px 10px;"
            )
            if not is_current:
                btn.clicked.connect(lambda checked=False, mm=m: self.series_movie_clicked.emit(mm))
            else:
                btn.setEnabled(False)
            chips_layout.addWidget(btn)

        chips_layout.addStretch()

        chips_scroll = QScrollArea()
        chips_scroll.setWidgetResizable(True)
        chips_scroll.setFixedHeight(56)
        chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chips_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:horizontal {
                background: #F8F9FA;
                height: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:horizontal {
                background: #CED4DA;
                border-radius: 3px;
            }
        """)
        chips_scroll.setWidget(chips_wrap)
        section_layout.addWidget(chips_scroll)
        
        return section
    
    def _create_series_movie_card(self, movie: Movie, is_current=False):
        """创建系列电影小卡片，海报上叠加评分"""
        card = QWidget()
        card.setFixedSize(100, 195)
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        if is_current:
            card.setStyleSheet("""
                QWidget {
                    background-color: rgba(204, 232, 255, 180);
                    border-radius: 2px;
                }
            """)
        else:
            card.setStyleSheet("""
                QWidget {
                    background-color: #F8F9FA;
                    border-radius: 6px;
                }
                QWidget:hover {
                    background-color: #E9ECEF;
                }
            """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(3)
        
        # 海报容器（用于叠加评分）
        poster_container = QWidget()
        poster_container.setFixedSize(92, 130)
        poster_container.setStyleSheet("background-color: transparent;")
        
        # 海报
        poster = QLabel(poster_container)
        poster.setFixedSize(92, 130)
        poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poster.setStyleSheet("border-radius: 4px; background-color: #DEE2E6;")
        poster.move(0, 0)
        
        if movie.has_poster():
            # 使用缓存加载海报（支持离线模式）
            pixmap = _load_poster_with_cache(movie.poster_path, 92, 130)
            if not pixmap.isNull():
                poster.setPixmap(pixmap)
                poster.setScaledContents(True)
            else:
                poster.setText("🎬")
                poster.setStyleSheet("border-radius: 4px; background-color: #DEE2E6; font-size: 24px;")
        else:
            poster.setText("🎬")
            poster.setStyleSheet("border-radius: 4px; background-color: #DEE2E6; font-size: 24px;")
        
        # 评分叠加层（右下角）
        rating_value = movie.rating
        if rating_value and rating_value > 0:
            rating_badge = QLabel(f"{rating_value:.1f}", poster_container)
            rating_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rating_badge.setFixedSize(36, 18)
            rating_badge.move(92 - 38, 130 - 20)  # 右下角
            rating_badge.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 0.7);
                    color: #FFD700;
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 0px 2px;
                }
            """)
        
        card_layout.addWidget(poster_container)
        
        # 电影名称
        name_text = movie.title if movie.title else "未知"
        name_label = QLabel(name_text)
        name_label.setFont(QFont("Microsoft YaHei", 8))
        name_label.setStyleSheet("color: #333;" if not is_current else "color: #007AFF; font-weight: bold;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(28)
        name_label.setToolTip(movie.title)
        card_layout.addWidget(name_label)
        
        # 年份
        year_text = movie.year if movie.year else ""
        year_label = QLabel(year_text)
        year_label.setFont(QFont("Microsoft YaHei", 8))
        year_label.setStyleSheet("color: #999;")
        year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        year_label.setFixedHeight(14)
        card_layout.addWidget(year_label)
        
        # 点击事件 - 使用 mousePressEvent
        card.mousePressEvent = lambda event, m=movie: self.series_movie_clicked.emit(m)
        
        return card
    
    def _create_separator(self):
        """创建分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #DEE2E6;")
        line.setFixedHeight(1)
        return line
    
    def _create_info_section(self, movie: Movie):
        """创建详细信息区域"""
        section = QWidget()
        layout = QGridLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setColumnStretch(1, 1)
        
        row = 0
        
        # 位置
        if movie.nfo_path:
            layout.addWidget(self._create_info_label("位置:"), row, 0)
            location = os.path.dirname(movie.nfo_path)
            layout.addWidget(self._create_info_value(location), row, 1)
            row += 1
        
        # 信息(文件名等) - 非阻塞：不在点击时做磁盘/网络 stat
        if movie.video_path:
            layout.addWidget(self._create_info_label("信息:"), row, 0, Qt.AlignmentFlag.AlignTop)
            
            # 获取文件信息
            filename = os.path.basename(movie.video_path)
            file_size_text = movie.file_size if movie.file_size else "大小未知"
            
            info_text = f"{filename}\n"
            info_text += file_size_text
            
            if movie.resolution:
                info_text += f" / {movie.resolution}"
            if movie.video_codec:
                info_text += f" / {movie.video_codec}"
            if movie.audio_codec:
                info_text += f" / {movie.audio_codec}"
            
            layout.addWidget(self._create_info_value(info_text), row, 1)
            row += 1
        
        # 类型
        if movie.genres:
            layout.addWidget(self._create_info_label("类型:"), row, 0)
            genres_text = " / ".join(movie.genres)
            layout.addWidget(self._create_info_value(genres_text), row, 1)
            row += 1
        
        # 年份
        if movie.year:
            layout.addWidget(self._create_info_label("年份:"), row, 0)
            layout.addWidget(self._create_info_value(movie.year), row, 1)
            row += 1
        
        # 国家
        if movie.countries:
            layout.addWidget(self._create_info_label("国家:"), row, 0)
            countries_text = " / ".join(movie.countries)
            layout.addWidget(self._create_info_value(countries_text), row, 1)
            row += 1
        
        # 系列
        if movie.set_name:
            layout.addWidget(self._create_info_label("系列:"), row, 0)
            layout.addWidget(self._create_info_value(movie.set_name), row, 1)
            row += 1
        
        # 导演
        if movie.directors:
            layout.addWidget(self._create_info_label("导演:"), row, 0)
            directors_text = " / ".join(movie.directors)
            layout.addWidget(self._create_info_value(directors_text), row, 1)
            row += 1
        
        # 演员
        if movie.actors:
            layout.addWidget(self._create_info_label("演员:"), row, 0, Qt.AlignmentFlag.AlignTop)
            actors_text = " / ".join([actor.name for actor in movie.actors[:10]])
            if len(movie.actors) > 10:
                actors_text += " ..."
            layout.addWidget(self._create_info_value(actors_text), row, 1)
            row += 1
        
        return section
    
    def _create_info_label(self, text: str):
        """创建信息标签"""
        label = QLabel(text)
        label.setStyleSheet("color: #6C757D; font-size: 13px; font-weight: bold;")
        return label
    
    def _create_info_value(self, text: str):
        """创建信息值"""
        label = QLabel(text)
        label.setStyleSheet("color: #495057; font-size: 13px;")
        label.setWordWrap(True)
        return label
    
    def _create_section(self, title: str, content: str):
        """创建通用信息区块"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 内容
        content_label = QLabel(content)
        content_label.setFont(QFont("Microsoft YaHei", 12))
        content_label.setStyleSheet("color: #6C757D; line-height: 1.8;")
        content_label.setWordWrap(True)
        layout.addWidget(content_label)
        
        return section
    
    def _create_cast_section(self, movie: Movie):
        """创建演职人员区块"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # 标题
        title_label = QLabel("🎭 演职人员")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 导演
        if movie.directors:
            director_text = "导演：" + " / ".join(movie.directors)
            director_label = QLabel(director_text)
            director_label.setStyleSheet("color: #6C757D; font-size: 12px;")
            layout.addWidget(director_label)
        
        # 演员（网格布局）
        if movie.actors:
            actors_grid = QGridLayout()
            actors_grid.setSpacing(10)
            
            for idx, actor in enumerate(movie.actors[:8]):
                row = idx // 2
                col = idx % 2
                
                actor_text = f"{actor.name}"
                if actor.role:
                    actor_text += f" 饰 {actor.role}"
                
                actor_label = QLabel(actor_text)
                actor_label.setStyleSheet("color: #6C757D; font-size: 12px;")
                actors_grid.addWidget(actor_label, row, col)
            
            layout.addLayout(actors_grid)
        
        return section
    
    def _create_tech_section(self, movie: Movie):
        """创建技术参数区块"""
        has_tech_info = any([
            movie.resolution,
            movie.hdr_type,
            movie.video_codec,
            movie.audio_codec
        ])
        
        if not has_tech_info:
            return None
        
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("📊 技术参数")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #495057;")
        layout.addWidget(title_label)
        
        # 参数列表
        params = []
        if movie.resolution:
            params.append(f"分辨率：{movie.resolution}")
        if movie.hdr_type:
            params.append(f"HDR：{movie.hdr_type}")
        if movie.video_codec:
            params.append(f"视频编码：{movie.video_codec}")
        if movie.audio_codec:
            params.append(f"音频编码：{movie.audio_codec}")
        
        params_text = " | ".join(params)
        params_label = QLabel(params_text)
        params_label.setStyleSheet("color: #6C757D; font-size: 12px;")
        params_label.setWordWrap(True)
        layout.addWidget(params_label)
        
        return section
    
    def _play_movie(self, movie: Movie):
        """播放电影"""
        if not movie.video_path or not os.path.exists(movie.video_path):
            logger.warning(f"视频文件不存在: {movie.video_path}")
            return
        
        try:
            os.startfile(movie.video_path)
            logger.info(f"正在播放: {movie.video_path}")
        except Exception as e:
            logger.error(f"播放失败: {e}")
    
    def _toggle_watch_status(self):
        """切换观看状态"""
        if not self.current_movie or not self.watch_history:
            return
        
        # 切换状态
        new_status = self.watch_history.toggle_watched(self.current_movie.nfo_path)
        self.current_movie.watched = new_status
        
        # 发射信号通知主窗口
        self.watch_status_changed.emit(self.current_movie.nfo_path, new_status)
        
        # 刷新显示
        self.show_movie(self.current_movie, self.watch_history, self.favorite_manager)
    
    def _create_button_bar(self, movie: Movie):
        """创建功能按钮栏"""
        button_bar = QWidget()
        button_bar.setFixedHeight(50)
        button_bar.setStyleSheet("background-color: #F8F9FA; border-radius: 8px;")
        
        layout = QHBoxLayout(button_bar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        
        # 按钮样式基础
        btn_style = """
            QPushButton {
                background-color: white;
                color: #495057;
                border: 1px solid #DEE2E6;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #E9ECEF;
                border-color: #CED4DA;
            }
        """
        
        # 播放按钮
        play_btn = QPushButton("▶ 播放")
        play_btn.setStyleSheet(btn_style)
        play_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        play_btn.clicked.connect(lambda: self._play_movie(movie))
        layout.addWidget(play_btn)
        
        # 收藏按钮
        favorite_btn = QPushButton()
        is_favorite = self.favorite_manager.is_favorite(movie.nfo_path) if self.favorite_manager else False
        if is_favorite:
            favorite_btn.setText("❤ 收藏")
            favorite_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FFC107;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 15px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #E0A800;
                }
            """)
        else:
            favorite_btn.setText("♡ 收藏")
            favorite_btn.setStyleSheet(btn_style)
        favorite_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        favorite_btn.clicked.connect(self._toggle_favorite)
        layout.addWidget(favorite_btn)
        
        # 网页链接按钮（下拉菜单）
        link_btn = QPushButton("🔗 网页 ▾")
        # 隐藏原生下拉箭头，保留文本中的小箭头
        link_btn_style = btn_style + """
            QPushButton::menu-indicator {
                width: 0px;
                height: 0px;
                image: none;
            }
        """
        link_btn.setStyleSheet(link_btn_style)
        link_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        # 构建可用链接列表
        web_links = []
        if hasattr(movie, 'douban_url') and movie.douban_url:
            web_links.append(("🟢 豆瓣", movie.douban_url))
        if hasattr(movie, 'imdb_id') and movie.imdb_id:
            web_links.append(("🟡 IMDb", f"https://www.imdb.com/title/{movie.imdb_id}/"))
        if hasattr(movie, 'tmdb_id') and movie.tmdb_id:
            web_links.append(("🔵 TMDB", f"https://www.themoviedb.org/movie/{movie.tmdb_id}"))
        
        if len(web_links) > 1:
            # 多个链接：显示下拉菜单
            web_menu = QMenu(link_btn)
            web_menu.setStyleSheet("""
                QMenu {
                    background-color: #FFFFFF;
                    border: 1px solid #DEE2E6;
                    border-radius: 6px;
                    padding: 4px 0;
                }
                QMenu::item {
                    padding: 6px 20px;
                    font-size: 13px;
                    color: #212529;
                }
                QMenu::item:selected {
                    background-color: #E9ECEF;
                }
            """)
            for label, url in web_links:
                action = web_menu.addAction(label)
                action.triggered.connect(lambda checked, u=url: self._open_url(u))
            link_btn.setMenu(web_menu)
        elif len(web_links) == 1:
            # 只有一个链接：直接打开
            link_btn.setText("🔗 网页")
            link_btn.clicked.connect(lambda: self._open_url(web_links[0][1]))
        else:
            link_btn.setEnabled(False)
            link_btn.setText("🔗 网页")
        
        layout.addWidget(link_btn)
        
        # 属性按钮
        props_btn = QPushButton("📝 属性")
        props_btn.setStyleSheet(btn_style)
        props_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        props_btn.clicked.connect(lambda: self._show_properties(movie))
        layout.addWidget(props_btn)

        # 更新海报按钮
        refresh_poster_btn = QPushButton("🖼 更新海报")
        refresh_poster_btn.setStyleSheet(btn_style)
        refresh_poster_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_poster_btn.clicked.connect(lambda: self.refresh_poster_requested.emit(movie))
        layout.addWidget(refresh_poster_btn)
        
        # 打开文件夹按钮
        folder_btn = QPushButton("📁 文件夹")
        folder_btn.setStyleSheet(btn_style)
        folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        folder_btn.clicked.connect(lambda: self._open_folder(movie))
        layout.addWidget(folder_btn)
        
        # 用户评分按钮
        rating_btn = QPushButton("⭐ 评分")
        rating_btn.setStyleSheet(btn_style)
        rating_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rating_btn.clicked.connect(lambda: self._show_rating_dialog(movie))
        layout.addWidget(rating_btn)

        # 删除按钮（仅本地数据库）
        delete_btn = QPushButton("🗑 删除")
        delete_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF5F5;
                color: #C92A2A;
                border: 1px solid #FFC9C9;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #FFE3E3;
                border-color: #FFA8A8;
            }
        """)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(movie))
        layout.addWidget(delete_btn)
        
        layout.addStretch()
        
        return button_bar
    
    def _toggle_favorite(self):
        """切换收藏状态"""
        if not self.current_movie or not self.favorite_manager:
            return
        
        new_status = self.favorite_manager.toggle_favorite(self.current_movie.nfo_path)
        
        # 发射信号通知主窗口
        self.favorite_status_changed.emit(self.current_movie.nfo_path, new_status)
        
        # 刷新显示
        self.show_movie(self.current_movie, self.watch_history, self.favorite_manager)
    
    def _open_url(self, url: str):
        """打开指定URL"""
        try:
            webbrowser.open(url)
            logger.info(f"打开网页: {url}")
        except Exception as e:
            logger.error(f"打开网页失败: {e}")
    
    def _show_properties(self, movie: Movie):
        """显示属性编辑对话框"""
        from ui.nfo_editor_dialog import NFOEditorDialog
        
        dialog = NFOEditorDialog(movie, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 重新解析 NFO 文件，更新内存中的 Movie 对象
            from parsers.nfo_parser import NFOParser
            updated_movie = NFOParser.parse(movie.nfo_path)
            if updated_movie:
                # 保留非 NFO 属性（观看状态、收藏状态等）
                updated_movie.watched = movie.watched
                
                # 更新当前对象的所有属性
                for attr in vars(updated_movie):
                    setattr(movie, attr, getattr(updated_movie, attr))
                
                logger.info(f"NFO文件已更新，已重新加载: {movie.title}")
                
                # 刷新详情面板显示
                self.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)
                
                # 通知主窗口更新缓存
                self.movie_updated.emit(movie)
            else:
                logger.error(f"重新解析 NFO 失败: {movie.nfo_path}")
    
    def _open_folder(self, movie: Movie):
        """打开电影所在文件夹"""
        if not movie.nfo_path:
            return
        
        folder_path = os.path.dirname(movie.nfo_path)
        
        try:
            os.startfile(folder_path)
            logger.info(f"打开文件夹: {folder_path}")
        except Exception as e:
            logger.error(f"打开文件夹失败: {e}")
    
    def _show_rating_dialog(self, movie: Movie):
        """显示用户评分对话框"""
        dialog = UserRatingDialog(movie, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_rating = dialog.get_rating()
            if new_rating > 0:
                # 保存评分到NFO文件
                success = NFOParser.update_user_rating(movie.nfo_path, new_rating)
                
                if success:
                    # 更新Movie对象中的用户评分
                    if not movie.ratings:
                        movie.ratings = {}
                    movie.ratings['user'] = new_rating
                    
                    # 发射信号通知主窗口
                    self.user_rating_changed.emit(movie.nfo_path, new_rating)
                    
                    # 刷新显示
                    self.show_movie(self.current_movie, self.watch_history, self.favorite_manager)
                    
                    QMessageBox.information(self, "成功", f"用户评分已保存: {new_rating}/10")
                else:
                    QMessageBox.warning(self, "失败", "保存评分失败")
    
    def _clear_layout(self):
        """清空布局中的所有控件"""
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class UserRatingDialog(QDialog):
    """用户评分对话框"""
    
    def __init__(self, movie: Movie, parent=None):
        super().__init__(parent)
        self.movie = movie
        self.rating = 0
        
        self.setWindowTitle("用户评分")
        self.setModal(True)
        self.setFixedSize(350, 200)
        
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        title = QLabel(f"为《{self.movie.title}》评分")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #212529;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 评分输入
        rating_layout = QHBoxLayout()
        rating_layout.setSpacing(15)
        
        rating_label = QLabel("评分:")
        rating_label.setStyleSheet("color: #495057; font-size: 14px;")
        rating_layout.addWidget(rating_label)
        
        self.rating_spinbox = QSpinBox()
        self.rating_spinbox.setRange(0, 10)
        self.rating_spinbox.setValue(int(self.movie.rating) if self.movie.rating else 0)
        self.rating_spinbox.setSuffix("  / 10")
        self.rating_spinbox.setFixedWidth(150)
        self.rating_spinbox.setFixedHeight(40)
        # 使用字体设置而不是样式表
        spinbox_font = QFont("Microsoft YaHei", 14)
        spinbox_font.setBold(True)
        self.rating_spinbox.setFont(spinbox_font)
        self.rating_spinbox.setStyleSheet("""
            QSpinBox {
                padding: 5px 10px;
                background-color: white;
                border: 2px solid #DEE2E6;
                border-radius: 4px;
            }
            QSpinBox:focus {
                border-color: #007BFF;
            }
            QSpinBox::up-button {
                width: 25px;
                border-left: 1px solid #DEE2E6;
                background-color: #F8F9FA;
            }
            QSpinBox::down-button {
                width: 25px;
                border-left: 1px solid #DEE2E6;
                background-color: #F8F9FA;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #E9ECEF;
            }
        """)
        rating_layout.addWidget(self.rating_spinbox)
        
        rating_layout.addStretch()
        layout.addLayout(rating_layout)
        
        # 提示
        hint = QLabel("评分将保存到NFO文件中")
        hint.setStyleSheet("color: #6C757D; font-size: 12px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        
        layout.addStretch()
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(100, 36)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #007BFF;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0056B3;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(100, 36)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #5A6268;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def get_rating(self):
        """获取用户输入的评分"""
        return float(self.rating_spinbox.value())

