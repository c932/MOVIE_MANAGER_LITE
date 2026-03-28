"""
电影海报卡片组件
可点击的海报卡片，展示海报、标题、评分和技术徽章
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsDropShadowEffect, QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QCursor

from models.movie import Movie
from utils.image_loader import ImageLoader, ImageCache


class MovieCard(QWidget):
    """
    电影海报卡片组件 - 带徽章和评分的紧凑版
    """
    
    # 点击信号：传递 Movie 对象
    clicked = pyqtSignal(Movie)
    # 右键信号：传递 Movie 对象与全局坐标
    right_clicked = pyqtSignal(Movie, object)
    
    def __init__(self, movie: Movie, poster_width: int = 200, poster_height: int = 300, parent=None):
        """
        初始化电影卡片
        
        Args:
            movie: 电影数据对象
            poster_width: 海报宽度
            poster_height: 海报高度
        """
        super().__init__(parent)
        self.movie = movie
        self.poster_width = poster_width
        self.poster_height = poster_height
        self.is_hovered = False
        
        # 图片缓存
        self.image_cache = ImageCache()
        
        self.init_ui()
        # 不再在构造时自动加载海报，改由外部批量加载
    
    def init_ui(self):
        """初始化 UI 布局 - 紧凑无边距版本"""
        self.setFixedSize(self.poster_width, self.poster_height)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        # 海报容器（使用绝对定位叠加徽章）
        self.poster_container = QWidget(self)
        self.poster_container.setGeometry(0, 0, self.poster_width, self.poster_height)
        
        # 海报背景标签
        self.poster_label = QLabel(self.poster_container)
        self.poster_label.setGeometry(0, 0, self.poster_width, self.poster_height)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setStyleSheet("background-color: #2C2C2E; border-radius: 8px;")
        self.poster_label.setScaledContents(False)
        
        # === 技术徽章层（左上角）===
        self.tech_badges_container = QWidget(self.poster_container)
        self.tech_badges_container.setGeometry(6, 6, self.poster_width - 12, 30)
        tech_layout = QHBoxLayout(self.tech_badges_container)
        tech_layout.setContentsMargins(0, 0, 0, 0)
        tech_layout.setSpacing(4)
        
        # 分辨率徽章
        if self.movie.resolution:
            res_badge = self._create_badge(self.movie.resolution, "#E74C3C")  # 红色
            tech_layout.addWidget(res_badge)
        
        # HDR徽章
        if self.movie.hdr_type:
            hdr_text = "DV" if "dolby" in self.movie.hdr_type.lower() else "HDR"
            hdr_badge = self._create_badge(hdr_text, "#9B59B6")  # 紫色
            tech_layout.addWidget(hdr_badge)
        
        tech_layout.addStretch()
        
        # === 评分徽章（右上角）===
        if self.movie.rating > 0:
            self.rating_badge = QLabel(self.poster_container)
            rating_icon = "⭐" if self.movie.rating_source == "douban" else "★"
            self.rating_badge.setText(f"{rating_icon} {self.movie.rating:.1f}")
            self.rating_badge.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 193, 7, 0.95);
                    color: #1C1C1E;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 4px 8px;
                    border-radius: 10px;
                }
            """)
            self.rating_badge.adjustSize()
            # 定位到右上角
            self.rating_badge.move(self.poster_width - self.rating_badge.width() - 6, 6)
        
        # 设置卡片阴影（整体）
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        # === 电影名称（底部半透明遮罩）===
        self.title_label = QLabel(self.poster_container)
        title_text = self.movie.title or ""
        self.title_label.setText(title_text)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 根据海报大小动态调整字体
        font_size = max(12, min(16, self.poster_width // 12))
        label_height = max(36, min(56, self.poster_height // 5))
        self.title_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 0.7);
                color: #FFFFFF;
                font-size: {font_size}px;
                font-weight: bold;
                padding: 4px 6px;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
        """)
        self.title_label.setGeometry(0, self.poster_height - label_height, self.poster_width, label_height)
    
    def _create_badge(self, text: str, color: str) -> QLabel:
        """创建技术徽章标签"""
        badge = QLabel(text)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: #FFFFFF;
                font-size: 10px;
                font-weight: bold;
                padding: 3px 6px;
                border-radius: 8px;
            }}
        """)
        badge.setFixedHeight(20)
        return badge
    
    def load_poster(self):
        """加载海报图片（异步）"""
        if not self.movie.has_poster():
            # 无海报时显示默认占位图
            self.poster_label.setText("暂无海报")
            self.poster_label.setStyleSheet("""
                QLabel {
                    background-color: #3C3C3E;
                    border-radius: 8px;
                    color: #999999;
                    font-size: 12px;
                }
            """)
            return
        
        # 检查缓存
        if self.image_cache.has(self.movie.poster_path):
            pixmap = self.image_cache.get(self.movie.poster_path)
            self._set_poster_pixmap(pixmap)
            return
        
        # 异步加载图片
        self.image_loader = ImageLoader(
            self.movie.poster_path,
            self.poster_width,
            self.poster_height
        )
        self.image_loader.image_loaded.connect(self._on_image_loaded)
        self.image_loader.start()
    
    def _on_image_loaded(self, path: str, pixmap: QPixmap):
        """图片加载完成回调"""
        # 缓存图片
        self.image_cache.set(path, pixmap)
        
        # 显示图片
        self._set_poster_pixmap(pixmap)
    
    def _set_poster_pixmap(self, pixmap: QPixmap):
        """设置海报图片"""
        if not pixmap.isNull():
            self.poster_label.setPixmap(pixmap)
        else:
            self.poster_label.setText("加载失败")
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.movie)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.movie, self.mapToGlobal(event.pos()))
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        """鼠标进入事件（悬停效果）"""
        self.is_hovered = True
        self.setStyleSheet("""
            MovieCard {
                border: 3px solid #007AFF;
                border-radius: 8px;
            }
        """)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self.is_hovered = False
        self.setStyleSheet("")
        super().leaveEvent(event)

