"""
系列电影页面
展示所有电影系列，每个系列以横向海报列表显示
"""
import os
import logging
from collections import defaultdict
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QFont, QCursor
from PyQt6 import sip

from models.movie import Movie
from utils.poster_cache_manager import PosterCacheManager
from pathlib import Path


def sip_is_deleted(obj):
    """检查 Qt 对象是否已被删除"""
    try:
        return sip.isdeleted(obj)
    except Exception:
        return True

logger = logging.getLogger(__name__)


class SeriesPage(QWidget):
    """系列电影页面 - 按系列分组展示电影"""
    
    # 点击某部电影的信号
    movie_clicked = pyqtSignal(object)
    # 返回主页信号
    back_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_movies = []
        self._cached_movie_count = -1  # 缓存标记，避免重复构建
        self._poster_cache = {}  # 海报缩略图缓存
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === 顶部栏 ===
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background-color: #FFFFFF; border-bottom: 1px solid #E5E5E5;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)
        header_layout.setSpacing(15)
        
        # 返回按钮
        back_btn = QPushButton("← 返回电影墙")
        back_btn.setFont(QFont("Microsoft YaHei", 11))
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #007AFF;
                border: none;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #0056CC;
                background-color: #F0F0F0;
                border-radius: 6px;
            }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_btn)
        
        # 标题
        title = QLabel("📚 系列电影")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #1A1A1A;")
        header_layout.addWidget(title)
        
        # 统计
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #999; font-size: 12px;")
        header_layout.addWidget(self.stats_label)
        
        header_layout.addStretch()
        layout.addWidget(header)
        
        # === 滚动内容区域 ===
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #F5F5F7;
            }
            QScrollBar:vertical {
                background: #F0F0F0;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #C0C0C0;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #999;
            }
        """)
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: #F5F5F7;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(25, 20, 25, 20)
        self.content_layout.setSpacing(25)
        
        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
    
    def update_movies(self, all_movies: list, force=False):
        """更新电影数据并刷新显示（若数据未变则跳过重建）"""
        movie_count = len(all_movies)
        if not force and self.all_movies is all_movies and self._cached_movie_count == movie_count:
            return  # 数据未变，跳过
        self.all_movies = all_movies
        self._cached_movie_count = movie_count
        self._refresh_series()
    
    def _refresh_series(self):
        """刷新系列电影展示"""
        # 清空现有内容
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 清空待加载队列
        self._pending_posters = []
        
        # 按系列分组
        series_map = defaultdict(list)
        for movie in self.all_movies:
            if movie.set_name:
                series_map[movie.set_name].append(movie)
        
        if not series_map:
            empty = QLabel("暂无系列电影数据\n\n电影的 NFO 文件中需要包含 <set> 标签")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #999; font-size: 16px; padding: 100px;")
            self.content_layout.addWidget(empty)
            self.stats_label.setText("")
            return
        
        # 按系列中电影数量降序排列
        sorted_series = sorted(series_map.items(), key=lambda x: len(x[1]), reverse=True)
        
        total_series = len(sorted_series)
        total_movies = sum(len(movies) for _, movies in sorted_series)
        self.stats_label.setText(f"共 {total_series} 个系列，{total_movies} 部电影")
        
        # 为每个系列创建一个展示区块
        for set_name, movies in sorted_series:
            series_widget = self._create_series_row(set_name, movies)
            self.content_layout.addWidget(series_widget)
        
        self.content_layout.addStretch()
        
        # 延迟加载海报，先显示界面再加载图片
        if self._pending_posters:
            self._poster_load_index = 0
            QTimer.singleShot(0, self._load_poster_batch)
    
    def _load_poster_batch(self):
        """分批加载海报图片，每批加载若干张避免卡顿（支持离线模式）"""
        BATCH_SIZE = 8
        end = min(self._poster_load_index + BATCH_SIZE, len(self._pending_posters))
        cache_manager = PosterCacheManager()
        
        for i in range(self._poster_load_index, end):
            poster_label, poster_path = self._pending_posters[i]
            if not poster_label or sip_is_deleted(poster_label):
                continue
            
            # 检查内存缓存
            cache_key = poster_path
            if cache_key in self._poster_cache:
                poster_label.setPixmap(self._poster_cache[cache_key])
                continue
            
            # 1. 尝试从磁盘缓存加载（仅精确尺寸）
            cached_pixmap = cache_manager.get_cached_pixmap(poster_path, 110, 155, allow_cross_size_reuse=False)
            if cached_pixmap is not None:
                # 裁剪到准确尺寸
                if cached_pixmap.width() > 110 or cached_pixmap.height() > 155:
                    x = (cached_pixmap.width() - 110) // 2
                    y = (cached_pixmap.height() - 155) // 2
                    cached_pixmap = cached_pixmap.copy(x, y, 110, 155)
                self._poster_cache[cache_key] = cached_pixmap
                poster_label.setPixmap(cached_pixmap)
                continue
            
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
                    scaled = pixmap.scaled(
                        110, 155,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    if scaled.width() > 110 or scaled.height() > 155:
                        x = (scaled.width() - 110) // 2
                        y = (scaled.height() - 155) // 2
                        scaled = scaled.copy(x, y, 110, 155)
                    
                    # 保存到磁盘缓存
                    cache_manager.save_to_cache(poster_path, 110, 155, scaled)
                    self._poster_cache[cache_key] = scaled
                    poster_label.setPixmap(scaled)
            else:
                # 4. 离线模式，尝试跨尺寸缓存复用
                cached_pixmap = cache_manager.get_cached_pixmap(poster_path, 110, 155, allow_cross_size_reuse=True)
                if cached_pixmap is not None:
                    # 裁剪到准确尺寸
                    if cached_pixmap.width() > 110 or cached_pixmap.height() > 155:
                        x = (cached_pixmap.width() - 110) // 2
                        y = (cached_pixmap.height() - 155) // 2
                        cached_pixmap = cached_pixmap.copy(x, y, 110, 155)
                    self._poster_cache[cache_key] = cached_pixmap
                    poster_label.setPixmap(cached_pixmap)
            # 离线模式且无缓存时，不设置海报，继续下一张
        
        self._poster_load_index = end
        if self._poster_load_index < len(self._pending_posters):
            QTimer.singleShot(10, self._load_poster_batch)
    
    def _create_series_row(self, set_name: str, movies: list):
        """创建单个系列的横向展示行"""
        row = QWidget()
        row.setStyleSheet("""
            QWidget#SeriesRow {
                background-color: #FFFFFF;
                border-radius: 12px;
            }
        """)
        row.setObjectName("SeriesRow")
        
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(20, 16, 20, 16)
        row_layout.setSpacing(12)
        
        # 系列标题行
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        
        name_label = QLabel(f"🎬 {set_name}")
        name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        name_label.setStyleSheet("color: #1A1A1A;")
        header_layout.addWidget(name_label)
        
        count_label = QLabel(f"{len(movies)} 部")
        count_label.setStyleSheet("""
            color: #FFFFFF;
            background-color: #007AFF;
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        count_label.setFixedHeight(22)
        header_layout.addWidget(count_label)
        
        # 年份范围
        years = sorted([m.year for m in movies if m.year])
        if years:
            year_range = f"{years[0]} - {years[-1]}" if years[0] != years[-1] else years[0]
            year_label = QLabel(year_range)
            year_label.setStyleSheet("color: #999; font-size: 12px;")
            header_layout.addWidget(year_label)
        
        header_layout.addStretch()
        row_layout.addLayout(header_layout)
        
        # 海报横向滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(230)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 5px;
            }
            QScrollBar::handle:horizontal {
                background: #D0D0D0;
                border-radius: 2px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #AAA;
            }
        """)
        
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        cards_layout = QHBoxLayout(container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(14)
        
        # 按年份排序
        movies.sort(key=lambda m: m.premiered or m.year or "0000")
        
        for movie in movies:
            card = self._create_movie_card(movie)
            cards_layout.addWidget(card)
        
        cards_layout.addStretch()
        scroll.setWidget(container)
        row_layout.addWidget(scroll)
        
        return row
    
    def _create_movie_card(self, movie: Movie):
        """创建单部电影卡片"""
        card = QWidget()
        card.setFixedSize(120, 215)
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        card.setObjectName("MovieCard")
        card.setStyleSheet("""
            QWidget#MovieCard {
                background-color: #F8F9FA;
                border-radius: 8px;
            }
            QWidget#MovieCard:hover {
                background-color: #E9ECEF;
            }
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(5, 5, 5, 5)
        card_layout.setSpacing(5)
        
        # 海报
        poster = QLabel()
        poster.setFixedSize(110, 155)
        poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poster.setStyleSheet("""
            QLabel {
                border-radius: 6px;
                background-color: #DEE2E6;
            }
        """)
        
        if movie.has_poster():
            cache_key = movie.poster_path
            if cache_key in self._poster_cache:
                # 已缓存，直接显示
                poster.setPixmap(self._poster_cache[cache_key])
            else:
                # 加入延迟加载队列
                self._pending_posters.append((poster, movie.poster_path))
        else:
            poster.setText("🎬")
            poster.setStyleSheet("""
                QLabel {
                    border-radius: 6px;
                    background-color: #DEE2E6;
                    font-size: 28px;
                }
            """)
        
        card_layout.addWidget(poster, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        title = QLabel(movie.title)
        title.setFont(QFont("Microsoft YaHei", 9))
        title.setStyleSheet("color: #333;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setMaximumHeight(28)
        card_layout.addWidget(title)
        
        # 年份 + 评分
        info_parts = []
        if movie.year:
            info_parts.append(movie.year)
        if movie.rating > 0:
            info_parts.append(f"⭐{movie.rating:.1f}")
        info_text = "  ".join(info_parts)
        
        info = QLabel(info_text)
        info.setFont(QFont("Microsoft YaHei", 8))
        info.setStyleSheet("color: #999;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setFixedHeight(14)
        card_layout.addWidget(info)
        
        # 点击事件
        card.mousePressEvent = lambda event, m=movie: self.movie_clicked.emit(m)
        
        return card
