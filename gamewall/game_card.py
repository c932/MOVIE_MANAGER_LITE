"""
游戏海报卡片组件
可点击的封面卡片，展示封面、标题、Steam 好评率与徽章
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QCursor

from gamewall.game_models import Game
from utils.image_loader import ImageCache


class GameCard(QWidget):
    """
    游戏封面卡片组件（与电影墙 MovieCard 同一视觉规范）
    徽章布局：左上 3A（金）、右上 Steam 好评率（半透明金）、左下 已安装（绿）
    """

    clicked = pyqtSignal(Game)
    right_clicked = pyqtSignal(Game, object)

    def __init__(self, game: Game, poster_width: int = 200, poster_height: int = 300, parent=None):
        super().__init__(parent)
        self.game = game
        self.poster_width = poster_width
        self.poster_height = poster_height
        self.is_hovered = False

        self.image_cache = ImageCache()

        # 懒加载状态标记（主窗口管理）
        self._poster_loaded = False
        self._poster_loading = False
        self._poster_fail_count = 0
        self._poster_next_retry_at = 0.0

        self.init_ui()

    def init_ui(self):
        self.setObjectName("GameCard")
        self.setFixedSize(self.poster_width, self.poster_height)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.poster_container = QWidget(self)
        self.poster_container.setGeometry(0, 0, self.poster_width, self.poster_height)

        # 封面背景标签
        self.poster_label = QLabel(self.poster_container)
        self.poster_label.setGeometry(0, 0, self.poster_width, self.poster_height)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setStyleSheet("background-color: #2C2C2E; border-radius: 8px;")
        self.poster_label.setScaledContents(False)

        # === 3A 徽章（左上角）===
        self.aaa_badge = None
        if self.game.is_aaa:
            self.aaa_badge = self._make_badge("3A", "rgba(212, 160, 23, 0.85)")
            self.aaa_badge.setParent(self.poster_container)
            self.aaa_badge.move(6, 6)

        # === Steam 好评率徽章（右上角，半透明）===
        self.rating_badge = None
        if self.game.steam_positive_pct > 0:
            self.rating_badge = QLabel(self.poster_container)
            self.rating_badge.setText(f"⭐ {self.game.steam_positive_pct:.0f}%")
            self.rating_badge.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 193, 7, 0.75);
                    color: #1C1C1E;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 6px;
                    border-radius: 4px;
                }
            """)
            self.rating_badge.adjustSize()
            self.rating_badge.move(self.poster_width - self.rating_badge.width() - 6, 6)

        # === 已安装徽章（左下角）===
        self.installed_badge = None
        if self.game.installed:
            self.installed_badge = self._make_badge("已安装", "rgba(40, 167, 69, 0.85)")
            self.installed_badge.setParent(self.poster_container)
            self.installed_badge.move(6, self.poster_height - 30)

        # 设置卡片阴影（仅在卡片数较少时启用；4721 张卡同时带高斯模糊
        # 会导致全屏/最大化时 Qt 渲染内存爆掉而崩溃）
        # TODO: 根据当前可见卡片数动态开关阴影
        # shadow = QGraphicsDropShadowEffect()
        # shadow.setBlurRadius(20)
        # shadow.setColor(QColor(0, 0, 0, 40))
        # shadow.setOffset(0, 4)
        # self.setGraphicsEffect(shadow)

        # === 游戏名（底部半透明遮罩）===
        self.title_label = QLabel(self.poster_container)
        self.title_label.setText(self.game.display_title())
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_title()
        label_height = max(36, min(56, self.poster_height // 5))
        self.title_label.setGeometry(0, self.poster_height - label_height,
                                     self.poster_width, label_height)
        # 确保初始状态有占位文字，避免卡片创建时就是完全空白
        self.ensure_placeholder()

    def _make_badge(self, text: str, bg: str) -> QLabel:
        badge = QLabel(text)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: #FFFFFF;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 4px;
            }}
        """)
        badge.setFixedHeight(20)
        return badge

    def _style_title(self):
        pw = self.poster_width
        font_size = max(12, min(16, pw // 12))
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

    def _relayout(self):
        """缩放后重新布局所有子控件"""
        pw, ph = self.poster_width, self.poster_height
        self.poster_container.setGeometry(0, 0, pw, ph)
        self.poster_label.setGeometry(0, 0, pw, ph)

        if self.aaa_badge:
            self.aaa_badge.move(6, 6)
        if self.rating_badge:
            self.rating_badge.adjustSize()
            self.rating_badge.move(pw - self.rating_badge.width() - 6, 6)
        if self.installed_badge:
            self.installed_badge.move(6, ph - 30)

        self._style_title()
        label_height = max(36, min(56, ph // 5))
        self.title_label.setGeometry(0, ph - label_height, pw, label_height)

    def update_game_info(self, game: Game):
        """卡片池复用时同步游戏数据与徽章"""
        self.game = game
        # 标题
        self.title_label.setText(game.display_title())
        # 3A
        if game.is_aaa and self.aaa_badge is None:
            self.aaa_badge = self._make_badge("3A", "rgba(212, 160, 23, 0.85)")
            self.aaa_badge.setParent(self.poster_container)
            self.aaa_badge.move(6, 6)
            self.aaa_badge.show()
        elif not game.is_aaa and self.aaa_badge is not None:
            self.aaa_badge.hide()
            self.aaa_badge.deleteLater()
            self.aaa_badge = None
        # 好评率
        if game.steam_positive_pct > 0:
            if self.rating_badge is None:
                self.rating_badge = QLabel(self.poster_container)
                self.rating_badge.setStyleSheet("""
                    QLabel {
                        background-color: rgba(255, 193, 7, 0.75);
                        color: #1C1C1E;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 2px 6px;
                        border-radius: 4px;
                    }
                """)
            self.rating_badge.setText(f"⭐ {game.steam_positive_pct:.0f}%")
            self.rating_badge.adjustSize()
            self.rating_badge.move(self.poster_width - self.rating_badge.width() - 6, 6)
            self.rating_badge.show()
        elif self.rating_badge is not None:
            self.rating_badge.hide()
            self.rating_badge.deleteLater()
            self.rating_badge = None
        # 已安装
        if game.installed and self.installed_badge is None:
            self.installed_badge = self._make_badge("已安装", "rgba(40, 167, 69, 0.85)")
            self.installed_badge.setParent(self.poster_container)
            self.installed_badge.move(6, self.poster_height - 30)
            self.installed_badge.show()
        elif not game.installed and self.installed_badge is not None:
            self.installed_badge.hide()
            self.installed_badge.deleteLater()
            self.installed_badge = None

    def load_placeholder(self):
        """无封面时显示占位——确保卡片不会变成完全空白"""
        self.poster_label.setScaledContents(False)
        self.poster_label.setText("暂无封面")
        self.poster_label.setStyleSheet("""
            QLabel {
                background-color: #3C3C3E;
                border-radius: 8px;
                color: #999999;
                font-size: 12px;
            }
        """)

    def ensure_placeholder(self):
        """如果当前既无 pixmap 也无文字，显示占位，避免卡片变成不可见的空白格"""
        pl = self.poster_label
        if (not pl.pixmap() or pl.pixmap().isNull()) and not pl.text():
            self.load_placeholder()

    def set_cover_pixmap(self, pixmap: QPixmap):
        if not pixmap.isNull():
            # 开启缩放填充：卡片缩放后已缓存 pixmap 的像素尺寸可能与 label 不一致，
            # 由 Qt 自动拉伸适配，避免每次缩放都清缓存重下载。
            self.poster_label.setScaledContents(True)
            self.poster_label.setPixmap(pixmap)
        else:
            self.poster_label.setScaledContents(False)
            self.poster_label.setText("加载失败")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.game, self.mapToGlobal(event.pos()))
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.is_hovered = True
        self.setStyleSheet("""
            GameCard {
                border: 3px solid #007AFF;
                border-radius: 8px;
            }
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.setStyleSheet("")
        super().leaveEvent(event)
