"""
主窗口
三栏布局：左侧筛选栏、中间海报墙、右侧详情面板
"""
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import List, Set
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QPushButton, QProgressBar, QFrame, QGridLayout,
    QMessageBox, QSizePolicy, QSpacerItem, QSlider, QCheckBox,
    QStackedWidget, QSplitter, QLineEdit, QMenu, QDialog
)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QCursor, QImage, QPixmap

from models.movie import Movie
from ui.movie_card import MovieCard
from ui.detail_panel import MovieDetailPanel
from ui.settings_dialog import SettingsDialog
from ui.flow_layout import FlowLayout
from ui.series_page import SeriesPage
from utils.config_manager import ConfigManager
from utils.library_scanner import LibraryScanner
from utils.watch_history import WatchHistoryManager
from utils.favorite_manager import FavoriteManager
from utils.cache_manager import CacheManager
from utils.image_loader import ImageCache, BatchImageLoader
from utils.network_mode import initialize_offline_cache_mode_once

logger = logging.getLogger(__name__)

# 类型英文到中文映射
GENRE_TRANSLATION = {
    'Action': '动作',
    'Adventure': '冒险',
    'Animation': '动画',
    'Comedy': '喜剧',
    'Crime': '犯罪',
    'Documentary': '纪录片',
    'Drama': '剧情',
    'Family': '家庭',
    'Fantasy': '奇幻',
    'History': '历史',
    'Horror': '恐怖',
    'Music': '音乐',
    'Mystery': '悬疑',
    'Romance': '爱情',
    'Science Fiction': '科幻',
    'TV Movie': '电视电影',
    'Thriller': '惊悚',
    'War': '战争',
    'Western': '西部',
}


class OnlineBackgroundUpdater(QThread):
    """
    在线时后台更新任务（QThread）：
    1. 对 added_time == 0.0 的电影读取磁盘 mtime 并写入 movie.added_time
    2. 对缺少缩略图缓存的电影预热海报缓存（海报墙尺寸 + 详情页高清尺寸）
    完成后发出 finished_signal，通知主线程保存缓存。
    """

    progress = pyqtSignal(int, int)   # (已完成数, 总数)
    finished_signal = pyqtSignal()

    def __init__(
        self,
        movies,
        poster_cache_manager,
        poster_width: int,
        poster_height: int,
        detail_width: int,
        detail_height: int,
        parent=None,
    ):
        super().__init__(parent)
        # 操作共享 movie 对象列表（只写各自的字段，无并发写冲突）
        self._movies = movies
        self._poster_cache = poster_cache_manager
        self._poster_w = poster_width
        self._poster_h = poster_height
        self._detail_w = detail_width
        self._detail_h = detail_height
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage

        total = len(self._movies)
        done = 0
        updated_mtime = 0
        updated_wall_poster = 0
        updated_detail_poster = 0

        for movie in self._movies:
            if self._cancelled:
                break

            # ── 1. 更新 added_time（仅对尚未获取的）─────────────────────────
            if movie.added_time == 0.0:
                stat_path = movie.video_path or movie.nfo_path
                if stat_path:
                    try:
                        movie.added_time = Path(stat_path).stat().st_mtime
                        updated_mtime += 1
                    except Exception:
                        pass

            # ── 2. 预热海报缓存（仅对缓存缺失的）─────────────────────────────
            if movie.poster_path:
                try:
                    need_wall_cache = not self._poster_cache.has_valid_cache(
                        movie.poster_path, self._poster_w, self._poster_h
                    )
                    need_detail_cache = not self._poster_cache.has_valid_cache(
                        movie.poster_path, self._detail_w, self._detail_h
                    )

                    if need_wall_cache or need_detail_cache:
                        img = QImage(movie.poster_path)
                        if not img.isNull():
                            if need_wall_cache:
                                wall_scaled = img.scaled(
                                    self._poster_w,
                                    self._poster_h,
                                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                                if self._poster_cache.save_to_cache_from_image(
                                    movie.poster_path,
                                    self._poster_w,
                                    self._poster_h,
                                    wall_scaled,
                                ):
                                    updated_wall_poster += 1

                            if need_detail_cache:
                                detail_scaled = img.scaled(
                                    self._detail_w,
                                    self._detail_h,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                                if self._poster_cache.save_to_cache_from_image(
                                    movie.poster_path,
                                    self._detail_w,
                                    self._detail_h,
                                    detail_scaled,
                                ):
                                    updated_detail_poster += 1
                except Exception:
                    pass

            done += 1
            if done % 20 == 0:
                self.progress.emit(done, total)

        # 确保索引落盘
        try:
            self._poster_cache.flush_index()
        except Exception:
            pass

        logger.info(
            f"后台更新完成：已更新 mtime={updated_mtime} 部，"
            f"海报墙缓存={updated_wall_poster} 张，详情页高清缓存={updated_detail_poster} 张，"
            f"共处理 {done}/{total} 部电影"
        )
        self.finished_signal.emit()


class LocalOrphanCacheCleaner(QThread):
    """仅清理本地路径孤立缓存的后台任务。"""

    finished_signal = pyqtSignal(int)  # cleaned_count

    def __init__(self, poster_cache_manager, parent=None):
        super().__init__(parent)
        self._poster_cache = poster_cache_manager

    def run(self):
        cleaned = 0
        try:
            cleaned = self._poster_cache.cleanup_orphaned_cache()
        except Exception as e:
            logger.error(f"后台清理孤立缓存失败: {e}")
        self.finished_signal.emit(cleaned)


class HighResPosterBulkUpdater(QThread):
    """批量更新高清海报缓存（仅补缺失，不覆盖已有缓存）。"""

    progress = pyqtSignal(int, int)  # (done, total)
    finished_signal = pyqtSignal(int, int, int, int)  # (total, updated, skipped, failed)

    def __init__(self, movies, poster_cache_manager, detail_width: int = 280, detail_height: int = 420, parent=None):
        super().__init__(parent)
        self._movies = movies
        self._poster_cache = poster_cache_manager
        self._detail_w = detail_width
        self._detail_h = detail_height
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage

        targets = [m for m in self._movies if getattr(m, 'poster_path', '')]
        total = len(targets)
        updated = 0
        skipped = 0
        failed = 0

        done = 0
        for movie in targets:
            if self._cancelled:
                break

            try:
                poster_path = movie.poster_path
                if self._poster_cache.has_valid_cache(poster_path, self._detail_w, self._detail_h):
                    skipped += 1
                else:
                    img = QImage(poster_path)
                    if img.isNull():
                        failed += 1
                    else:
                        detail_scaled = img.scaled(
                            self._detail_w,
                            self._detail_h,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        if self._poster_cache.save_to_cache_from_image(
                            poster_path, self._detail_w, self._detail_h, detail_scaled
                        ):
                            updated += 1
                        else:
                            failed += 1
            except Exception:
                failed += 1

            done += 1
            if done % 20 == 0 or done == total:
                self.progress.emit(done, total)

        try:
            self._poster_cache.flush_index()
        except Exception:
            pass

        self.finished_signal.emit(total, updated, skipped, failed)


class MainWindow(QMainWindow):
    """
    主窗口类 - 三栏布局
    负责整体布局、媒体库扫描、过滤和海报墙展示
    """
    
    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.offline_cache_only = initialize_offline_cache_mode_once(self.config.get_movie_paths())
        self.watch_history = WatchHistoryManager()  # 观看历史管理器
        self.favorite_manager = FavoriteManager()  # 收藏管理器
        self.cache_manager = CacheManager()  # 缓存管理器
        self.all_movies: List[Movie] = []  # 所有电影列表
        self.filtered_movies: List[Movie] = []  # 过滤后的电影列表
        self.movie_cards: List[MovieCard] = []  # 海报卡片列表
        
        # 过滤器状态
        self.selected_genres: Set[str] = set()
        self.selected_countries: Set[str] = set()
        self.selected_years: Set[str] = set()
        self.selected_tags: Set[str] = set()
        self.min_rating: float = 0.0
        self.watch_filter_mode: int = 0  # 0=全部, 1=未观看, 2=已观看
        self.favorite_filter_mode: int = 0  # 0=全部, 1=仅收藏
        self.search_keyword: str = ""  # 全局搜索关键词
        
        # 海报缩放
        self.poster_scale = 1.0  # 缩放比例（0.5 - 2.0）
        self._initial_show_done = False  # 窗口首次显示标志
        self._visible_loader_running = False  # 可见区海报加载是否在运行
        self._detail_request_generation = 0  # 详情渲染请求代号（用于丢弃过期点击）
        self._poster_cache_manager = None
        self._bulk_poster_updater = None
        self._local_cache_cleaner = None
        self._idle_cleanup_timer = None
        self._idle_cleanup_started = False
        self._show_refresh_cleanup_popup = False
        self._incremental_refresh_mode = False
        self._refresh_old_movies_by_nfo = {}
        
        # 排序状态
        self.sort_mode = 'release'  # default, rating, release, added, random
        
        self.init_ui()
        
        # 从配置中恢复缩放比例（必须在init_ui之后）
        saved_scale = self.config.get_poster_scale()
        self.poster_scale = saved_scale / 100.0
        self.scale_slider.setValue(saved_scale)
        self.scale_value_label.setText(f"{saved_scale}%")
        
        self.start_scan()
    
    def closeEvent(self, event):
        """窗口关闭事件，保存状态并清理线程"""
        # 停止扫描线程
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            logger.info("正在停止扫描线程...")
            self.scanner.cancel()
            self.scanner.wait(2000)  # 等待最多2秒
            if self.scanner.isRunning():
                self.scanner.terminate()
        
        # 停止所有批量图片加载线程
        if hasattr(self, '_batch_loaders'):
            for loader in self._batch_loaders:
                if loader.isRunning():
                    loader.cancel()
                    loader.wait(1000)  # 等待最多1秒
                    if loader.isRunning():
                        loader.terminate()

        # 停止后台在线更新线程
        if hasattr(self, '_bg_updater') and self._bg_updater.isRunning():
            self._bg_updater.cancel()
            self._bg_updater.wait(2000)
            if self._bg_updater.isRunning():
                self._bg_updater.terminate()

        # 停止“更新所有海报”线程
        if hasattr(self, '_bulk_poster_updater') and self._bulk_poster_updater is not None:
            if self._bulk_poster_updater.isRunning():
                self._bulk_poster_updater.cancel()
                self._bulk_poster_updater.wait(2000)

        # 停止本地孤立缓存清理线程
        if hasattr(self, '_local_cache_cleaner') and self._local_cache_cleaner is not None:
            if self._local_cache_cleaner.isRunning():
                self._local_cache_cleaner.wait(1000)

        # 停止空闲清理定时器
        if hasattr(self, '_idle_cleanup_timer') and self._idle_cleanup_timer is not None:
            self._idle_cleanup_timer.stop()
        
        # 退出阶段只做快速索引落盘，避免 NAS/UNC exists() 检查导致长时间阻塞
        try:
            if self._poster_cache_manager is not None:
                self._poster_cache_manager.flush_index()
        except Exception as e:
            logger.error(f"落盘海报缓存索引时出错: {e}")
        
        # 保存分割器尺寸
        main_sizes = self.main_splitter.sizes()
        right_sizes = self.right_splitter.sizes()
        self.config.set_splitter_sizes(main_sizes, right_sizes)
        
        # 保存配置
        self.config.save_config()
        logger.info("已保存窗口状态")
        
        event.accept()
    
    def init_ui(self):
        """初始化用户界面 - 左侧筛选 + 右侧上下布局（上：详情，下：海报墙）"""
        self.setWindowTitle("Local Movie Wall - 本地电影海报墙")
        self.setMinimumSize(1600, 900)
        
        # === 中央主容器 ===
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # === 水平分割器：左侧过滤栏 | 右侧内容区 ===
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(3)
        self.main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E0E0E0;
            }
            QSplitter::handle:hover {
                background-color: #007AFF;
            }
        """)
        
        # === 左侧过滤栏 ===
        self.filter_panel = self._create_filter_panel()
        self.main_splitter.addWidget(self.filter_panel)
        
        # === 右侧内容区域（垂直分割：详情 | 海报墙）===
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setHandleWidth(3)
        self.right_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E0E0E0;
            }
            QSplitter::handle:hover {
                background-color: #007AFF;
            }
        """)
        
        # 上半部分：详情面板
        self.detail_panel = MovieDetailPanel()
        self.detail_panel.setMinimumHeight(200)
        # 连接观看状态切换信号
        self.detail_panel.watch_status_changed.connect(self.on_watch_status_toggled)
        # 连接收藏状态切换信号
        self.detail_panel.favorite_status_changed.connect(self.on_favorite_status_toggled)
        # 连接用户评分改变信号
        self.detail_panel.user_rating_changed.connect(self.on_user_rating_changed)
        # 连接系列电影点击信号
        self.detail_panel.series_movie_clicked.connect(self.on_movie_card_clicked)
        # 连接电影信息更新信号（NFO编辑后）
        self.detail_panel.movie_updated.connect(self._on_movie_updated)
        # 连接详情页删除请求（仅本地数据库）
        self.detail_panel.delete_requested.connect(self._menu_delete_movie_local_only)
        # 连接详情页更新海报请求
        self.detail_panel.refresh_poster_requested.connect(self._menu_refresh_movie_poster)
        self.right_splitter.addWidget(self.detail_panel)
        
        # 下半部分：内容切换区域（海报墙 / 系列页）
        content_wrapper = QWidget()
        content_wrapper_layout = QVBoxLayout(content_wrapper)
        content_wrapper_layout.setContentsMargins(10, 0, 0, 0)
        content_wrapper_layout.setSpacing(10)
        self.content_stack = QStackedWidget()
        
        # 页面0：海报墙
        poster_container = QWidget()
        poster_layout = QVBoxLayout(poster_container)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(10)
        
        # 顶部工具栏（缩放 + 排序）
        toolbar = self._create_toolbar()
        poster_layout.addWidget(toolbar)
        
        # 海报墙滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("PosterScrollArea")
        
        # 海报墙容器
        self.poster_wall_widget = QWidget()
        self.poster_wall_widget.setObjectName("PosterWall")
        self.poster_wall_layout = QGridLayout(self.poster_wall_widget)
        self.poster_wall_layout.setSpacing(0)
        self.poster_wall_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area.setWidget(self.poster_wall_widget)
        poster_layout.addWidget(self.scroll_area)
        
        self.content_stack.addWidget(poster_container)  # index 0
        
        # 页面1：系列电影页
        self.series_page = SeriesPage()
        self.series_page.movie_clicked.connect(self._on_series_movie_clicked)
        self.series_page.back_requested.connect(self._switch_to_poster_wall)
        self.content_stack.addWidget(self.series_page)  # index 1
        
        content_wrapper_layout.addWidget(self.content_stack, 1)
        self.right_splitter.addWidget(content_wrapper)
        
        # 设置垂直分割器初始比例（详情:450 海报墙:450）
        self.right_splitter.setStretchFactor(0, 0)  # 详情不自动拉伸
        self.right_splitter.setStretchFactor(1, 1)  # 海报墙占剩余空间
        
        self.main_splitter.addWidget(self.right_splitter)
        
        # 设置水平分割器初始比例（筛选:220 内容:780）
        # 从配置恢复分割器尺寸
        saved_sizes = self.config.get_splitter_sizes()
        if saved_sizes["main"]:
            self.main_splitter.setSizes(saved_sizes["main"])
        else:
            self.main_splitter.setSizes([220, 780])
        
        if saved_sizes["right"]:
            self.right_splitter.setSizes(saved_sizes["right"])
        else:
            self.right_splitter.setSizes([450, 450])
        
        self.main_splitter.setStretchFactor(0, 0)  # 筛选栏不自动拉伸
        self.main_splitter.setStretchFactor(1, 1)  # 内容区占剩余空间
        
        # 筛选栏最小/最大宽度
        self.filter_panel.setMinimumWidth(180)
        self.filter_panel.setMaximumWidth(400)
        
        main_layout.addWidget(self.main_splitter)
    
    def _create_toolbar(self) -> QWidget:
        """创建顶部工具栏（状态 + 排序 + 缩放）"""
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(15)
        
        # 状态标签
        self.status_label = QLabel("正在扫描媒体库...")
        self.status_label.setFont(QFont("Microsoft YaHei", 11))
        self.status_label.setStyleSheet("color: #6C757D;")
        toolbar_layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #DEE2E6;
                border-radius: 4px;
                background-color: #F8F9FA;
                text-align: center;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #007AFF;
                border-radius: 3px;
            }
        """)
        toolbar_layout.addWidget(self.progress_bar)
        
        toolbar_layout.addSpacing(15)
        
        # === 全局搜索框 ===
        search_label = QLabel("🔍 搜索:")
        search_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("片名/导演/演员...")
        self.search_input.setFixedWidth(200)
        self.search_input.setFixedHeight(28)
        self.search_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CED4DA;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                background-color: white;
            }
            QLineEdit:focus {
                border-color: #007AFF;
                background-color: #F0F8FF;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._on_search_enter)
        toolbar_layout.addWidget(self.search_input)
        
        # 清除搜索按钮
        clear_search_btn = QPushButton("✕")
        clear_search_btn.setFixedSize(28, 28)
        clear_search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_search_btn.setToolTip("清除搜索")
        clear_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5A6268;
            }
        """)
        clear_search_btn.clicked.connect(self._clear_search)
        toolbar_layout.addWidget(clear_search_btn)

        # 同名搜索按钮（用于查重）
        duplicate_search_btn = QPushButton("同名")
        duplicate_search_btn.setFixedHeight(28)
        duplicate_search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        duplicate_search_btn.setToolTip("查找片名重复的电影，用于清理重复资源")
        duplicate_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #17A2B8;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        duplicate_search_btn.clicked.connect(self._search_duplicate_titles)
        toolbar_layout.addWidget(duplicate_search_btn)
        
        toolbar_layout.addStretch()
        
        # === 排序按钮组 ===
        sort_label = QLabel("📊 排序:")
        sort_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(sort_label)
        
        sort_buttons = [
            ("默认", "default"),
            ("评分↓", "rating"),
            ("上映时间↓", "release"),
            ("加入时间↓", "added"),
            ("随机", "random")
        ]
        
        for text, mode in sort_buttons:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(mode == 'release')
            btn.setFixedHeight(28)
            btn.setObjectName("SortButton")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked, m=mode, b=btn: self._on_sort_changed(m, b))
            toolbar_layout.addWidget(btn)
        
        toolbar_layout.addSpacing(20)
        
        # 海报缩放控制
        scale_label = QLabel("🔍 缩放:")
        scale_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(scale_label)
        
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(50)  # 0.5x
        self.scale_slider.setMaximum(200)  # 2.0x
        self.scale_slider.setValue(int(self.poster_scale * 100))  # 使用当前缩放值
        self.scale_slider.setFixedWidth(120)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        toolbar_layout.addWidget(self.scale_slider)
        
        self.scale_value_label = QLabel(f"{int(self.poster_scale * 100)}%")
        self.scale_value_label.setStyleSheet("color: #495057; font-size: 12px; font-weight: bold;")
        self.scale_value_label.setFixedWidth(50)
        toolbar_layout.addWidget(self.scale_value_label)
        
        toolbar_layout.addSpacing(20)
        
        # 系列电影入口按钮
        self.series_btn = QPushButton("📚 系列电影")
        self.series_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.series_btn.setFixedHeight(28)
        self.series_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.series_btn.setStyleSheet("""
            QPushButton {
                background-color: #5856D6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 14px;
            }
            QPushButton:hover {
                background-color: #4744B8;
            }
        """)
        self.series_btn.clicked.connect(self._switch_to_series_page)
        toolbar_layout.addWidget(self.series_btn)
        
        # 刮削按钮（独立模块入口）
        self.scrape_btn = QPushButton("🔍 刮削")
        self.scrape_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.scrape_btn.setFixedHeight(28)
        self.scrape_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.scrape_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 14px;
            }
            QPushButton:hover {
                background-color: #E08600;
            }
        """)
        self.scrape_btn.clicked.connect(self._open_scrape_dialog)
        toolbar_layout.addWidget(self.scrape_btn)
        
        return toolbar
    
    def _on_scale_changed(self, value: int):
        """海报缩放改变（防抖：拖拽停止后200ms执行刷新）"""
        self.poster_scale = value / 100.0
        self.scale_value_label.setText(f"{value}%")
        
        if not hasattr(self, '_scale_debounce_timer'):
            from PyQt6.QtCore import QTimer
            self._scale_debounce_timer = QTimer(self)
            self._scale_debounce_timer.setSingleShot(True)
            self._scale_debounce_timer.timeout.connect(self._apply_scale_change)
        self._scale_debounce_timer.start(200)
    
    def _apply_scale_change(self):
        """实际执行缩放刷新和保存"""
        self.config.set_poster_scale(int(self.poster_scale * 100))
        self.config.save_config()
        self.refresh_poster_wall()
    
    def _on_search_changed(self, text: str):
        """搜索框文本改变时（实时搜索，防抖处理）"""
        if not hasattr(self, '_search_debounce_timer'):
            from PyQt6.QtCore import QTimer
            self._search_debounce_timer = QTimer(self)
            self._search_debounce_timer.setSingleShot(True)
            self._search_debounce_timer.timeout.connect(self._apply_search)
        self._search_debounce_timer.start(300)  # 300ms防抖
    
    def _on_search_enter(self):
        """按下回车键时立即搜索"""
        if hasattr(self, '_search_debounce_timer'):
            self._search_debounce_timer.stop()
        self._apply_search()
    
    def _apply_search(self):
        """执行搜索"""
        self.search_keyword = self.search_input.text().strip().lower()
        logger.info(f"执行搜索: '{self.search_keyword}'")
        self.apply_filters()
    
    def _clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.search_keyword = ""
        self.apply_filters()

    def _search_duplicate_titles(self):
        """查找同名电影并显示结果（用于清理重复电影）。"""
        if not self.all_movies:
            self.filtered_movies = []
            self.refresh_poster_wall()
            self.status_label.setText("暂无电影可查重")
            return

        title_groups = {}
        for movie in self.all_movies:
            title = (movie.title or "").strip()
            if not title:
                continue
            key = " ".join(title.lower().split())
            title_groups.setdefault(key, []).append(movie)

        duplicate_groups = [group for group in title_groups.values() if len(group) > 1]
        duplicate_movies = [movie for group in duplicate_groups for movie in group]

        # 保持组内稳定顺序（优先按年份），便于人工比对清理
        duplicate_movies.sort(key=lambda m: ((m.title or "").lower(), m.year or "0000", m.nfo_path or ""))

        self.filtered_movies = duplicate_movies
        self.refresh_poster_wall()

        if duplicate_movies:
            self.status_label.setText(
                f"🔍 同名查重：发现 {len(duplicate_groups)} 组，共 {len(duplicate_movies)} 部重复电影"
            )
        else:
            self.status_label.setText("🔍 同名查重：未发现重复电影")
    
    def _on_sort_changed(self, mode: str, clicked_btn: QPushButton = None):
        """排序模式改变"""
        self.sort_mode = mode
        
        # 更新按钮状态
        if clicked_btn:
            toolbar = clicked_btn.parent()
            if toolbar:
                for btn in toolbar.findChildren(QPushButton):
                    if btn.objectName() == "SortButton":
                        btn.setChecked(False)
                clicked_btn.setChecked(True)
        
        self.refresh_poster_wall()
        
    def showEvent(self, event):
        """窗口显示事件 - 首次显示后刷新海报墙以获取正确宽度"""
        super().showEvent(event)
        if not self._initial_show_done:
            self._initial_show_done = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.refresh_poster_wall)
    
    def _switch_to_series_page(self):
        """切换到系列电影页面"""
        self.series_page.update_movies(self.all_movies)
        self.content_stack.setCurrentIndex(1)
    
    def _open_scrape_dialog(self):
        """打开刮削工作流对话框（独立模块）"""
        from scraper.scrape_dialog import ScrapeDialog
        movie_paths = self.config.get_movie_paths()
        if not movie_paths:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先在配置文件中设置电影目录路径。")
            return
        dialog = ScrapeDialog(
            movie_paths=movie_paths,
            on_complete=self.start_scan,
            parent=self
        )
        dialog.exec()
    
    def _switch_to_poster_wall(self):
        """切换回海报墙页面"""
        self.content_stack.setCurrentIndex(0)
    
    def _on_series_movie_clicked(self, movie):
        """系列页面的电影卡片被点击"""
        self._switch_to_poster_wall()
        self.on_movie_card_clicked(movie)
    
    def resizeEvent(self, event):
        """窗口大小变化时重新计算海报墙布局（防抖）"""
        super().resizeEvent(event)
        if self._initial_show_done and self.filtered_movies:
            # 防抖：避免拖拽窗口时频繁刷新
            if not hasattr(self, '_resize_timer'):
                from PyQt6.QtCore import QTimer
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self.refresh_poster_wall)
            self._resize_timer.start(200)
    
    def _create_filter_panel(self) -> QWidget:
        """创建左侧过滤面板"""
        panel = QWidget()
        panel.setObjectName("FilterPanel")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(0)  # 完全不用自动间距，改用显式spacing
        
        # 标题
        title_label = QLabel("🎬 电影筛选")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1A1A1A; border: none;")
        layout.addWidget(title_label)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #D0D0D0; border: none;")
        layout.addWidget(separator)
        layout.addSpacing(8)
        
        # === 类型过滤区域 ===
        genre_label = QLabel("类型")
        genre_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        genre_label.setStyleSheet("color: #333333;")
        genre_label.setFixedHeight(22)
        layout.addWidget(genre_label)
        layout.addSpacing(2)
        
        self.genre_filter_widget = QWidget()
        self.genre_filter_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.genre_filter_layout = FlowLayout(self.genre_filter_widget, margin=0, spacing=6)
        layout.addWidget(self.genre_filter_widget)
        layout.addSpacing(10)
        
        # === 国家/地区过滤 ===
        country_label = QLabel("国家/地区")
        country_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        country_label.setStyleSheet("color: #333333;")
        country_label.setFixedHeight(22)
        layout.addWidget(country_label)
        layout.addSpacing(2)
        
        self.country_filter_widget = QWidget()
        self.country_filter_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.country_filter_layout = FlowLayout(self.country_filter_widget, margin=0, spacing=6)
        layout.addWidget(self.country_filter_widget)
        layout.addSpacing(10)
        
        # === 年份过滤 ===
        year_label = QLabel("年份")
        year_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        year_label.setStyleSheet("color: #333333;")
        year_label.setFixedHeight(22)
        layout.addWidget(year_label)
        layout.addSpacing(2)
        
        self.year_filter_widget = QWidget()
        self.year_filter_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.year_filter_layout = FlowLayout(self.year_filter_widget, margin=0, spacing=6)
        layout.addWidget(self.year_filter_widget)
        layout.addSpacing(10)
        
        # === 评分筛选 ===
        rating_label = QLabel("评分")
        rating_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        rating_label.setStyleSheet("color: #333333;")
        rating_label.setFixedHeight(22)
        layout.addWidget(rating_label)
        layout.addSpacing(2)
        
        rating_widget = QWidget()
        rating_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        rating_layout = FlowLayout(rating_widget, margin=0, spacing=6)
        
        rating_options = [
            ("全部", 0.0),
            ("7.0+", 7.0),
            ("8.0+", 8.0),
            ("9.0+", 9.0)
        ]
        
        for text, min_value in rating_options:
            rb = self._create_filter_button(text, 'rating', is_all=(min_value == 0.0))
            rb.clicked.connect(lambda checked, mv=min_value: self._on_rating_filter_changed(mv))
            rating_layout.addWidget(rb)
        
        layout.addWidget(rating_widget)
        layout.addSpacing(10)
        
        # === 观看状态 ===
        status_label = QLabel("观看状态")
        status_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        status_label.setStyleSheet("color: #333333;")
        status_label.setFixedHeight(22)
        layout.addWidget(status_label)
        layout.addSpacing(2)
        
        status_widget = QWidget()
        status_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        status_layout = FlowLayout(status_widget, margin=0, spacing=6)
        
        all_status_btn = self._create_filter_button("全部", 'status', is_all=True)
        all_status_btn.setChecked(True)
        all_status_btn.clicked.connect(lambda: self._on_watch_status_changed(0))
        status_layout.addWidget(all_status_btn)
        
        self.unwatched_checkbox = self._create_filter_button("未观看", 'status')
        self.unwatched_checkbox.clicked.connect(lambda: self._on_watch_status_changed(1))
        status_layout.addWidget(self.unwatched_checkbox)
        
        watched_btn = self._create_filter_button("已观看", 'status')
        watched_btn.clicked.connect(lambda: self._on_watch_status_changed(2))
        status_layout.addWidget(watched_btn)
        
        layout.addWidget(status_widget)
        layout.addSpacing(10)
        
        # === 收藏状态 ===
        favorite_label = QLabel("收藏")
        favorite_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        favorite_label.setStyleSheet("color: #333333;")
        favorite_label.setFixedHeight(22)
        layout.addWidget(favorite_label)
        layout.addSpacing(2)
        
        favorite_widget = QWidget()
        favorite_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        favorite_layout = FlowLayout(favorite_widget, margin=0, spacing=6)
        
        all_favorite_btn = self._create_filter_button("全部", 'favorite', is_all=True)
        all_favorite_btn.setChecked(True)
        all_favorite_btn.clicked.connect(lambda: self._on_favorite_filter_changed(0))
        favorite_layout.addWidget(all_favorite_btn)
        
        favorite_only_btn = self._create_filter_button("仅收藏", 'favorite')
        favorite_only_btn.clicked.connect(lambda: self._on_favorite_filter_changed(1))
        favorite_layout.addWidget(favorite_only_btn)
        
        layout.addWidget(favorite_widget)
        layout.addSpacing(10)
        
        # === 自定义标签 ===
        self.tag_label = QLabel("自定义标签")
        self.tag_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.tag_label.setStyleSheet("color: #333333;")
        self.tag_label.setFixedHeight(22)
        
        self.tag_filter_widget = QWidget()
        self.tag_filter_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.tag_filter_layout = FlowLayout(self.tag_filter_widget, margin=0, spacing=6)
        
        # 创建容器来包裹标签标题和widget，方便整体控制显示/隐藏
        self.tag_container = QWidget()
        self.tag_container.setVisible(False)  # 默认隐藏，等有标签时再显示
        tag_container_layout = QVBoxLayout(self.tag_container)
        tag_container_layout.setContentsMargins(0, 0, 0, 0)
        tag_container_layout.setSpacing(2)
        tag_container_layout.addWidget(self.tag_label)
        tag_container_layout.addWidget(self.tag_filter_widget)
        
        layout.addWidget(self.tag_container)
        
        # 弹簧：吸收多余垂直空间，防止上方组件被拉伸
        layout.addStretch(1)
        layout.addSpacing(8)
        
        # === 重置按钮 ===
        reset_button = QPushButton("🔄 重置筛选")
        reset_button.setFont(QFont("Microsoft YaHei", 11))
        reset_button.setFixedHeight(38)
        reset_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset_button.setObjectName("ResetButton")
        reset_button.clicked.connect(self.reset_filters)
        layout.addWidget(reset_button)
        layout.addSpacing(4)
        
        # === 刷新媒体库按钮 ===
        refresh_button = QPushButton("🔃 刷新媒体库")
        refresh_button.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        refresh_button.setFixedHeight(45)
        refresh_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_button.setObjectName("RefreshButton")
        refresh_button.setToolTip("仅更新差异部分，保留本地已有缓存（海报/详情等）")
        refresh_button.clicked.connect(self.refresh_library)
        layout.addWidget(refresh_button)
        layout.addSpacing(4)

        # === 更新所有海报按钮（高清缓存，补缺失）===
        update_all_posters_btn = QPushButton("🖼 更新所有海报")
        update_all_posters_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        update_all_posters_btn.setFixedHeight(42)
        update_all_posters_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        update_all_posters_btn.setObjectName("UpdateAllPostersButton")
        update_all_posters_btn.setToolTip("从服务器拉取所有电影的高清海报到本地缓存（跳过已有缓存）")
        update_all_posters_btn.clicked.connect(self.update_all_posters_high_res)
        layout.addWidget(update_all_posters_btn)
        layout.addSpacing(4)
        
        # === 底部设置按钮（固定在底部）===
        settings_button = QPushButton("⚙️ 媒体库设置")
        settings_button.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        settings_button.setFixedHeight(50)
        settings_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        settings_button.setObjectName("SettingsButton")
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(settings_button)
        
        # 将panel包裹在滚动区域中
        scroll_area = QScrollArea()
        scroll_area.setWidget(panel)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFixedWidth(280)
        scroll_area.setObjectName("FilterScrollArea")
        
        return scroll_area
    
    def start_scan(self, force_rescan: bool = False):
        """开始扫描媒体库
        
        Args:
            force_rescan: 是否强制重新扫描（True时不使用缓存）
        """
        # 如果不是强制扫描，先尝试加载缓存
        if not force_rescan:
            movie_paths = self.config.get_movie_paths()
            cached_movies = self.cache_manager.load_cache(movie_paths)
            
            if cached_movies is not None:
                logger.info(f"从缓存加载了 {len(cached_movies)} 部电影")
                self.all_movies = cached_movies
                
                # 更新观看状态（可能在缓存后有变化）
                for movie in self.all_movies:
                    movie.watched = self.watch_history.is_watched(movie.nfo_path)
                
                # 模拟扫描完成
                self.status_label.setText(f"✅ 从缓存加载，共 {len(cached_movies)} 部电影")
                self.progress_bar.setVisible(False)
                
                # 生成过滤器选项
                self.generate_filter_options()
                
                # 显示所有电影
                self.filtered_movies = self.all_movies.copy()
                self.refresh_poster_wall()
                
                # 恢复上次打开的电影
                self._restore_last_opened_movie()

                # 在线时启动后台更新任务（更新 mtime + 预热海报缓存）
                if not self.offline_cache_only:
                    QTimer.singleShot(2000, self._start_online_background_update)
                    self._schedule_idle_local_cache_cleanup(20000)
                return
        
        # 缓存加载失败或强制扫描，执行正常扫描
        logger.info("启动媒体库扫描...")
        
        # 清空现有数据
        self.all_movies.clear()
        self.filtered_movies.clear()
        self.movie_cards.clear()
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.status_label.setText("正在扫描媒体库...")
        
        # 停止旧扫描线程（如果存在）
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(3000)
        
        # 创建扫描线程
        self.scanner = LibraryScanner()
        self.scanner.progress_updated.connect(self.on_scan_progress)
        self.scanner.movie_found.connect(self.on_movie_found)
        self.scanner.scan_completed.connect(self.on_scan_completed)
        self.scanner.scan_error.connect(self.on_scan_error)
        
        # 启动扫描
        self.scanner.start()
    
    def on_scan_progress(self, current: int, total: int):
        """扫描进度更新"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"正在解析电影信息... {current}/{total}")
    
    def on_movie_found(self, movie: Movie):
        """发现一部电影"""
        # 设置观看状态
        movie.watched = self.watch_history.is_watched(movie.nfo_path)

        # 增量刷新时保留旧缓存中的补充字段（例如 added_time），避免无变化电影被重置。
        if self._incremental_refresh_mode and movie.nfo_path:
            normalized_path = WatchHistoryManager.normalize_path(movie.nfo_path)
            old_movie = self._refresh_old_movies_by_nfo.get(normalized_path)
            if old_movie is not None and getattr(movie, 'added_time', 0.0) == 0.0:
                movie.added_time = getattr(old_movie, 'added_time', 0.0)

        if movie.watched:
            logger.info(f"加载已观看电影: {movie.title} (NFO: {movie.nfo_path})")
        self.all_movies.append(movie)
    
    def on_scan_completed(self, count: int):
        """扫描完成"""
        logger.info(f"扫描完成，共发现 {count} 部电影")
        self.status_label.setText(f"✅ 媒体库加载完成，共 {count} 部电影")
        self.progress_bar.setVisible(False)

        refresh_added = 0
        refresh_removed = 0
        refresh_unchanged = 0
        if self._incremental_refresh_mode:
            old_paths = set(self._refresh_old_movies_by_nfo.keys())
            new_paths = {
                WatchHistoryManager.normalize_path(m.nfo_path)
                for m in self.all_movies
                if m.nfo_path
            }
            refresh_added = len(new_paths - old_paths)
            refresh_removed = len(old_paths - new_paths)
            refresh_unchanged = len(new_paths & old_paths)

        # 清理本地数据库中已失效条目（服务器端已删除目录/电影）
        removed_watched, removed_fav = self._prune_stale_local_records()

        # 仅在“手动刷新媒体库”后提示本次清理统计，避免普通启动频繁打扰。
        if self._show_refresh_cleanup_popup:
            QMessageBox.information(
                self,
                "刷新完成",
                f"媒体库刷新完成。\n\n"
                f"本次差异：\n"
                f"新增电影：{refresh_added} 部\n"
                f"移除电影：{refresh_removed} 部\n"
                f"未变化电影：{refresh_unchanged} 部\n\n"
                f"本次清理结果：\n"
                f"观看历史：{removed_watched} 条\n"
                f"收藏：{removed_fav} 条"
            )
            self._show_refresh_cleanup_popup = False

        # 刷新流程结束，重置增量模式状态
        self._incremental_refresh_mode = False
        self._refresh_old_movies_by_nfo = {}
        
        # 保存缓存
        movie_paths = self.config.get_movie_paths()
        if self.cache_manager.save_cache(self.all_movies, movie_paths):
            logger.info("缓存已保存")
        
        # 生成过滤器选项
        self.generate_filter_options()
        
        # 显示所有电影
        self.filtered_movies = self.all_movies.copy()
        self.refresh_poster_wall()
        
        # 恢复上次打开的电影
        self._restore_last_opened_movie()

        # 在线时启动后台更新任务
        if not self.offline_cache_only:
            QTimer.singleShot(2000, self._start_online_background_update)
            self._schedule_idle_local_cache_cleanup(20000)

    def _prune_stale_local_records(self):
        """按当前扫描结果清理本地数据库中的失效记录。"""
        valid_nfo_paths = {
            WatchHistoryManager.normalize_path(m.nfo_path)
            for m in self.all_movies
            if m.nfo_path
        }

        # 清理观看历史中的失效项
        old_watched_count = len(self.watch_history.watched_movies)
        self.watch_history.watched_movies = {
            p for p in self.watch_history.watched_movies
            if p in valid_nfo_paths
        }
        removed_watched = old_watched_count - len(self.watch_history.watched_movies)
        if removed_watched > 0:
            self.watch_history.save()

        # 清理收藏中的失效项
        old_fav_count = len(self.favorite_manager.favorites)
        self.favorite_manager.favorites = {
            p for p in self.favorite_manager.favorites
            if p in valid_nfo_paths
        }
        removed_fav = old_fav_count - len(self.favorite_manager.favorites)
        if removed_fav > 0:
            self.favorite_manager.save()

        # 清理“上次打开电影”记录
        last_nfo = self.config.get_last_opened_movie()
        if last_nfo and WatchHistoryManager.normalize_path(last_nfo) not in valid_nfo_paths:
            self.config.set_last_opened_movie("")
            logger.info("已清理失效的上次打开电影记录")

        if removed_watched > 0 or removed_fav > 0:
            logger.info(
                f"已清理本地失效记录: 观看历史={removed_watched}, 收藏={removed_fav}"
            )

        return removed_watched, removed_fav

    def _restore_last_opened_movie(self):
        """恢复上次打开的电影"""
        last_nfo = self.config.get_last_opened_movie()
        if last_nfo:
            logger.info(f"尝试恢复上次打开的电影，NFO路径: {last_nfo}")
            found = False
            for movie in self.all_movies:
                if movie.nfo_path == last_nfo:
                    logger.info(f"✓ 成功恢复上次打开的电影: {movie.title}")
                    self.detail_panel.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)
                    found = True
                    break
            if not found:
                logger.warning(f"✗ 未找到匹配的电影，路径可能已改变或电影已删除")
                logger.info(f"保存的路径: {last_nfo}")
                if self.all_movies:
                    logger.info(f"当前共加载 {len(self.all_movies)} 部电影")
        else:
            logger.info("未保存上次打开的电影，跳过恢复")

    def _start_online_background_update(self):
        """在线时启动后台更新：读取 mtime、预热海报缓存，完成后保存缓存。"""
        if not self.all_movies:
            return

        # 防止重复启动
        if getattr(self, '_bg_updater', None) and self._bg_updater.isRunning():
            logger.debug("后台更新任务已在运行，跳过重复启动")
            return

        # 确保 poster_cache_manager 已初始化
        if self._poster_cache_manager is None:
            from utils.poster_cache_manager import PosterCacheManager
            self._poster_cache_manager = PosterCacheManager()

        # 使用当前实际海报尺寸（若还未布局则用默认值）
        pw = getattr(self, '_poster_width', 200)
        ph = getattr(self, '_poster_height', 300)
        detail_w, detail_h = 280, 420

        logger.info(
            f"启动后台更新任务，共 {len(self.all_movies)} 部电影，"
            f"海报墙尺寸 {pw}x{ph}，详情页高清尺寸 {detail_w}x{detail_h}"
        )
        self._bg_updater = OnlineBackgroundUpdater(
            self.all_movies,
            self._poster_cache_manager,
            pw,
            ph,
            detail_w,
            detail_h,
            parent=self,
        )
        self._bg_updater.progress.connect(self._on_bg_update_progress)
        self._bg_updater.finished_signal.connect(self._on_bg_update_finished)
        self._bg_updater.start(QThread.Priority.LowPriority)

    def _on_bg_update_progress(self, done: int, total: int):
        """后台更新进度回调（低频，不更新 UI）"""
        logger.debug(f"后台更新进度: {done}/{total}")

    def _on_bg_update_finished(self):
        """后台更新完成：保存 movie cache（含新 added_time）"""
        logger.info("后台更新完成，保存电影缓存")
        movie_paths = self.config.get_movie_paths()
        if self.cache_manager.save_cache(self.all_movies, movie_paths):
            logger.info("电影缓存（含 mtime）已保存")
        # 后台更新完成后安排一次“空闲本地孤立缓存清理”。
        self._schedule_idle_local_cache_cleanup(5000)

    def _ensure_poster_cache_manager(self):
        if self._poster_cache_manager is None:
            from utils.poster_cache_manager import PosterCacheManager
            self._poster_cache_manager = PosterCacheManager()

    def _is_app_idle_for_cache_cleanup(self) -> bool:
        """判断是否可执行低优先级后台清理任务。"""
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            return False
        if getattr(self, '_visible_loader_running', False):
            return False
        if getattr(self, '_bg_updater', None) is not None and self._bg_updater.isRunning():
            return False
        if hasattr(self, '_batch_loaders'):
            for loader in self._batch_loaders:
                if loader.isRunning():
                    return False
        return True

    def _schedule_idle_local_cache_cleanup(self, delay_ms: int = 30000):
        """在线时按延迟调度空闲清理，仅启动一次周期机制。"""
        if self.offline_cache_only:
            return

        if self._idle_cleanup_timer is None:
            self._idle_cleanup_timer = QTimer(self)
            self._idle_cleanup_timer.setSingleShot(True)
            self._idle_cleanup_timer.timeout.connect(self._try_start_idle_local_cache_cleanup)

        # 只要计时器未运行，就允许调度一次；避免过于频繁重置。
        if not self._idle_cleanup_timer.isActive():
            self._idle_cleanup_timer.start(max(1000, delay_ms))

    def _try_start_idle_local_cache_cleanup(self):
        """在线且空闲时，启动本地孤立缓存后台清理。"""
        if self.offline_cache_only:
            return

        # 任务运行中则等待下次。
        if self._local_cache_cleaner is not None and self._local_cache_cleaner.isRunning():
            self._schedule_idle_local_cache_cleanup(30000)
            return

        if not self._is_app_idle_for_cache_cleanup():
            logger.debug("当前不空闲，延后本地孤立缓存清理")
            self._schedule_idle_local_cache_cleanup(15000)
            return

        self._ensure_poster_cache_manager()
        logger.info("启动空闲后台任务：清理本地路径孤立海报缓存")
        self._local_cache_cleaner = LocalOrphanCacheCleaner(self._poster_cache_manager, parent=self)
        self._local_cache_cleaner.finished_signal.connect(self._on_idle_local_cache_cleanup_finished)
        self._local_cache_cleaner.start(QThread.Priority.LowPriority)

    def _on_idle_local_cache_cleanup_finished(self, cleaned_count: int):
        """本地孤立缓存清理完成后，周期性再次调度。"""
        if cleaned_count > 0:
            logger.info(f"空闲后台清理完成：移除本地孤立缓存 {cleaned_count} 个")
        else:
            logger.debug("空闲后台清理完成：未发现本地孤立缓存")

        # 周期性巡检，避免长期堆积垃圾缓存。
        self._schedule_idle_local_cache_cleanup(20 * 60 * 1000)

    def on_scan_error(self, error_msg: str):
        """扫描错误"""
        logger.error(f"扫描错误: {error_msg}")
        self.status_label.setText(f"❌ 扫描失败: {error_msg}")
        self._show_refresh_cleanup_popup = False
        self._incremental_refresh_mode = False
        self._refresh_old_movies_by_nfo = {}
        QMessageBox.critical(self, "扫描错误", error_msg)
    
    def generate_filter_options(self):
        """根据电影数据生成过滤选项"""
        logger.info("开始生成筛选选项...")
        
        # 先清空现有的过滤器按钮
        while self.genre_filter_layout.count():
            item = self.genre_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        while self.country_filter_layout.count():
            item = self.country_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        while self.year_filter_layout.count():
            item = self.year_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        while self.tag_filter_layout.count():
            item = self.tag_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        logger.info("已清空旧的筛选按钮")
        
        # 收集所有类型、年份、国家、标签
        all_genres = set()
        all_years = set()
        all_countries = set()
        all_tags = set()
        
        for movie in self.all_movies:
            all_genres.update(movie.genres)
            all_countries.update(movie.countries)
            # 防御性获取 tags 属性
            if hasattr(movie, 'tags') and movie.tags:
                all_tags.update(movie.tags)
            if movie.year:
                all_years.add(movie.year)
        
        logger.info(f"收集到的筛选数据: 类型={len(all_genres)}, 国家={len(all_countries)}, 年份={len(all_years)}, 标签={len(all_tags)}")
        
        # 生成类型按钮（先添加"全部"）
        all_genre_btn = self._create_filter_button("全部", filter_type='genre', is_all=True)
        all_genre_btn.setChecked(True)
        all_genre_btn.clicked.connect(lambda: self._clear_filter_category('genre'))
        self.genre_filter_layout.addWidget(all_genre_btn)
        
        genre_count = 0
        for genre in sorted(all_genres):
            # 使用中文显示，但内部使用英文键
            display_name = GENRE_TRANSLATION.get(genre, genre)
            btn = self._create_filter_button(display_name, filter_type='genre')
            btn.setProperty('genre_key', genre)  # 保存英文键
            self.genre_filter_layout.addWidget(btn)
            genre_count += 1
        
        logger.info(f"已添加 {genre_count} 个类型按钮到布局，布局总控件数: {self.genre_filter_layout.count()}")
        
        # 强制更新类型过滤器widget的几何形状
        self.genre_filter_widget.updateGeometry()
        self.genre_filter_widget.adjustSize()
        
        # 生成国家按钮（先添加"全部"）
        all_country_btn = self._create_filter_button("全部", filter_type='country', is_all=True)
        all_country_btn.setChecked(True)
        all_country_btn.clicked.connect(lambda: self._clear_filter_category('country'))
        self.country_filter_layout.addWidget(all_country_btn)
        
        country_count = 0
        for country in sorted(all_countries):
            btn = self._create_filter_button(country, filter_type='country')
            self.country_filter_layout.addWidget(btn)
            country_count += 1
        
        logger.info(f"已添加 {country_count} 个国家按钮到布局，布局总控件数: {self.country_filter_layout.count()}")
        
        # 强制更新国家过滤器widget的几何形状
        self.country_filter_widget.updateGeometry()
        self.country_filter_widget.adjustSize()
        
        # 生成年份按钮（先添加"全部"，倒序）
        all_year_btn = self._create_filter_button("全部", filter_type='year', is_all=True)
        all_year_btn.setChecked(True)
        all_year_btn.clicked.connect(lambda: self._clear_filter_category('year'))
        self.year_filter_layout.addWidget(all_year_btn)
        
        year_count = 0
        for year in sorted(all_years, reverse=True)[:20]:
            btn = self._create_filter_button(year, filter_type='year')
            self.year_filter_layout.addWidget(btn)
            year_count += 1
        
        logger.info(f"已添加 {year_count} 个年份按钮到布局，布局总控件数: {self.year_filter_layout.count()}")
        
        # 强制更新年份过滤器widget的几何形状
        self.year_filter_widget.updateGeometry()
        self.year_filter_widget.adjustSize()
        
        # 生成自定义标签按钮（先添加"全部"）
        if all_tags:
            # 显示标签区域
            self.tag_container.setVisible(True)
            
            all_tag_btn = self._create_filter_button("全部", filter_type='tag', is_all=True)
            all_tag_btn.setChecked(True)
            all_tag_btn.clicked.connect(lambda: self._clear_filter_category('tag'))
            self.tag_filter_layout.addWidget(all_tag_btn)
            
            tag_count = 0
            for tag in sorted(all_tags):
                btn = self._create_filter_button(tag, filter_type='tag')
                self.tag_filter_layout.addWidget(btn)
                tag_count += 1
            
            logger.info(f"已添加 {tag_count} 个标签按钮到布局，布局总控件数: {self.tag_filter_layout.count()}")
            
            # 强制更新标签过滤器widget的几何形状
            self.tag_filter_widget.updateGeometry()
            self.tag_filter_widget.adjustSize()
        else:
            # 隐藏整个标签容器（当没有自定义标签时）
            self.tag_container.setVisible(False)
    
    def _create_filter_button(self, text, filter_type: str, is_all: bool = False) -> QPushButton:
        """创建过滤按钮"""
        # 确保text是字符串（年份可能是整数）
        text_str = str(text)
        btn = QPushButton(text_str)
        btn.setCheckable(True)
        btn.setFont(QFont("Microsoft YaHei", 10))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        # 直接设置样式，不依赖QSS
        if is_all:
            # "全部"按钮 - 红色主题
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #E74C3C;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 14px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #C0392B;
                }
                QPushButton:checked {
                    background-color: #A93226;
                }
            """)
        else:
            # 普通按钮 - 灰色主题
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #F5F5F5;
                    color: #333333;
                    border: 1px solid #E0E0E0;
                    border-radius: 4px;
                    padding: 6px 14px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #E8E8E8;
                    border-color: #007AFF;
                    color: #007AFF;
                }
                QPushButton:checked {
                    background-color: #007AFF;
                    color: white;
                    border-color: #007AFF;
                }
            """)
        
        # 绑定点击事件（"全部"按钮、"status"按钮和"favorite"按钮不绑定，由外部单独处理）
        if not is_all and filter_type != 'status' and filter_type != 'favorite':
            if filter_type == 'genre':
                btn.clicked.connect(lambda checked, b=btn: self.toggle_genre_filter(b))
            elif filter_type == 'country':
                btn.clicked.connect(lambda: self.toggle_country_filter(text_str, btn.isChecked()))
            elif filter_type == 'year':
                btn.clicked.connect(lambda: self.toggle_year_filter(text_str, btn.isChecked()))
            elif filter_type == 'tag':
                btn.clicked.connect(lambda: self.toggle_tag_filter(text_str, btn.isChecked()))
        
        return btn
    
    def _clear_filter_category(self, category: str):
        """清除某个分类的筛选（点击"全部"按钮）"""
        logger.info(f"清除筛选分类: {category}")
        if category == 'genre':
            self.selected_genres.clear()
            layout = self.genre_filter_layout
        elif category == 'country':
            self.selected_countries.clear()
            layout = self.country_filter_layout
        elif category == 'year':
            self.selected_years.clear()
            logger.info(f"  已清空年份筛选，当前: {self.selected_years}")
            layout = self.year_filter_layout
        elif category == 'tag':
            self.selected_tags.clear()
            layout = self.tag_filter_layout
        else:
            return
        
        # 取消除"全部"外的所有按钮选中状态
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, QPushButton):
                    # 保持第一个按钮（"全部"）选中
                    widget.setChecked(i == 0)
        
        self.apply_filters()
    
    def _clear_all_filter_layouts(self):
        """清空所有过滤器布局中的控件"""
        # 清空类型过滤器
        while self.genre_filter_layout.count():
            item = self.genre_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 清空国家过滤器
        while self.country_filter_layout.count():
            item = self.country_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 清空年份过滤器
        while self.year_filter_layout.count():
            item = self.year_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 清空标签过滤器
        while self.tag_filter_layout.count():
            item = self.tag_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def toggle_genre_filter(self, btn: QPushButton):
        """切换类型过滤"""
        genre_key = btn.property('genre_key')  # 获取英文键
        if not genre_key:
            return
        
        if btn.isChecked():
            self.selected_genres.add(genre_key)
        else:
            self.selected_genres.discard(genre_key)
        
        self.apply_filters()
    
    def toggle_country_filter(self, country: str, is_checked: bool):
        """切换国家过滤"""
        if is_checked:
            self.selected_countries.add(country)
        else:
            self.selected_countries.discard(country)
        
        self.apply_filters()
    
    def toggle_year_filter(self, year: str, is_checked: bool):
        """切换年份过滤"""
        logger.info(f"年份筛选切换: year={year}, is_checked={is_checked}")
        if is_checked:
            self.selected_years.add(year)
            logger.info(f"  添加年份: {year}, 当前选中: {self.selected_years}")
        else:
            self.selected_years.discard(year)
            logger.info(f"  移除年份: {year}, 当前选中: {self.selected_years}")
        
        self.apply_filters()
    
    def toggle_tag_filter(self, tag: str, is_checked: bool):
        """切换自定义标签过滤"""
        if is_checked:
            self.selected_tags.add(tag)
        else:
            self.selected_tags.discard(tag)
        
        self.apply_filters()
    
    def _on_rating_filter_changed(self, min_value: float):
        """评分筛选改变"""
        self.min_rating = min_value
        logger.info(f"评分筛选改变: min_rating = {min_value}")
        
        # 更新按钮状态
        sender = self.sender()
        parent = sender.parent()
        if parent:
            for btn in parent.findChildren(QPushButton):
                btn.setChecked(False)
        sender.setChecked(True)
        
        self.apply_filters()
    
    def on_watch_status_toggled(self, nfo_path: str, is_watched: bool):
        """详情面板的观看状态切换
        nfo_path: NFO文件路径
        is_watched: 是否已观看
        """
        logger.info(f"观看状态切换: {nfo_path} -> {is_watched}")
        
        # 规范化路径用于比较
        normalized_path = WatchHistoryManager.normalize_path(nfo_path)
        
        # 更新对应电影对象的watched属性
        found = False
        for movie in self.all_movies:
            # 使用规范化路径比较
            if WatchHistoryManager.normalize_path(movie.nfo_path) == normalized_path:
                movie.watched = is_watched
                logger.info(f"✓ 更新电影观看状态: {movie.title} -> {is_watched}")
                found = True
                break
        
        if not found:
            logger.warning(f"✗ 未找到匹配的电影，NFO路径: {nfo_path}")
            logger.warning(f"  规范化路径: {normalized_path}")
            logger.warning(f"  当前电影总数: {len(self.all_movies)}")
            if self.all_movies:
                logger.warning(f"  示例路径: {self.all_movies[0].nfo_path}")
                logger.warning(f"  示例规范化: {WatchHistoryManager.normalize_path(self.all_movies[0].nfo_path)}")
        
        # 重新应用过滤器
        self.apply_filters()
    
    def on_favorite_status_toggled(self, nfo_path: str, is_favorite: bool):
        """详情面板的收藏状态切换
        nfo_path: NFO文件路径
        is_favorite: 是否已收藏
        """
        logger.info(f"收藏状态切换: {nfo_path} -> {is_favorite}")
        
        # 重新应用过滤器（如果当前在"仅收藏"模式）
        if self.favorite_filter_mode == 1:
            self.apply_filters()
    
    def on_user_rating_changed(self, nfo_path: str, rating: float):
        """详情面板的用户评分改变
        nfo_path: NFO文件路径
        rating: 用户评分
        """
        logger.info(f"用户评分改变: {nfo_path} -> {rating}")
        
        # 更新对应电影对象的评分
        for movie in self.all_movies:
            if movie.nfo_path == nfo_path:
                if not movie.ratings:
                    movie.ratings = {}
                movie.ratings['user'] = rating
                logger.info(f"✓ 更新电影用户评分: {movie.title} -> {rating}")
                break
        
        # 重新应用过滤器（如果有评分筛选）
        if self.min_rating > 0:
            self.apply_filters()
    
    def _on_movie_updated(self, movie):
        """电影NFO编辑后更新缓存"""
        logger.info(f"电影信息已更新: {movie.title}")
        
        # 更新缓存
        movie_paths = self.config.get_movie_paths()
        if self.cache_manager.save_cache(self.all_movies, movie_paths):
            logger.info("缓存已同步更新")
    
    def _on_watch_status_changed(self, status_type: int):
        """观看状态改变
        status_type: 0=全部, 1=未观看, 2=已观看
        """
        # 更新按钮状态
        sender = self.sender()
        parent = sender.parent()
        if parent:
            for btn in parent.findChildren(QPushButton):
                btn.setChecked(False)
        sender.setChecked(True)
        
        self.watch_filter_mode = status_type
        self.apply_filters()
    
    def _on_favorite_filter_changed(self, filter_type: int):
        """收藏筛选改变
        filter_type: 0=全部, 1=仅收藏
        """
        # 更新按钮状态
        sender = self.sender()
        parent = sender.parent()
        if parent:
            for btn in parent.findChildren(QPushButton):
                btn.setChecked(False)
        sender.setChecked(True)
        
        self.favorite_filter_mode = filter_type
        self.apply_filters()
    
    def apply_filters(self):
        """应用所有过滤器"""
        logger.info(f"开始应用过滤器: min_rating={self.min_rating}, watch_mode={self.watch_filter_mode}, 电影总数={len(self.all_movies)}")
        logger.info(f"  激活的筛选: 类型={len(self.selected_genres)}, 国家={len(self.selected_countries)}, 年份={len(self.selected_years)}, 搜索='{self.search_keyword}'")
        
        # 调试：显示所有电影的观看状态
        if self.watch_filter_mode != 0:
            watched_count = sum(1 for m in self.all_movies if m.watched)
            logger.info(f"  当前已观看电影数: {watched_count}/{len(self.all_movies)}")
            for movie in self.all_movies:
                if movie.watched:
                    logger.debug(f"  已观看: {movie.title}")
        
        self.filtered_movies = []
        
        for movie in self.all_movies:
            # 搜索过滤（优先级最高，支持片名、英文原名、导演、演员）
            if self.search_keyword:
                keyword = self.search_keyword
                match_found = False
                
                # 搜索中文片名
                if keyword in movie.title.lower():
                    match_found = True
                
                # 搜索英文原名
                if not match_found and movie.original_title and keyword in movie.original_title.lower():
                    match_found = True
                
                # 搜索导演
                if not match_found:
                    for director in movie.directors:
                        if keyword in director.lower():
                            match_found = True
                            break
                
                # 搜索演员
                if not match_found:
                    for actor in movie.actors:
                        if keyword in actor.name.lower():
                            match_found = True
                            break
                
                if not match_found:
                    continue
            
            # 类型过滤
            if self.selected_genres:
                if not any(genre in self.selected_genres for genre in movie.genres):
                    continue
            
            # 国家过滤
            if self.selected_countries:
                if not any(country in self.selected_countries for country in movie.countries):
                    continue
            
            # 年份过滤
            if self.selected_years:
                if movie.year not in self.selected_years:
                    continue
            
            # 自定义标签过滤
            if self.selected_tags:
                if not any(tag in self.selected_tags for tag in movie.tags):
                    continue
            
            # 评分过滤
            if self.min_rating > 0:
                logger.debug(f"评分过滤: {movie.title} - rating={movie.rating} (type={type(movie.rating)}), min={self.min_rating}, 通过={movie.rating >= self.min_rating}")
                if movie.rating < self.min_rating:
                    continue
            
            # 观看状态过滤
            if self.watch_filter_mode == 1:  # 未观看
                if movie.watched:
                    continue
            elif self.watch_filter_mode == 2:  # 已观看
                if not movie.watched:
                    continue
            # watch_filter_mode == 0 即“全部”，不过滤
            
            # 收藏状态过滤
            if self.favorite_filter_mode == 1:  # 仅收藏
                is_favorite = self.favorite_manager.is_favorite(movie.nfo_path)
                if not is_favorite:
                    continue
            # favorite_filter_mode == 0 即"全部"，不过滤
            
            self.filtered_movies.append(movie)
        
        # 更新状态
        total = len(self.all_movies)
        filtered = len(self.filtered_movies)
        logger.info(f"筛选完成: {filtered}/{total} 部电影通过")
        if filtered > 0:
            logger.info(f"  通过的电影: {', '.join([m.title for m in self.filtered_movies[:5]])}" + 
                       (f" ... (共{filtered}部)" if filtered > 5 else ""))
        self.status_label.setText(f"显示 {filtered} / {total} 部电影")
        
        # 刷新海报墙
        self.refresh_poster_wall()
    
    def reset_filters(self):
        """重置所有过滤器"""
        self.selected_genres.clear()
        self.selected_countries.clear()
        self.selected_years.clear()
        self.selected_tags.clear()
        self.min_rating = 0.0
        self.watch_filter_mode = 0
        self.favorite_filter_mode = 0
        
        # 取消所有筛选按钮的选中状态（遍历整个筛选面板）
        filter_panel = self.genre_filter_layout.parentWidget()
        if filter_panel:
            # 向上找到筛选面板的顶层容器
            top = filter_panel
            while top.parentWidget() and top.parentWidget().objectName() != 'centralwidget':
                top = top.parentWidget()
            # 重置所有 QPushButton 的 checked 状态
            for btn in top.findChildren(QPushButton):
                if btn.isCheckable():
                    btn.setChecked(False)
        
        # 显示所有电影
        self.filtered_movies = self.all_movies.copy()
        self.status_label.setText(f"显示全部 {len(self.all_movies)} 部电影")
        self.refresh_poster_wall()
    
    def refresh_poster_wall(self):
        """刷新海报墙显示 - 分批创建卡片避免UI假死"""
        # 停止之前的批量加载线程
        if hasattr(self, '_batch_loaders'):
            for loader in self._batch_loaders:
                if loader.isRunning():
                    loader.cancel()
        self._batch_loaders = []
        
        # 停止之前的分批创建定时器
        if hasattr(self, '_card_batch_timer') and self._card_batch_timer is not None:
            self._card_batch_timer.stop()
            self._card_batch_timer = None
        
        # 清空现有卡片
        while self.poster_wall_layout.count():
            item = self.poster_wall_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.movie_cards.clear()
        
        # === 空状态视图 ===
        if not self.filtered_movies:
            self._show_empty_state()
            return
        
        # 基础海报尺寸
        base_width, base_height = self.config.get_poster_size()
        
        # 应用缩放
        poster_width = int(base_width * self.poster_scale)
        poster_height = int(base_height * self.poster_scale)
        
        # 根据缩放自动计算列数（海报墙区域宽度）
        wall_width = self.scroll_area.width() - 20  # 减去滚动条宽度
        columns = max(1, wall_width // poster_width)
        
        # 应用排序
        sorted_movies = self._apply_sorting(self.filtered_movies.copy())
        
        # 保存排序后的电影列表和尺寸信息（懒加载用）
        self._sorted_movies = sorted_movies
        self._poster_width = poster_width
        self._poster_height = poster_height
        self._columns = columns
        
        # 连接滚动事件（懒加载） — 避免重复连接
        try:
            self.scroll_area.verticalScrollBar().valueChanged.connect(
                self._on_scroll_lazy_load, Qt.ConnectionType.UniqueConnection)
        except TypeError:
            pass  # 已连接，跳过
        
        # 启动分批创建卡片
        self._card_create_index = 0
        self._card_batch_create()
    
    def _card_batch_create(self):
        """分批创建电影卡片，每批创建若干张，避免阻塞UI"""
        BATCH_SIZE = 50  # 每批创建50个卡片
        
        total = len(self._sorted_movies)
        end = min(self._card_create_index + BATCH_SIZE, total)
        columns = self._columns
        
        for idx in range(self._card_create_index, end):
            movie = self._sorted_movies[idx]
            card = MovieCard(movie, self._poster_width, self._poster_height)
            card.clicked.connect(self.on_movie_card_clicked)
            card.right_clicked.connect(self.on_movie_card_right_clicked)
            card._poster_loaded = False
            card._poster_loading = False
            card._poster_fail_count = 0
            card._poster_next_retry_at = 0.0
            
            row = idx // columns
            col = idx % columns
            self.poster_wall_layout.addWidget(card, row, col)
            self.movie_cards.append(card)
        
        self._card_create_index = end
        
        # 更新状态栏进度
        if end < total:
            self.status_label.setText(f"正在加载海报墙... {end}/{total}")
            # 用 QTimer 让 UI 处理事件后继续创建下一批
            from PyQt6.QtCore import QTimer
            self._card_batch_timer = QTimer(self)
            self._card_batch_timer.setSingleShot(True)
            self._card_batch_timer.timeout.connect(self._card_batch_create)
            self._card_batch_timer.start(0)  # 尽快执行但让出UI线程
        else:
            # 全部创建完成
            self._card_batch_timer = None
            self.poster_wall_layout.setRowStretch(self.poster_wall_layout.rowCount(), 1)
            self.status_label.setText(f"✅ 共 {total} 部电影")
            
            # 加载可见区域海报
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self._load_visible_posters)
    
    def _on_scroll_lazy_load(self):
        """滚动时触发懒加载"""
        if getattr(self, '_suspend_lazy_loading', False):
            return
        if not hasattr(self, '_scroll_lazy_timer'):
            from PyQt6.QtCore import QTimer
            self._scroll_lazy_timer = QTimer(self)
            self._scroll_lazy_timer.setSingleShot(True)
            self._scroll_lazy_timer.timeout.connect(self._load_visible_posters)
        self._scroll_lazy_timer.start(100)  # 100ms防抖
    
    def _load_visible_posters(self):
        """只加载当前可见区域（含预加载缓冲区）的海报"""
        if getattr(self, '_suspend_lazy_loading', False):
            return
        if self._visible_loader_running:
            return
        if not self.movie_cards:
            return
        
        image_cache = ImageCache()
        viewport = self.scroll_area.viewport()
        scroll_y = self.scroll_area.verticalScrollBar().value()
        visible_height = viewport.height()
        
        # 预加载缓冲区：上下各多加载1屏
        buffer = visible_height
        view_top = scroll_y - buffer
        view_bottom = scroll_y + visible_height + buffer
        
        load_tasks = []
        card_map = {}
        MAX_TASKS_PER_BATCH = 8
        now_ts = time.perf_counter()
        next_retry_in = None
        
        for card in self.movie_cards:
            if card._poster_loaded or getattr(card, '_poster_loading', False):
                continue
            
            # 检查卡片是否在可见范围内
            card_y = card.y()
            card_bottom = card_y + card.height()
            
            if card_bottom < view_top or card_y > view_bottom:
                continue  # 不在可见范围，跳过

            retry_at = getattr(card, '_poster_next_retry_at', 0.0)
            if now_ts < retry_at:
                retry_wait = retry_at - now_ts
                if next_retry_in is None or retry_wait < next_retry_in:
                    next_retry_in = retry_wait
                continue

            movie = card.movie

            if not movie.has_poster():
                card.load_poster()  # 显示"暂无海报"
                card._poster_loaded = True
                card._poster_loading = False
            elif image_cache.has(movie.poster_path):
                pixmap = image_cache.get(movie.poster_path)
                card._set_poster_pixmap(pixmap)
                card._poster_loaded = True
                card._poster_loading = False
            else:
                # 标记为正在加载；_poster_loaded 保持 False，直到真正成功后才设 True。
                poster_path = movie.poster_path
                card._poster_loading = True
                load_tasks.append((poster_path, self._poster_width, self._poster_height))
                if poster_path not in card_map:
                    card_map[poster_path] = []
                card_map[poster_path].append(card)

                if len(load_tasks) >= MAX_TASKS_PER_BATCH:
                    break
        
        # 批量异步加载
        if load_tasks:
            # 只保留最新一批加载任务：滚动后旧任务会产生大量过期回调，导致主线程卡顿。
            if hasattr(self, '_batch_loaders'):
                for old_loader in self._batch_loaders:
                    if old_loader.isRunning():
                        old_loader.cancel()

            # 递增批次令牌，用于丢弃过期回调
            if not hasattr(self, '_poster_load_generation'):
                self._poster_load_generation = 0
            self._poster_load_generation += 1
            current_generation = self._poster_load_generation

            loader = BatchImageLoader(load_tasks, self)
            self._visible_loader_running = True
            
            def on_batch_loaded(items, _card_map=card_map, _cache=image_cache):
                from PyQt6 import sip
                # 旧批次回调直接丢弃，避免滚动后的主线程回调风暴
                if current_generation != getattr(self, '_poster_load_generation', current_generation):
                    return

                pending = deque(items)

                def _apply_chunk():
                    # 分片提交 UI 更新，避免单次回调处理过多图片导致卡顿。
                    if current_generation != getattr(self, '_poster_load_generation', current_generation):
                        return

                    applied = 0
                    while pending and applied < 4:
                        path, image = pending.popleft()
                        pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else image
                        if not pixmap.isNull():
                            _cache.set(path, pixmap)
                        if path in _card_map:
                            for c in _card_map[path]:
                                try:
                                    if c is not None and not sip.isdeleted(c):
                                        if not pixmap.isNull():
                                            c._set_poster_pixmap(pixmap)
                                            c._poster_loaded = True
                                            c._poster_fail_count = 0
                                            c._poster_next_retry_at = 0.0
                                        else:
                                            c._poster_fail_count = getattr(c, '_poster_fail_count', 0) + 1
                                            c._poster_next_retry_at = time.perf_counter() + min(3.0, 0.4 * c._poster_fail_count)
                                        c._poster_loading = False
                                except RuntimeError:
                                    pass
                        applied += 1

                    if pending:
                        QTimer.singleShot(0, _apply_chunk)

                QTimer.singleShot(0, _apply_chunk)

            if hasattr(loader, 'batch_loaded'):
                loader.batch_loaded.connect(on_batch_loaded)
            else:
                def on_image_loaded(path, image, _card_map=card_map, _cache=image_cache):
                    from PyQt6 import sip
                    if current_generation != getattr(self, '_poster_load_generation', current_generation):
                        return
                    pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else image
                    _cache.set(path, pixmap)
                    if path in _card_map:
                        for c in _card_map[path]:
                            try:
                                if c is not None and not sip.isdeleted(c):
                                    c._set_poster_pixmap(pixmap)
                            except RuntimeError:
                                pass
                loader.image_loaded.connect(on_image_loaded)

            def on_all_loaded():
                # 批次提前取消时，未被处理到的卡片要回滚为可重试状态。
                for cards in card_map.values():
                    for c in cards:
                        try:
                            if c is None:
                                continue
                            if getattr(c, '_poster_loading', False) and not getattr(c, '_poster_loaded', False):
                                c._poster_loading = False
                                c._poster_fail_count = getattr(c, '_poster_fail_count', 0) + 1
                                # 未完成任务可能是批次取消，短退避后重试，避免永久卡在空白。
                                c._poster_next_retry_at = time.perf_counter() + min(1.5, 0.2 * c._poster_fail_count)
                        except RuntimeError:
                            pass

                self._visible_loader_running = False
                # 若仍有未加载卡片，继续下一小批；使用 singleShot 让出 UI 主线程。
                if not getattr(self, '_suspend_lazy_loading', False):
                    QTimer.singleShot(0, self._load_visible_posters)

            loader.all_loaded.connect(on_all_loaded)
            # 当前仅保留这一批，后续滚动会取消它
            self._batch_loaders = []
            self._batch_loaders.append(loader)
            loader.start()
        elif next_retry_in is not None and not getattr(self, '_suspend_lazy_loading', False):
            # 当前批次都在退避窗口，按最早可重试时间自动唤醒，避免卡片长期不再加载。
            retry_ms = max(60, int(next_retry_in * 1000) + 20)
            if not hasattr(self, '_retry_lazy_timer'):
                self._retry_lazy_timer = QTimer(self)
                self._retry_lazy_timer.setSingleShot(True)
                self._retry_lazy_timer.timeout.connect(self._load_visible_posters)
            self._retry_lazy_timer.start(retry_ms)
    
    def _apply_sorting(self, movies: List[Movie]) -> List[Movie]:
        """应用排序到电影列表"""
        import random
        
        if self.sort_mode == 'rating':
            # 按评分降序
            return sorted(movies, key=lambda m: m.rating, reverse=True)
        elif self.sort_mode == 'release':
            # 按上映时间降序（完整日期 YYYY-MM-DD）
            return sorted(movies, key=lambda m: m.premiered or m.year or "0000", reverse=True)
        elif self.sort_mode == 'added':
            # 按加入时间降序：优先使用缓存的 added_time，网络路径在后台更新后下次排序即生效。
            return sorted(movies, key=lambda m: getattr(m, 'added_time', 0.0), reverse=True)
        elif self.sort_mode == 'random':
            # 随机排序
            shuffled = movies.copy()
            random.shuffle(shuffled)
            return shuffled
        else:
            # 默认排序（保持原顺序）
            return movies
    
    def _show_empty_state(self):
        """显示空状态视图"""
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(25)
        
        # 大图标
        icon_label = QLabel("🎬")
        icon_label.setFont(QFont("Microsoft YaHei", 80))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon_label)
        
        # 主提示文字
        title_label = QLabel("暂无电影")
        title_label.setFont(QFont("Microsoft YaHei", 22, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #333333;")
        empty_layout.addWidget(title_label)
        
        # 副提示文字
        desc_label = QLabel("点击下方按钮添加电影目录，开始构建你的私人影库")
        desc_label.setFont(QFont("Microsoft YaHei", 13))
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setStyleSheet("color: #999999;")
        empty_layout.addWidget(desc_label)
        
        # 添加目录按钮
        add_button = QPushButton("➕ 添加本地电影目录")
        add_button.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        add_button.setFixedSize(280, 60)
        add_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_button.setObjectName("AddLibraryButton")
        add_button.clicked.connect(self.open_settings)
        empty_layout.addWidget(add_button, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 将空状态组件添加到布局
        self.poster_wall_layout.addWidget(empty_widget, 0, 0)
    
    def open_settings(self):
        """打开媒体库设置对话框"""
        dialog = SettingsDialog(self)
        dialog.settings_updated.connect(self.on_settings_updated)
        dialog.exec()
    
    def refresh_library(self):
        """刷新媒体库（增量更新，保留已有缓存）"""
        reply = QMessageBox.question(
            self,
            "确认刷新",
            "确定要刷新媒体库吗？\n"
            "将仅更新差异部分并保留本地已有缓存（海报/详情等）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("用户手动触发媒体库刷新")
            self._show_refresh_cleanup_popup = True

            # 启用增量模式：保留旧数据快照用于差异统计与字段复用。
            self._incremental_refresh_mode = True
            self._refresh_old_movies_by_nfo = {
                WatchHistoryManager.normalize_path(m.nfo_path): m
                for m in self.all_movies
                if m.nfo_path
            }
            
            # 重置状态
            self.all_movies.clear()
            self.filtered_movies.clear()
            self.movie_cards.clear()
            self.selected_genres.clear()
            self.selected_countries.clear()
            self.selected_years.clear()
            self.selected_tags.clear()
            
            # 清空过滤器
            self._clear_all_filter_layouts()
            
            # 显示进度条
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.status_label.setText("正在重新扫描媒体库...")
            
            # 清空海报墙
            while self.poster_wall_layout.count():
                item = self.poster_wall_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # 强制重新扫描（不读取 movie_cache；扫描完成后会写回新缓存）
            self.start_scan(force_rescan=True)
    
    def on_settings_updated(self):
        """设置更新后的回调：重新扫描媒体库"""
        logger.info("媒体库配置已更新，开始重新扫描...")
        
        # 清除缓存（因为路径可能变化）
        self.cache_manager.clear_cache()
        
        # 重置状态
        self.all_movies.clear()
        self.filtered_movies.clear()
        self.movie_cards.clear()
        self.selected_genres.clear()
        self.selected_countries.clear()
        self.selected_years.clear()
        self.selected_tags.clear()
        
        # 清空过滤器
        self._clear_all_filter_layouts()
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在扫描更新的媒体库...")
        
        # 清空海报墙
        while self.poster_wall_layout.count():
            item = self.poster_wall_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 强制重新启动扫描（不使用缓存）
        self.start_scan(force_rescan=True)

    def update_all_posters_high_res(self):
        """从服务器拉取所有电影高清海报到本地缓存（仅补缺失）。"""
        if self.offline_cache_only:
            QMessageBox.information(self, "离线模式", "当前为仅缓存模式，无法从服务器拉取海报。")
            return

        if not self.all_movies:
            QMessageBox.information(self, "提示", "当前没有可更新的电影。")
            return

        if getattr(self, '_bg_updater', None) and self._bg_updater.isRunning():
            QMessageBox.information(self, "请稍候", "后台更新任务正在运行，请稍后再试。")
            return

        if self._bulk_poster_updater is not None and self._bulk_poster_updater.isRunning():
            QMessageBox.information(self, "请稍候", "“更新所有海报”任务已在运行。")
            return

        if self._poster_cache_manager is None:
            from utils.poster_cache_manager import PosterCacheManager
            self._poster_cache_manager = PosterCacheManager()

        self.status_label.setText("正在更新所有高清海报缓存...")
        self._bulk_poster_updater = HighResPosterBulkUpdater(
            self.all_movies,
            self._poster_cache_manager,
            detail_width=280,
            detail_height=420,
            parent=self,
        )
        self._bulk_poster_updater.progress.connect(self._on_bulk_poster_update_progress)
        self._bulk_poster_updater.finished_signal.connect(self._on_bulk_poster_update_finished)
        self._bulk_poster_updater.start(QThread.Priority.LowPriority)

    def _on_bulk_poster_update_progress(self, done: int, total: int):
        self.status_label.setText(f"正在更新所有高清海报缓存... {done}/{total}")

    def _on_bulk_poster_update_finished(self, total: int, updated: int, skipped: int, failed: int):
        self.status_label.setText("✅ 高清海报缓存更新完成")
        QMessageBox.information(
            self,
            "更新所有海报完成",
            f"总计：{total} 部\n"
            f"新增高清缓存：{updated} 部\n"
            f"已存在（跳过）：{skipped} 部\n"
            f"失败：{failed} 部"
        )
        logger.info(
            f"更新所有海报完成: total={total}, updated={updated}, skipped={skipped}, failed={failed}"
        )
    
    def on_movie_card_clicked(self, movie: Movie):
        """海报卡片点击事件 - 在右侧详情面板显示"""
        t0 = time.perf_counter()
        logger.info(f"选中电影: {movie.get_display_title()}")

        # 点击优先：暂停懒加载并取消当前批量任务，避免主线程被图片回调占满。
        self._suspend_lazy_loading = True
        if not hasattr(self, '_resume_lazy_timer'):
            self._resume_lazy_timer = QTimer(self)
            self._resume_lazy_timer.setSingleShot(True)
            self._resume_lazy_timer.timeout.connect(lambda: setattr(self, '_suspend_lazy_loading', False))
        self._resume_lazy_timer.start(1200)

        # 失效旧批次回调
        if not hasattr(self, '_poster_load_generation'):
            self._poster_load_generation = 0
        self._poster_load_generation += 1

        # 停止滚动防抖定时器，避免点击后立即触发新一轮加载
        if hasattr(self, '_scroll_lazy_timer'):
            self._scroll_lazy_timer.stop()

        # 取消当前批量加载线程
        if hasattr(self, '_batch_loaders'):
            for loader in self._batch_loaders:
                if loader.isRunning():
                    loader.cancel()

        # 先显示轻量占位，保证点击瞬时响应；真实详情在下一轮事件循环渲染。
        self.detail_panel.show_loading_state(movie.title)
        self._detail_request_generation += 1
        current_generation = self._detail_request_generation

        def _render_detail():
            if current_generation != self._detail_request_generation:
                return
            self.detail_panel.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)
            logger.info(f"点击到详情渲染调度完成: {(time.perf_counter() - t0) * 1000:.1f} ms - {movie.get_display_title()}")

        QTimer.singleShot(0, _render_detail)
        
        # 保存当前打开的电影
        self.config.set_last_opened_movie(movie.nfo_path)

        # 兜底：点击后如果详情可用缓存海报，回填海报墙对应卡片。
        if movie.has_poster():
            QTimer.singleShot(120, lambda p=movie.poster_path: self._sync_wall_poster_from_cache(p))

    def on_movie_card_right_clicked(self, movie: Movie, global_pos):
        """海报卡片右键菜单"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFFFFF;
                border: 1px solid #DEE2E6;
                border-radius: 6px;
                padding: 4px 0;
            }
            QMenu::item {
                padding: 7px 20px;
                font-size: 13px;
                color: #212529;
            }
            QMenu::item:selected {
                background-color: #E9ECEF;
            }
        """)

        action_play = menu.addAction("▶ 播放")
        action_open_folder = menu.addAction("📁 打开所在文件夹")
        menu.addSeparator()
        action_update_nfo = menu.addAction("📝 更新NFO文件")
        action_update_poster = menu.addAction("🖼 更新海报")
        action_properties = menu.addAction("⚙ 属性")
        menu.addSeparator()
        action_delete_local = menu.addAction("🗑 删除（仅本地数据库）")

        selected = menu.exec(global_pos)
        if selected == action_play:
            self._menu_play_movie(movie)
        elif selected == action_open_folder:
            self._menu_open_movie_folder(movie)
        elif selected == action_update_nfo:
            self._menu_refresh_movie_from_nfo(movie)
        elif selected == action_update_poster:
            self._menu_refresh_movie_poster(movie)
        elif selected == action_properties:
            self._menu_edit_movie_properties(movie)
        elif selected == action_delete_local:
            self._menu_delete_movie_local_only(movie)

    def _menu_play_movie(self, movie: Movie):
        """右键菜单：播放电影"""
        if not movie.video_path or not os.path.exists(movie.video_path):
            QMessageBox.warning(self, "播放失败", "视频文件不存在或不可访问。")
            return
        try:
            os.startfile(movie.video_path)
            logger.info(f"右键播放: {movie.video_path}")
        except Exception as e:
            logger.error(f"右键播放失败: {e}")
            QMessageBox.warning(self, "播放失败", str(e))

    def _menu_open_movie_folder(self, movie: Movie):
        """右键菜单：打开电影所在目录"""
        folder = ""
        if movie.nfo_path:
            folder = os.path.dirname(movie.nfo_path)
        elif movie.video_path:
            folder = os.path.dirname(movie.video_path)

        if not folder:
            QMessageBox.warning(self, "打开失败", "未找到电影目录。")
            return

        try:
            os.startfile(folder)
            logger.info(f"右键打开文件夹: {folder}")
        except Exception as e:
            logger.error(f"右键打开文件夹失败: {e}")
            QMessageBox.warning(self, "打开失败", str(e))

    def _menu_refresh_movie_from_nfo(self, movie: Movie):
        """右键菜单：重新解析NFO并更新本地数据库"""
        if not movie.nfo_path:
            QMessageBox.warning(self, "更新失败", "当前电影缺少NFO路径。")
            return

        from parsers.nfo_parser import NFOParser

        updated_movie = NFOParser.parse(movie.nfo_path)
        if not updated_movie:
            QMessageBox.warning(self, "更新失败", "NFO重新解析失败。")
            return

        # 保留运行期状态
        updated_movie.watched = self.watch_history.is_watched(movie.nfo_path)
        if hasattr(movie, 'added_time') and not getattr(updated_movie, 'added_time', 0.0):
            updated_movie.added_time = getattr(movie, 'added_time', 0.0)

        for attr in vars(updated_movie):
            setattr(movie, attr, getattr(updated_movie, attr))

        # 若当前详情页就是该电影，刷新详情
        if self.detail_panel.current_movie and self.detail_panel.current_movie.nfo_path == movie.nfo_path:
            self.detail_panel.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)

        movie_paths = self.config.get_movie_paths()
        self.cache_manager.save_cache(self.all_movies, movie_paths)
        self.apply_filters()
        logger.info(f"右键更新NFO完成: {movie.title}")

    def _menu_refresh_movie_poster(self, movie: Movie):
        """右键菜单：清理该电影海报缓存并触发重新加载"""
        if not movie.poster_path:
            QMessageBox.information(self, "提示", "该电影没有海报路径。")
            return

        if self._poster_cache_manager is None:
            from utils.poster_cache_manager import PosterCacheManager
            self._poster_cache_manager = PosterCacheManager()

        removed = self._poster_cache_manager.invalidate_cache_for_path(movie.poster_path)

        # 同步清理内存缓存，确保后续会从源图重新加载
        image_cache = ImageCache()
        if hasattr(image_cache, 'remove'):
            image_cache.remove(movie.poster_path)

        for card in self.movie_cards:
            if card.movie.poster_path == movie.poster_path:
                card._poster_loaded = False
                card._poster_loading = False
                card._poster_fail_count = 0
                card._poster_next_retry_at = 0.0

        # 立即尝试重新加载可见区域海报
        self._load_visible_posters()

        # 若当前详情页就是该电影，刷新详情（会触发详情异步海报加载）
        if self.detail_panel.current_movie and self.detail_panel.current_movie.nfo_path == movie.nfo_path:
            self.detail_panel.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)

        logger.info(f"右键更新海报: {movie.title}, 清理缓存条目={removed}")

    def _menu_edit_movie_properties(self, movie: Movie):
        """右键菜单：打开属性编辑（NFO编辑器）"""
        from ui.nfo_editor_dialog import NFOEditorDialog
        from parsers.nfo_parser import NFOParser

        dialog = NFOEditorDialog(movie, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        updated_movie = NFOParser.parse(movie.nfo_path)
        if not updated_movie:
            QMessageBox.warning(self, "更新失败", "属性已保存，但重新解析NFO失败。")
            return

        updated_movie.watched = self.watch_history.is_watched(movie.nfo_path)
        if hasattr(movie, 'added_time') and not getattr(updated_movie, 'added_time', 0.0):
            updated_movie.added_time = getattr(movie, 'added_time', 0.0)

        for attr in vars(updated_movie):
            setattr(movie, attr, getattr(updated_movie, attr))

        if self.detail_panel.current_movie and self.detail_panel.current_movie.nfo_path == movie.nfo_path:
            self.detail_panel.show_movie(movie, self.watch_history, self.favorite_manager, self.all_movies)

        movie_paths = self.config.get_movie_paths()
        self.cache_manager.save_cache(self.all_movies, movie_paths)
        self.apply_filters()
        logger.info(f"右键属性编辑完成: {movie.title}")

    def _menu_delete_movie_local_only(self, movie: Movie):
        """右键菜单：仅从本地数据库移除电影，不删除服务器文件"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要从本地数据库删除《{movie.title}》吗？\n\n"
            f"此操作不会删除服务器上的电影文件，仅移除本地缓存与列表记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        target_nfo = movie.nfo_path

        # 从本地状态中移除（不触碰实际文件）
        self.all_movies = [m for m in self.all_movies if m.nfo_path != target_nfo]
        self.filtered_movies = [m for m in self.filtered_movies if m.nfo_path != target_nfo]

        # 同步移除收藏/观看状态（仅本地JSON）
        if target_nfo:
            self.favorite_manager.remove_favorite(target_nfo)
            self.watch_history.mark_unwatched(target_nfo)

        # 如果删除的是当前详情页电影，清空详情
        if self.detail_panel.current_movie and self.detail_panel.current_movie.nfo_path == target_nfo:
            self.detail_panel.show_empty_state()

        # 清理“上次打开”记录
        if self.config.get_last_opened_movie() == target_nfo:
            self.config.set_last_opened_movie("")

        # 更新本地缓存文件
        movie_paths = self.config.get_movie_paths()
        self.cache_manager.save_cache(self.all_movies, movie_paths)

        # 重新生成筛选项并刷新海报墙
        self.generate_filter_options()
        self.apply_filters()

        logger.info(f"已从本地数据库删除电影（未删除服务器文件）: {movie.title}")

    def _sync_wall_poster_from_cache(self, poster_path: str):
        """将缓存中的海报回填到海报墙，修复个别卡片长期未加载。"""
        if not poster_path or not hasattr(self, '_poster_width') or not hasattr(self, '_poster_height'):
            return

        if self._poster_cache_manager is None:
            from utils.poster_cache_manager import PosterCacheManager
            self._poster_cache_manager = PosterCacheManager()

        pixmap = self._poster_cache_manager.get_cached_pixmap(
            poster_path, self._poster_width, self._poster_height, allow_cross_size_reuse=True
        )
        if pixmap is None or pixmap.isNull():
            return

        updated = 0
        for card in self.movie_cards:
            try:
                if card.movie.poster_path == poster_path and not getattr(card, '_poster_loaded', False):
                    card._set_poster_pixmap(pixmap)
                    card._poster_loaded = True
                    card._poster_loading = False
                    card._poster_fail_count = 0
                    card._poster_next_retry_at = 0.0
                    updated += 1
            except RuntimeError:
                pass

        if updated > 0:
            logger.info(f"海报墙回填缓存海报: {updated} 张")
