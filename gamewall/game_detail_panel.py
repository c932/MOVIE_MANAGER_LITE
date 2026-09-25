"""
游戏详情面板
左侧：大封面 + 操作按钮；右侧：标题/元信息/评分/简介（可滚动）
"""
import logging

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
                             QScrollArea, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap, QCursor

from gamewall.game_models import Game
from gamewall.cover_loader import BatchCoverLoader
from utils.image_loader import ImageCache

logger = logging.getLogger(__name__)


class GameDetailPanel(QWidget):
    """
    游戏详情嵌入式面板（与电影墙 MovieDetailPanel 同一视觉规范）
    """

    launch_requested = pyqtSignal(str)      # 启动游戏 (exe 路径)
    download_requested = pyqtSignal(str)    # 打开下载链接 (url)
    open_folder_requested = pyqtSignal(str)  # 打开游戏目录

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_game = None
        self._cover_loader = None
        self._render_generation = 0
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("background-color: #FFFFFF;")
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.show_empty_state()

    def _clear_layout(self, layout=None):
        if layout is None:
            layout = self.main_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    # ── 状态视图 ──
    def show_empty_state(self):
        self._clear_layout()
        label = QLabel("👈 点击游戏封面查看详情")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("""
            QLabel { color: #999999; font-size: 18px; padding: 100px; }
        """)
        self.main_layout.addWidget(label)

    def show_loading_state(self, title: str = ""):
        self._clear_layout()
        text = "正在加载详情..."
        if title:
            text = f"正在加载《{title}》详情..."
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("""
            QLabel { color: #6C757D; font-size: 16px; padding: 60px; }
        """)
        self.main_layout.addWidget(label)

    # ── 详情渲染 ──
    def show_game(self, game: Game):
        self._render_generation += 1
        generation = self._render_generation
        self.current_game = game
        self._clear_layout()

        # === 左侧封面区域 ===
        left_widget = QWidget()
        left_widget.setFixedWidth(320)
        left_widget.setStyleSheet("background-color: #F8F9FA;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        cover_label = QLabel()
        cover_label.setFixedSize(280, 420)
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_label.setStyleSheet("""
            QLabel {
                background-color: #E9ECEF;
                border-radius: 8px;
                color: #999999;
            }
        """)
        self._load_cover_async(game, cover_label, generation)
        left_layout.addWidget(cover_label)

        # 操作按钮区
        if game.installed and game.installed_exe:
            launch_btn = QPushButton("▶ 启动游戏")
            launch_btn.setFixedHeight(44)
            launch_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            launch_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
            launch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28A745;
                    color: white;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover { background-color: #218838; }
            """)
            launch_btn.clicked.connect(
                lambda checked, exe=game.installed_exe: self.launch_requested.emit(exe))
            left_layout.addWidget(launch_btn)

            folder_btn = QPushButton("📁 打开游戏目录")
            folder_btn.setFixedHeight(36)
            folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            folder_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6C757D;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #5A6268; }
            """)
            import os
            folder_btn.clicked.connect(
                lambda checked, p=game.installed_exe: self.open_folder_requested.emit(os.path.dirname(p)))
            left_layout.addWidget(folder_btn)

        if game.quark_link:
            download_text = "🔗 打开下载链接（夸克网盘）"
            download_btn = QPushButton(download_text)
            download_btn.setFixedHeight(40)
            download_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            download_btn.setFont(QFont("Microsoft YaHei", 11))
            download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #007AFF;
                    color: white;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover { background-color: #0066D6; }
            """)
            download_btn.clicked.connect(
                lambda checked, url=game.quark_link: self.download_requested.emit(url))
            left_layout.addWidget(download_btn)

        left_layout.addStretch()
        self.main_layout.addWidget(left_widget)

        # === 右侧信息区域（滚动）===
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setObjectName("RightContent")

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(25, 20, 25, 20)
        content_layout.setSpacing(12)

        # 标题行（含 3A 标记）
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_label = QLabel(game.display_title())
        title_label.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #212529;")
        title_label.setWordWrap(True)
        title_row.addWidget(title_label, 1)
        if game.is_aaa:
            aaa_label = QLabel("3A 大作")
            aaa_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
            aaa_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(212, 160, 23, 0.9);
                    color: white;
                    padding: 4px 10px;
                    border-radius: 6px;
                }
            """)
            title_row.addWidget(aaa_label)
        content_layout.addLayout(title_row)

        classification_label = QLabel(f"3A 分类：{game.aaa_source_label}")
        classification_label.setFont(QFont("Microsoft YaHei", 10))
        classification_label.setStyleSheet("color: #8A6D1D;")
        classification_label.setWordWrap(True)
        content_layout.addWidget(classification_label)

        # 元信息行
        meta_parts = []
        if game.release_date:
            meta_parts.append(f"发售: {game.release_date}")
        if game.developer:
            meta_parts.append(f"开发商: {game.developer}")
        if game.genres:
            meta_parts.append(" / ".join(game.genres))
        if game.size_text:
            meta_parts.append(f"大小: {game.size_text}")
        if game.version:
            meta_parts.append(f"版本: {game.version}")
        if game.update_date:
            meta_parts.append(f"更新: {game.update_date}")
        if game.installed:
            meta_parts.append("● 已安装")
        meta_label = QLabel("  ·  ".join(meta_parts) if meta_parts else "暂无信息")
        meta_label.setFont(QFont("Microsoft YaHei", 11))
        meta_label.setStyleSheet("color: #6C757D;")
        meta_label.setWordWrap(True)
        content_layout.addWidget(meta_label)

        content_layout.addWidget(self._create_separator())

        # 评分区
        ratings = self._collect_ratings(game)
        if ratings:
            content_layout.addWidget(self._create_ratings_section(ratings))
            content_layout.addWidget(self._create_separator())

        # 简介区
        if game.description:
            desc_title = QLabel("📖 游戏简介")
            desc_title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
            desc_title.setStyleSheet("color: #495057;")
            content_layout.addWidget(desc_title)

            desc_text = game.description
            if len(desc_text) > 2000:
                desc_text = desc_text[:2000].rstrip() + "..."
            desc_label = QLabel(desc_text)
            desc_label.setFont(QFont("Microsoft YaHei", 11))
            desc_label.setStyleSheet("color: #6C757D; line-height: 1.6;")
            desc_label.setWordWrap(True)
            content_layout.addWidget(desc_label)

        content_layout.addStretch()
        right_scroll.setWidget(content_widget)
        self.main_layout.addWidget(right_scroll)

    def _collect_ratings(self, game: Game) -> list:
        """收集评分卡数据 [(label, value_text, bg, fg), ...]"""
        ratings = []
        if game.steam_positive_pct > 0:
            desc = self._steam_desc(game.steam_positive_pct)
            ratings.append((f"Steam 好评率\n{desc}", f"{game.steam_positive_pct:.0f}%",
                            "#E8F4FD", "#1B6EC2"))
        if game.metacritic > 0:
            ratings.append(("Metacritic", f"{game.metacritic:.0f}", "#F3F6F4", "#2C3E50"))
        if game.ign_score > 0:
            ratings.append(("IGN", f"{game.ign_score:.1f}", "#FFF3F0", "#D6402C"))
        if game.gamersky_score > 0:
            ratings.append(("游民星空", f"{game.gamersky_score:.1f}", "#FDF6E3", "#B8860B"))
        return ratings

    @staticmethod
    def _steam_desc(pct: float) -> str:
        if pct >= 95: return "好评如潮"
        if pct >= 80: return "特别好评"
        if pct >= 70: return "多半好评"
        if pct >= 40: return "褒贬不一"
        return "差评如潮"

    def _create_ratings_section(self, ratings: list) -> QWidget:
        section = QWidget()
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for label_text, value_text, bg, fg in ratings:
            card = QWidget()
            card.setFixedSize(110, 74)
            card.setStyleSheet(f"""
                QWidget {{ background-color: {bg}; border-radius: 8px; }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(2)
            card_layout.setContentsMargins(6, 8, 6, 6)

            logo = QLabel(label_text)
            logo.setFont(QFont("Microsoft YaHei", 8, QFont.Weight.Bold))
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setStyleSheet("color: #6C757D; background: transparent;")
            card_layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)

            value_label = QLabel(value_text)
            value_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
            value_label.setStyleSheet(f"color: {fg}; background: transparent;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(value_label)

            layout.addWidget(card)
        layout.addStretch()
        return section

    @staticmethod
    def _create_separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #E9ECEF; border: none;")
        return line

    def _load_cover_async(self, game: Game, cover_label: QLabel, generation: int):
        """异步加载封面（竖版优先、头图兜底），快速切换时丢弃过期回调"""
        urls = game.get_cover_urls()
        if not urls:
            cover_label.setText("暂无封面")
            return

        image_cache = ImageCache()
        for url in urls:
            if image_cache.has(url):
                pixmap = image_cache.get(url)
                if not pixmap.isNull():
                    cover_label.setPixmap(pixmap)
                    cover_label.setScaledContents(True)
                    return

        if self._cover_loader is not None and self._cover_loader.isRunning():
            self._cover_loader.cancel()
            # 等待旧线程退出再起新线程：cancel() 只在 URL 尝试间隙生效，
            # 不 wait 会同时存在多个下载线程抢资源并可能 emit 过期 batch_loaded。
            self._cover_loader.wait(2000)

        loader = BatchCoverLoader([(urls, 280, 420)], self)
        self._cover_loader = loader

        def _on_batch(items, _game=game, _label=cover_label, _gen=generation):
            if generation != self._render_generation:
                return
            if not self.current_game or self.current_game.norm_key != _game.norm_key:
                return
            cache = ImageCache()
            for url, image in items:
                pixmap = QPixmap.fromImage(image) if not isinstance(image, QPixmap) else image
                if not pixmap.isNull():
                    cache.set(url, pixmap)
                    _label.setPixmap(pixmap)
                    _label.setScaledContents(True)
                    return
            _label.setText("暂无封面")

        loader.batch_loaded.connect(_on_batch)
        loader.start()
