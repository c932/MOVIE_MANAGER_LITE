"""
游戏墙主窗口
三栏布局：左侧筛选栏、中间海报墙、右侧详情面板（参照 ui/main_window.py 视觉规范）
"""
import logging
import os
import subprocess
import time
import webbrowser
from collections import deque

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QScrollArea, QGridLayout, QLineEdit, QSlider,
    QProgressBar, QSplitter, QFrame, QSizePolicy, QMenu,
    QApplication, QMessageBox, QFileDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QFont, QFontMetrics, QCursor, QPixmap

from utils.config_manager import ConfigManager
from utils.app_paths import DATA_DIR
from utils.image_loader import ImageCache, get_poster_cache_manager
from ui.flow_layout import FlowWidget
from gamewall.game_models import Game
from gamewall.game_cache import GameCacheManager
from gamewall.aaa_classifier import build_auto_evidence, classify_aaa
from gamewall.llm_classifier import classify_with_llm
from gamewall import steam_client
from gamewall.game_card import GameCard
from gamewall.game_detail_panel import GameDetailPanel
from gamewall.cover_loader import BatchCoverLoader
from gamewall.enrichment_worker import EnrichmentWorker
from gamewall.local_scanner import InstalledGameScanner
from gamewall.name_utils import normalize_name
from gamewall.settings_dialog import GameSettingsDialog

logger = logging.getLogger(__name__)


class ExcelImportWorker(QThread):
    """后台 Excel 导入线程。当文件消失或读取失败时回退缓存。"""
    import_finished = pyqtSignal(list, object)
    import_error = pyqtSignal(str)
    diff_checked = pyqtSignal(list, object)
    diff_error = pyqtSignal(str)

    def __init__(self, excel_path, cache, parent=None):
        super().__init__(parent)
        self.excel_path = excel_path
        self.cache = cache

    def run(self):
        try:
            from gamewall.excel_parser import parse_excel, diff_games
            games, meta = parse_excel(self.excel_path)
            self.diff_checked.emit(games, meta)
        except Exception as e:
            logger.exception("Excel 导入失败")
            self.diff_error.emit(str(e))


class LLMClassifyWorker(QThread):
    """后台 LLM 3A 判定线程：逐个调用 OpenAI 兼容 API，结果经信号交回主线程。"""
    game_verdict = pyqtSignal(str, object)   # (norm_key, verdict dict | None)
    finished_with = pyqtSignal(str)          # 汇总信息

    def __init__(self, games, base_url: str, api_key: str, model: str, parent=None):
        super().__init__(parent)
        self._games = list(games)
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        done = 0
        for game in self._games:
            if self._cancelled:
                break
            try:
                verdict = classify_with_llm(
                    game, self._base_url, self._api_key, self._model)
            except Exception as e:
                logger.warning(f"LLM 判定异常 {game.norm_key}: {e}")
                verdict = None
            if verdict is not None:
                self.game_verdict.emit(game.norm_key, verdict)
            done += 1
        self.finished_with.emit(f"LLM 判定完成：{done} 款游戏")


class GameMainWindow(QMainWindow):
    """游戏墙主窗口：左侧筛选栏 + 中间海报墙 + 右侧详情面板"""

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.cache = GameCacheManager()
        self.all_games = []
        self.filtered_games = []
        self.movie_cards = []
        self.search_keyword = ""
        self.selected_genres = set()
        self.min_rating = 0
        self.no_rating_only = False
        self.aaa_only = False
        self.installed_only = False
        self.filter_years = set()
        self.filter_developers = set()
        self.sort_mode = "update"
        self.poster_scale = self.config.get_value("poster_scale", 100) / 100.0

        self._card_pool = {}
        self._cover_loader = None
        self._cover_load_generation = 0
        self._visible_loader_running = False
        self._cover_retry_timer = QTimer(self)
        self._cover_retry_timer.setSingleShot(True)
        self._cover_retry_timer.timeout.connect(self._load_visible_posters)

        self._developer_options_refresh_scheduled = False
        self._enrichment_worker = None
        self._local_scanner = None
        self._games_by_key = {}
        self._enriched_save_counter = 0

        self.init_ui()
        self._startup_load()

    def init_ui(self):
        self.setWindowTitle("Local Game Wall - 本地游戏墙")
        self.setMinimumSize(1200, 720)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter_style = """
            QSplitter::handle { background-color: #E0E0E0; }
            QSplitter::handle:hover { background-color: #007AFF; }
        """
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setStyleSheet(splitter_style)
        self.main_splitter.setChildrenCollapsible(False)

        self.filter_panel = self._create_filter_panel()
        self.main_splitter.addWidget(self.filter_panel)
        self.main_splitter.setCollapsible(0, False)

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.detail_panel = GameDetailPanel()
        self.detail_panel.setMinimumHeight(240)
        self.detail_panel.launch_requested.connect(self._launch_game)
        self.detail_panel.download_requested.connect(self._open_download_link)
        self.detail_panel.open_folder_requested.connect(self._open_folder)

        poster_container = QWidget()
        poster_layout = QVBoxLayout(poster_container)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(0)

        toolbar = self._create_toolbar()
        poster_layout.addWidget(toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("PosterScrollArea")

        self.poster_wall_widget = QWidget()
        self.poster_wall_widget.setObjectName("PosterWall")
        self.poster_wall_layout = QGridLayout(self.poster_wall_widget)
        self.poster_wall_layout.setSpacing(0)
        self.poster_wall_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area.setWidget(self.poster_wall_widget)
        poster_layout.addWidget(self.scroll_area)

        self.right_splitter.addWidget(self.detail_panel)
        self.right_splitter.addWidget(poster_container)
        self.right_splitter.setStretchFactor(0, 0)  # 详情不自动拉伸
        self.right_splitter.setStretchFactor(1, 1)  # 海报墙占剩余空间
        self.right_splitter.setCollapsible(0, False)
        self.right_splitter.setCollapsible(1, False)

        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.main_splitter)

        saved_sizes = self.config.get_splitter_sizes()
        if isinstance(saved_sizes, dict):
            left = saved_sizes.get("main", None)
            right = saved_sizes.get("right", None)
            if isinstance(left, (list, tuple)) and len(left) == 2 and all(isinstance(x, int) for x in left):
                self.main_splitter.setSizes(list(left))
            if isinstance(right, (list, tuple)) and len(right) == 2 and all(isinstance(x, int) for x in right):
                self.right_splitter.setSizes(list(right))
            else:
                self.right_splitter.setSizes([450, 450])

    def _create_filter_panel(self):
        """左侧筛选面板，筛选内容可滚动而重置操作始终可见。"""
        sidebar = QWidget()
        sidebar.setObjectName("GameFilterSidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(400)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(6)

        self.filter_content = QWidget()
        self.filter_content.setObjectName("FilterPanel")
        layout = QVBoxLayout(self.filter_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QLabel("🎮 游戏筛选")
        title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1A1A1A; border: none;")
        layout.addWidget(title_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #D0D0D0; border: none;")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        genre_label = QLabel("类型")
        genre_label.setStyleSheet("color: #333333;")
        layout.addWidget(genre_label)
        self.genre_filter_widget = FlowWidget(margin=0, spacing=4)
        self.genre_filter_layout = self.genre_filter_widget.flow_layout
        layout.addWidget(self.genre_filter_widget)

        rating_label = QLabel("Steam 评分")
        rating_label.setStyleSheet("color: #333333;")
        layout.addWidget(rating_label)
        rating_widget = FlowWidget(margin=0, spacing=4)
        self.rating_filter_layout = rating_widget.flow_layout
        self._rating_buttons = []
        for text, value in [("全部", 0), ("> 50%", 50), ("> 75%", 75), ("> 90%", 90), ("无评分", -1)]:
            btn = self._create_filter_button(text, value == 0)
            btn.clicked.connect(lambda checked, v=value, b=btn: self._on_rating_filter_changed(v, b))
            self.rating_filter_layout.addWidget(btn)
            self._rating_buttons.append(btn)
        layout.addWidget(rating_widget)

        feature_label = QLabel("特性")
        feature_label.setStyleSheet("color: #333333;")
        layout.addWidget(feature_label)
        feature_widget = FlowWidget(margin=0, spacing=4)
        self.feature_filter_layout = feature_widget.flow_layout
        self.aaa_btn = self._create_filter_button("3A大作", False)
        self.aaa_btn.clicked.connect(self._on_aaa_filter_toggled)
        self.feature_filter_layout.addWidget(self.aaa_btn)
        self.installed_btn = self._create_filter_button("已安装", False)
        self.installed_btn.clicked.connect(self._on_installed_filter_toggled)
        self.feature_filter_layout.addWidget(self.installed_btn)
        layout.addWidget(feature_widget)

        year_label = QLabel("年份")
        year_label.setStyleSheet("color: #333333;")
        layout.addWidget(year_label)
        self.year_filter_widget = FlowWidget(margin=0, spacing=4)
        self.year_filter_layout = self.year_filter_widget.flow_layout
        layout.addWidget(self.year_filter_widget)

        developer_label = QLabel("制作公司")
        developer_label.setStyleSheet("color: #333333;")
        layout.addWidget(developer_label)
        self.developer_filter_widget = FlowWidget(margin=0, spacing=4)
        self.developer_filter_layout = self.developer_filter_widget.flow_layout
        layout.addWidget(self.developer_filter_widget)

        layout.addStretch()

        self.filter_scroll_area = QScrollArea()
        self.filter_scroll_area.setObjectName("FilterScrollArea")
        self.filter_scroll_area.setWidget(self.filter_content)
        self.filter_scroll_area.setWidgetResizable(True)
        self.filter_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.filter_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.filter_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.filter_scroll_area.viewport().installEventFilter(self)
        sidebar_layout.addWidget(self.filter_scroll_area)

        footer = QWidget()
        footer.setObjectName("GameFilterFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        self.reset_button = QPushButton("🔄 重置筛选")
        self.reset_button.setObjectName("ResetButton")
        self.reset_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.reset_button.clicked.connect(self.reset_filters)
        self.reset_button.setStyleSheet("""
            QPushButton {
                background-color: #F5F5F5; color: #333333; border: 1px solid #E0E0E0;
                border-radius: 6px; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #E8E8E8; }
        """)
        footer_layout.addWidget(self.reset_button)
        sidebar_layout.addWidget(footer)

        QTimer.singleShot(0, self._reflow_filter_buttons)
        return sidebar

    @staticmethod
    def _clear_filter_button_layout(flow_layout):
        """清空筛选按钮布局（供年份/制作公司重建时复用）"""
        while flow_layout.count():
            item = flow_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def generate_year_options(self):
        """从发售日期重建年份筛选按钮（新→旧，多选）"""
        years = sorted({
            g.release_date[:4] for g in self.all_games
            if g.release_date and len(g.release_date) >= 4
        }, reverse=True)
        self._clear_filter_button_layout(self.year_filter_layout)
        if not years:
            hint = QLabel("（无年份数据）")
            hint.setStyleSheet("color: #999999; font-size: 11px;")
            self.year_filter_layout.addWidget(hint)
            return
        for year in years[:30]:
            btn = self._create_filter_button(year, False)
            btn.setChecked(year in self.filter_years)
            btn.clicked.connect(lambda checked, y=year: self._on_year_filter_toggled(y, checked))
            self.year_filter_layout.addWidget(btn)
        QTimer.singleShot(0, self._reflow_filter_buttons)

    def generate_developer_options(self):
        """从补全数据重建制作公司筛选按钮（按游戏数排序，多选）"""
        from collections import Counter
        counter = Counter()
        for g in self.all_games:
            if g.developer:
                counter[g.developer] += 1
        developers = [d for d, _ in counter.most_common()]
        self._clear_filter_button_layout(self.developer_filter_layout)
        if not developers:
            hint = QLabel("（待评分数据补全后可用）")
            hint.setStyleSheet("color: #999999; font-size: 11px;")
            self.developer_filter_layout.addWidget(hint)
            return
        for developer in developers[:25]:
            btn = self._create_filter_button(developer, False)
            btn.setChecked(developer in self.filter_developers)
            btn.clicked.connect(lambda checked, d=developer: self._on_developer_filter_toggled(d, checked))
            self.developer_filter_layout.addWidget(btn)
        QTimer.singleShot(0, self._reflow_filter_buttons)

    def _schedule_developer_options_refresh(self):
        if not self._developer_options_refresh_scheduled:
            self._developer_options_refresh_scheduled = True
            QTimer.singleShot(0, self._refresh_developer_options)

    def _refresh_developer_options(self):
        self._developer_options_refresh_scheduled = False
        self.generate_developer_options()

    def _on_year_filter_toggled(self, year, checked):
        if checked:
            self.filter_years.add(year)
        else:
            self.filter_years.discard(year)
        self.apply_filters()

    def _on_developer_filter_toggled(self, developer, checked):
        if checked:
            self.filter_developers.add(developer)
        else:
            self.filter_developers.discard(developer)
        self.apply_filters()

    def _create_filter_button(self, text: str, is_all: bool = True):
        """创建过滤按钮（与电影墙同款样式）"""
        btn = QPushButton(text)
        btn.setProperty("filter_label", text)
        btn.setToolTip(text)
        btn.setCheckable(True)
        btn.setFont(QFont("Microsoft YaHei", 10))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if is_all:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #E74C3C; color: white;
                    border: none; border-radius: 4px; padding: 6px 14px; font-size: 11px;
                }
                QPushButton:hover { background-color: #C0392B; }
                QPushButton:checked { background-color: #A93226; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #F5F5F5; color: #333333;
                    border: 1px solid #E0E0E0; border-radius: 4px;
                    padding: 6px 14px; font-size: 11px;
                }
                QPushButton:hover { background-color: #E8E8E8; }
                QPushButton:checked {
                    background-color: #007AFF; color: white; border-color: #007AFF;
                }
            """)
        return btn

    @staticmethod
    def _wrap_filter_label(text: str, max_width: int):
        font_metrics = QFontMetrics(QApplication.font())
        lines = []
        for line in text.split("\n"):
            current = ""
            for ch in line:
                candidate = current + ch
                if font_metrics.horizontalAdvance(candidate) > max_width and current:
                    lines.append(current)
                    current = ch
                else:
                    current = candidate
            if current:
                lines.append(current)
        return "\n".join(lines)

    def _reflow_filter_buttons(self):
        if not hasattr(self, "filter_scroll_area"):
            return
        viewport_width = self.filter_scroll_area.viewport().width()
        content_width = max(viewport_width - 16, 120)
        text_width = content_width - 28

        for btn in self.filter_content.findChildren(QPushButton):
            if btn.property("filter_label"):
                btn.setMaximumWidth(content_width)
                label = btn.text()
                btn.setText(self._wrap_filter_label(label, text_width))
                btn.updateGeometry()

        for flow_layout in (getattr(self, n, None) for n in
                            ["genre_filter_layout", "rating_filter_layout", "feature_filter_layout",
                             "year_filter_layout", "developer_filter_layout"]):
            if flow_layout is not None:
                flow_layout.invalidate()
                flow_layout.activate()
                parent_widget = flow_layout.parentWidget()
                if parent_widget and isinstance(parent_widget, FlowWidget):
                    h = flow_layout.heightForWidth(parent_widget.width())
                    if h > 0:
                        parent_widget.setMinimumHeight(h)
                        parent_widget.updateGeometry()
        self.filter_content.updateGeometry()

    def eventFilter(self, watched, event):
        if hasattr(self, "filter_scroll_area") and watched is self.filter_scroll_area.viewport():
            if event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self._reflow_filter_buttons)
        return super().eventFilter(watched, event)

    def _create_toolbar(self):
        """顶部工具栏（状态 + 搜索 + 排序 + 缩放 + 设置）"""
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(8)

        self.status_label = QLabel("正在加载游戏库...")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        self.status_label.setStyleSheet("color: #6C757D;")
        toolbar_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.hide()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #DEE2E6; border-radius: 4px;
                background-color: #F8F9FA; text-align: center; font-size: 10px;
            }
            QProgressBar::chunk { background-color: #007AFF; border-radius: 3px; }
        """)
        toolbar_layout.addWidget(self.progress_bar)
        toolbar_layout.addSpacing(8)

        search_label = QLabel("🔍 搜索:")
        search_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("游戏名...")
        self.search_input.setFixedHeight(28)
        self.search_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CED4DA; border-radius: 6px;
                padding: 4px 10px; font-size: 11px; background-color: white;
            }
            QLineEdit:focus { border-color: #007AFF; background-color: #F0F8FF; }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_input)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(24, 24)
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.setToolTip("清除搜索")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D; color: white; border: none;
                border-radius: 6px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #5A6268; }
        """)
        clear_btn.clicked.connect(self._clear_search)
        toolbar_layout.addWidget(clear_btn)
        toolbar_layout.addStretch()

        sort_label = QLabel("📊 排序:")
        sort_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(sort_label)
        for text, mode in [("更新", "update"), ("评分", "rating"), ("发售", "release"), ("名称", "name")]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(self.sort_mode == mode)
            btn.setObjectName("SortButton")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #F5F5F5; color: #333333;
                    border: 1px solid #E0E0E0; border-radius: 4px; padding: 4px 8px;
                }
                QPushButton:hover { background-color: #E8E8E8; }
                QPushButton:checked {
                    background-color: #007AFF; color: white; border-color: #007AFF;
                }
            """)
            btn.clicked.connect(lambda checked, m=mode, b=btn: self._on_sort_changed(m, b))
            toolbar_layout.addWidget(btn)

        toolbar_layout.addSpacing(16)

        scale_label = QLabel("🔍 缩放:")
        scale_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        toolbar_layout.addWidget(scale_label)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setObjectName("scale_slider")
        self.scale_slider.setMinimum(50)
        self.scale_slider.setMaximum(200)
        self.scale_slider.setValue(int(self.poster_scale * 100))
        self.scale_slider.setFixedWidth(120)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        toolbar_layout.addWidget(self.scale_slider)

        self.scale_value_label = QLabel(f"{int(self.poster_scale * 100)}%")
        self.scale_value_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.scale_value_label.setStyleSheet("color: #495057; font-size: 12px; font-weight: bold;")
        toolbar_layout.addWidget(self.scale_value_label)
        toolbar_layout.addStretch()

        import_btn = QPushButton("📥 导入 Excel 更新")
        import_btn.setToolTip("导入 Excel 更新")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF; color: white; border: none;
                border-radius: 6px; padding: 4px 14px;
            }
            QPushButton:hover { background-color: #0066D6; }
        """)
        import_btn.clicked.connect(self._import_excel_dialog)
        toolbar_layout.addWidget(import_btn)

        settings_btn = QPushButton("⚙ 设置")
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #868E96; color: white; border: none;
                border-radius: 6px; padding: 4px 14px;
            }
            QPushButton:hover { background-color: #6C757D; }
        """)
        settings_btn.clicked.connect(self._open_settings)
        toolbar_layout.addWidget(settings_btn)

        return toolbar

    def _startup_load(self):
        """缓存优先：立即用缓存库上墙，再后台导入 Excel 校准"""
        excel_path = self.config.get_value("excel_path", "")
        if excel_path:
            setattr(self, "_loaded_excel_path", excel_path)
        cached_games = self.cache.load_games_from_cache()
        if cached_games:
            self.all_games = list(cached_games)
            self._refresh_auto_aaa_classifications()
            self.cache.save()
            self.generate_genre_options()
            self.generate_year_options()
            self.generate_developer_options()
            self.apply_filters()
            self.status_label.setText(f"已从缓存加载 {len(self.all_games)} 款游戏，正在后台同步 Excel…")
        else:
            self._show_empty_state()

        if not excel_path:
            self.status_label.setText("请先在设置中选择游戏 Excel 文件")
            return

        self._excel_worker = ExcelImportWorker(excel_path, self.cache)
        self._excel_worker.import_finished.connect(self._on_excel_import_finished)
        self._excel_worker.import_error.connect(self._on_excel_import_error)
        self._excel_worker.start()

    def _refresh_auto_aaa_classifications(self, games=None):
        """从游戏已有数据（Steam 资料/评价/资源体积/内置大厂名录）推导证据并重算分类。"""
        if games is None:
            games = self.all_games
        for game in games:
            evidence = build_auto_evidence(game)
            game.aaa_evidence = evidence
            result = classify_aaa(evidence)
            game.aaa_score = result.get("score", 0)
            game.aaa_tier = result.get("tier", "INDIE")
            game.aaa_rule_version = result.get("rule_version", "")
            self.cache.set_auto_aaa_classification(game.norm_key, result, evidence)

    def _on_excel_import_finished(self, games, meta):
        previous_games = self.all_games
        try:
            self.all_games = games
            for game in self.all_games:
                self.cache.apply_to_game(game)
            self._refresh_auto_aaa_classifications()
            self.cache.snapshot_games(self.all_games)
            self.cache.save()
            setattr(self, "_loaded_excel_path", meta.get("path", ""))
            setattr(self, "_excel_mtime", meta.get("mtime"))
            self.generate_genre_options()
            self.generate_year_options()
            self.generate_developer_options()
            self.apply_filters()
            logger.info(f"游戏库加载完成: {len(games)} 款 (表头行 {meta.get('header_row', '?')})")
        except Exception:
            logger.exception("处理导入结果失败")
            try:
                self.all_games = previous_games
                if previous_games:
                    self.generate_genre_options()
                    self.generate_year_options()
                    self.generate_developer_options()
                    self.apply_filters()
                else:
                    self._show_empty_state()
                self.status_label.setText(f"已保留 {len(previous_games)} 款游戏，导入更新未应用")
            except Exception:
                logger.exception("恢复先前游戏库失败")
                self._show_empty_state()
                self.status_label.setText("游戏库导入处理失败")
        finally:
            self._start_background_tasks_safely()

    def _on_excel_import_error(self, error):
        cached_games = self.cache.load_games_from_cache()
        if cached_games:
            self.all_games = list(cached_games)
            self._refresh_auto_aaa_classifications()
            self.cache.save()
            self.generate_genre_options()
            self.generate_year_options()
            self.generate_developer_options()
            self.apply_filters()
            self.status_label.setText(f"Excel 不可用，已从缓存加载 {len(self.all_games)} 款游戏")
        else:
            self._show_empty_state()
        logger.error(f"导入失败: {error}")
        self._start_background_tasks_safely()

    def _on_search_changed(self, text):
        if not hasattr(self, "_search_debounce_timer"):
            self._search_debounce_timer = QTimer(self)
            self._search_debounce_timer.setSingleShot(True)
            self._search_debounce_timer.timeout.connect(self._apply_search)
        self._search_debounce_timer.start(300)

    def _apply_search(self):
        self.search_keyword = self.search_input.text().strip().lower()
        self.apply_filters()

    def _clear_search(self):
        self.search_input.clear()
        self.search_keyword = ""
        self.apply_filters()

    def _on_rating_filter_changed(self, value, btn):
        for b in self._rating_buttons:
            b.setChecked(b is btn)
        if value == -1:
            self.min_rating = 0
            self.no_rating_only = True
        else:
            self.min_rating = value
            self.no_rating_only = False
        self.apply_filters()

    def _on_aaa_filter_toggled(self):
        self.aaa_only = self.aaa_btn.isChecked()
        self.apply_filters()

    def _on_installed_filter_toggled(self):
        self.installed_only = self.installed_btn.isChecked()
        self.apply_filters()

    def generate_genre_options(self):
        """从补全后的游戏类型重建类型筛选按钮（按数量排序）"""
        while self.genre_filter_layout.count():
            item = self.genre_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        from collections import Counter
        counter = Counter()
        for game in self.all_games:
            for genre in (game.genres or []):
                counter[genre] += 1
        if not counter:
            genre_label = QLabel("（待评分数据补全后可用）")
            genre_label.setStyleSheet("color: #999999; font-size: 11px;")
            self.genre_filter_layout.addWidget(genre_label)
            return
        top_genres = [genre for genre, _ in counter.most_common()]
        for genre in top_genres:
            btn = self._create_filter_button(genre, False)
            btn.clicked.connect(lambda checked, g=genre, b=btn: self._on_genre_filter_changed(g, b))
            self.genre_filter_layout.addWidget(btn)
        QTimer.singleShot(0, self._reflow_filter_buttons)

    def _on_genre_filter_changed(self, genre, btn):
        if genre in self.selected_genres:
            self.selected_genres.discard(genre)
            btn.setChecked(False)
        else:
            self.selected_genres.add(genre)
            btn.setChecked(True)
        self.apply_filters()

    def apply_filters(self):
        """内存筛选（与电影墙同模式）"""
        filtered = []
        for game in self.all_games:
            if self.search_keyword:
                haystacks = [game.title_cn.lower(), game.title_en.lower(), (game.steam_name or "").lower()]
                if not any(self.search_keyword in h for h in haystacks):
                    continue
            if self.selected_genres:
                if not any(g in self.selected_genres for g in (game.genres or [])):
                    continue
            if self.no_rating_only:
                if game.steam_positive_pct > 0:
                    continue
            elif self.min_rating > 0:
                if game.steam_positive_pct <= 0 or game.steam_positive_pct < self.min_rating:
                    continue
            if self.aaa_only and not game.is_aaa:
                continue
            if self.installed_only and not game.installed:
                continue
            if self.filter_years:
                year = (game.release_date or "")[:4]
                if year not in self.filter_years:
                    continue
            if self.filter_developers:
                if game.developer not in self.filter_developers:
                    continue
            filtered.append(game)
        self.filtered_games = filtered
        total = len(self.all_games)
        shown = len(filtered)
        self.status_label.setText(f"显示 {shown} / {total} 款游戏")
        self.refresh_poster_wall()

    def reset_filters(self):
        self.selected_genres.clear()
        self.min_rating = 0
        self.no_rating_only = False
        self.aaa_only = False
        self.installed_only = False
        self.search_keyword = ""
        self.search_input.clear()
        self.filter_years.clear()
        self.filter_developers.clear()
        for b in self._rating_buttons:
            b.setChecked(b.text() == "全部")
        self.aaa_btn.setChecked(False)
        self.installed_btn.setChecked(False)
        self.generate_genre_options()
        self.generate_year_options()
        self.generate_developer_options()
        self.apply_filters()

    def _on_sort_changed(self, mode, clicked_btn=None):
        """排序模式改变（参照电影墙实现：用按钮父控件定位 toolbar）"""
        self.sort_mode = mode
        if clicked_btn:
            toolbar = clicked_btn.parent()
            if toolbar:
                for b in toolbar.findChildren(QPushButton):
                    if b.objectName() == "SortButton":
                        b.setChecked(False)
                clicked_btn.setChecked(True)
        self.refresh_poster_wall()

    def _on_scale_changed(self, value):
        self.poster_scale = value / 100.0
        self.scale_value_label.setText(f"{value}%")
        if not hasattr(self, "_scale_debounce_timer"):
            self._scale_debounce_timer = QTimer(self)
            self._scale_debounce_timer.setSingleShot(True)
            self._scale_debounce_timer.timeout.connect(self._apply_scale_change)
        self._scale_debounce_timer.start(200)

    def _apply_scale_change(self):
        self.config.set_value("poster_scale", int(self.poster_scale * 100))
        self.config.save_config()
        # 不清空 ImageCache：已缓存封面由 QLabel.setScaledContents 自动适配新尺寸
        self.refresh_poster_wall()

    def _apply_sorting(self, games):
        if self.sort_mode == "rating":
            return sorted(games, key=lambda g: g.get_rating_value(), reverse=True)
        elif self.sort_mode == "release":
            return sorted(games, key=lambda g: g.release_date or "0000-00-00", reverse=True)
        elif self.sort_mode == "name":
            return sorted(games, key=lambda g: g.display_title())
        else:  # update（默认，Excel 已按更新日期排序，保持原序）
            return games

    def _prune_card_pool(self, kept_keys):
        """淘汰卡片池中不再属于当前游戏库的卡片，避免池无上限增长。

        在 Excel 重新导入替换 all_games 后调用。仅清理确实移除的游戏卡片，
        保留仍存在的卡片以复用。
        """
        stale_keys = [k for k in self._card_pool if k not in kept_keys]
        if not stale_keys:
            return
        for key in stale_keys:
            card = self._card_pool.pop(key)
            self.poster_wall_layout.removeWidget(card)
            card.deleteLater()
        logger.info(f"卡片池淘汰 {len(stale_keys)} 张陈旧卡片，池剩余 {len(self._card_pool)} 张")

    def refresh_poster_wall(self):
        """刷新海报墙 - 卡片池复用模式"""
        self._cover_load_generation += 1
        if self._cover_loader is not None and self._cover_loader.isRunning():
            self._cover_loader.cancel()
        self._cover_loader = None
        self._visible_loader_running = False
        self._cover_retry_timer.stop()

        # 禁止中间重绘：布局清空 + 逐个 addWidget 会触发大量中间脏区域
        self.setUpdatesEnabled(False)
        try:
            self._do_refresh_poster_wall()
        finally:
            self.setUpdatesEnabled(True)

    def _do_refresh_poster_wall(self):
        pool_widgets = set(self._card_pool.values())
        while self.poster_wall_layout.count():
            item = self.poster_wall_layout.takeAt(0)
            if item.widget() and item.widget() not in pool_widgets:
                item.widget().deleteLater()

        for r in range(min(self.poster_wall_layout.rowCount(), 2000)):
            self.poster_wall_layout.setRowStretch(r, 0)
        for c in range(min(self.poster_wall_layout.columnCount(), 2000)):
            self.poster_wall_layout.setColumnStretch(c, 0)
            self.poster_wall_layout.setColumnMinimumWidth(c, 0)

        if not self.filtered_games:
            self.movie_cards = []
            self._show_empty_state()
            return

        base_width, base_height = self.config.get_poster_size()
        poster_width = int(base_width * self.poster_scale)
        poster_height = int(base_height * self.poster_scale)

        size_changed = (
            poster_width != getattr(self, '_prev_poster_width', 0)
            or poster_height != getattr(self, '_prev_poster_height', 0)
        )
        self._prev_poster_width = poster_width
        self._prev_poster_height = poster_height

        wall_width = self.scroll_area.width() - 20
        columns = max(1, wall_width // poster_width)
        spacing = max(0, (wall_width - columns * poster_width) // columns)
        self.poster_wall_layout.setHorizontalSpacing(spacing)

        sorted_games = self._apply_sorting(self.filtered_games.copy())
        self._sorted_games = sorted_games
        self._poster_width = poster_width
        self._poster_height = poster_height
        self._columns = columns

        try:
            self.scroll_area.verticalScrollBar().valueChanged.connect(
                self._on_scroll_lazy_load, Qt.ConnectionType.UniqueConnection)
        except TypeError:
            pass

        visible_key_set = {g.norm_key for g in sorted_games}

        for key, card in self._card_pool.items():
            if key not in visible_key_set:
                card.hide()
                if size_changed:
                    self._resize_card(card, poster_width, poster_height)

        self.movie_cards = []
        seen_keys = set()
        for idx, game in enumerate(sorted_games):
            key = game.norm_key
            # 跳过重复 norm_key 的游戏：相同 game 被 addWidget 两次会让 QGridLayout
            # 留下空 cell（产生可见的空白间距）。每个 norm_key 只显示一次。
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if key not in self._card_pool:
                card = GameCard(game, poster_width, poster_height)
                card.clicked.connect(self.on_game_card_clicked)
                card.right_clicked.connect(self.on_game_card_right_clicked)
                self._reset_card_load_state(card)
                self._card_pool[key] = card
            else:
                card = self._card_pool[key]
                if size_changed:
                    self._resize_card(card, poster_width, poster_height)
                card.update_game_info(game)
                card.show()

            card.ensure_placeholder()

            row = idx // columns
            col = idx % columns
            self.poster_wall_layout.removeWidget(card)
            self.poster_wall_layout.addWidget(card, row, col)
            self.movie_cards.append(card)

        self.poster_wall_layout.setRowStretch(self.poster_wall_layout.rowCount(), 1)
        self.poster_wall_layout.setColumnStretch(columns, 1)
        self.poster_wall_layout.activate()

        QTimer.singleShot(50, self._load_visible_posters)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_initial_show_done", False):
            self._initial_show_done = True
            QTimer.singleShot(0, self.refresh_poster_wall)

    def resizeEvent(self, event):
        """窗口尺寸变化时按新视口宽度重排列数（防抖）"""
        super().resizeEvent(event)
        if (getattr(self, "_initial_show_done", False)
                and getattr(self, "filtered_games", None)):
            if not hasattr(self, "_resize_timer"):
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self.refresh_poster_wall)
            self._resize_timer.start(200)

    def _resize_card(self, card, w, h):
        card.setFixedSize(w, h)
        card.poster_width = w
        card.poster_height = h
        card._poster_loaded = False
        card._poster_loading = False
        card._poster_fail_count = 0
        card._poster_next_retry_at = 0.0
        card._relayout()

    @staticmethod
    def _reset_card_load_state(card):
        card._poster_loaded = False
        card._poster_loading = False
        card._poster_fail_count = 0
        card._poster_next_retry_at = 0.0

    def _show_empty_state(self):
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        icon_label = QLabel("🎮")
        icon_label.setFont(QFont("Microsoft YaHei", 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon_label)

        title_label = QLabel("暂无游戏")
        title_label.setFont(QFont("Microsoft YaHei", 22, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #333333;")
        empty_layout.addWidget(title_label)

        hint = "点击右上角「⚙ 设置」选择游戏 Excel 文件开始使用" \
            if not self.config.get_value("excel_path", "") else "当前筛选条件下没有游戏"
        hint_label = QLabel(hint)
        hint_label.setFont(QFont("Microsoft YaHei", 13))
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setStyleSheet("color: #999999;")
        empty_layout.addWidget(hint_label)

        pool_widgets = set(self._card_pool.values())
        while self.poster_wall_layout.count():
            item = self.poster_wall_layout.takeAt(0)
            w = item.widget()
            if w and w not in pool_widgets:
                w.deleteLater()
        for card in self._card_pool.values():
            card.hide()
        self.poster_wall_layout.addWidget(empty_widget, 0, 0)

    def _on_scroll_lazy_load(self):
        if not hasattr(self, '_scroll_lazy_timer'):
            self._scroll_lazy_timer = QTimer(self)
            self._scroll_lazy_timer.setSingleShot(True)
            self._scroll_lazy_timer.timeout.connect(self._load_visible_posters)
        self._scroll_lazy_timer.start(100)

    def _load_visible_posters(self):
        """只加载可见区域（±1 屏缓冲）的封面"""
        if not self.movie_cards:
            return

        if self._visible_loader_running:
            if self._cover_loader is None or not self._cover_loader.isRunning():
                return
            self._cover_load_generation += 1
            self._cover_loader.cancel()
            for card in self.movie_cards:
                if getattr(card, '_poster_loading', False) and not card._poster_loaded:
                    card._poster_loading = False
            self._cover_loader = None
            self._visible_loader_running = False

        self._cover_retry_timer.stop()
        image_cache = ImageCache()

        # 真可见区懒加载：只加载当前视口上下各 1 屏缓冲内的封面
        viewport = self.scroll_area.viewport()
        scroll_y = self.scroll_area.verticalScrollBar().value()
        visible_height = viewport.height()
        buffer = visible_height
        view_top = scroll_y - buffer
        view_bottom = scroll_y + visible_height + buffer

        load_tasks = []
        card_map = {}
        batch_cards = []
        max_tasks_per_batch = 32
        now_ts = time.perf_counter()
        next_retry_in = None
        poster_w = self._poster_width
        poster_h = self._poster_height

        for card in self.movie_cards:
            if card._poster_loaded or getattr(card, '_poster_loading', False):
                continue

            card_y = card.y()
            card_bottom = card_y + card.height()
            if card_y > view_bottom:
                break
            if card_bottom < view_top:
                continue

            retry_at = getattr(card, '_poster_next_retry_at', 0.0)
            if now_ts < retry_at:
                retry_wait = retry_at - now_ts
                if next_retry_in is None or retry_wait < next_retry_in:
                    next_retry_in = retry_wait
                continue

            game = card.game
            if not game.has_cover():
                card._poster_loading = False
                card._poster_next_retry_at = now_ts + 30.0
                card.ensure_placeholder()
                continue

            urls = game.get_cover_urls()
            cached_hit = False
            for url in urls:
                if image_cache.has(url):
                    pixmap = image_cache.get(url)
                    if not pixmap.isNull():
                        card.set_cover_pixmap(pixmap)
                        card._poster_loaded = True
                        card._poster_loading = False
                        cached_hit = True
                        break
            if cached_hit:
                continue

            card._poster_loading = True
            batch_cards.append(card)
            load_tasks.append((urls, poster_w, poster_h))
            for url in urls:
                card_map.setdefault(url, []).append(card)
            if len(load_tasks) >= max_tasks_per_batch:
                break

        if not load_tasks:
            if next_retry_in is not None:
                self._schedule_visible_poster_retry(max(60, int(next_retry_in * 1000) + 20))
            return

        self._cover_load_generation += 1
        current_generation = self._cover_load_generation
        loader = BatchCoverLoader(load_tasks, self)
        self._cover_loader = loader
        self._visible_loader_running = True
        pending = deque()
        loader_finished = False
        apply_scheduled = False
        finalized = False

        def finish_loader():
            nonlocal finalized
            if (finalized or current_generation != self._cover_load_generation
                    or pending or apply_scheduled):
                return
            finalized = True
            from PyQt6 import sip
            for card in batch_cards:
                try:
                    if card is None or sip.isdeleted(card):
                        continue
                    if getattr(card, '_poster_loading', False) and not card._poster_loaded:
                        card._poster_loading = False
                        card._poster_fail_count = getattr(card, '_poster_fail_count', 0) + 1
                        card._poster_next_retry_at = (
                            time.perf_counter()
                            + min(8.0, 0.5 * card._poster_fail_count)
                        )
                        card.ensure_placeholder()
                except RuntimeError:
                    pass

            self._visible_loader_running = False
            if self._cover_loader is loader:
                self._cover_loader = None

            now = time.perf_counter()
            next_retry = None
            ready_to_load = False
            for card in self.movie_cards:
                if (card._poster_loaded or getattr(card, '_poster_loading', False)
                        or not card.game.has_cover()):
                    continue
                retry_at = getattr(card, '_poster_next_retry_at', 0.0)
                if retry_at <= now:
                    ready_to_load = True
                    break
                retry_wait = retry_at - now
                if next_retry is None or retry_wait < next_retry:
                    next_retry = retry_wait

            if ready_to_load and self.isVisible():
                QTimer.singleShot(0, self._load_visible_posters)
            elif next_retry is not None:
                self._schedule_visible_poster_retry(max(60, int(next_retry * 1000) + 20))
            elif not self._visible_loader_running and self.isVisible():
                QTimer.singleShot(50, self._load_visible_posters)

        def apply_chunk():
            nonlocal apply_scheduled
            from PyQt6 import sip
            if current_generation != self._cover_load_generation:
                while pending:
                    url, image = pending.popleft()
                    if image is None:
                        continue
                    pixmap = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
                    if not pixmap.isNull():
                        image_cache.set(url, pixmap)
                    for card in card_map.get(url, []):
                        try:
                            if card is None or sip.isdeleted(card):
                                continue
                            card._poster_loading = False
                        except RuntimeError:
                            pass
                apply_scheduled = False
                return

            applied = 0
            while pending and applied < 4:
                url, image = pending.popleft()
                pixmap = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
                if not pixmap.isNull():
                    image_cache.set(url, pixmap)
                for card in card_map.get(url, []):
                    try:
                        if card is None or sip.isdeleted(card):
                            continue
                        if not pixmap.isNull():
                            card.set_cover_pixmap(pixmap)
                            card._poster_loaded = True
                            card._poster_fail_count = 0
                            card._poster_next_retry_at = 0.0
                        card._poster_loading = False
                    except RuntimeError:
                        pass
                applied += 1

            if pending:
                QTimer.singleShot(0, apply_chunk)
                return

            apply_scheduled = False
            if loader_finished:
                finish_loader()

        def on_image_loaded(url, image):
            nonlocal apply_scheduled
            if current_generation != self._cover_load_generation:
                if image is not None:
                    pixmap = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
                    if not pixmap.isNull():
                        image_cache.set(url, pixmap)
                return
            pending.append((url, image))
            if not apply_scheduled:
                apply_scheduled = True
                QTimer.singleShot(0, apply_chunk)

        def on_all_loaded():
            nonlocal loader_finished
            if current_generation != self._cover_load_generation:
                return
            loader_finished = True
            finish_loader()

        loader.image_loaded.connect(on_image_loaded)
        loader.all_loaded.connect(on_all_loaded)
        loader.start()

        # Fallback watchdog：finish_loader 续触发在 generation 切换时可能漏掉
        if not hasattr(self, '_cover_progress_watchdog'):
            self._cover_progress_watchdog = QTimer(self)
            self._cover_progress_watchdog.timeout.connect(self._cover_watchdog_tick)
            self._cover_progress_watchdog.start(2000)

    def _cover_watchdog_tick(self):
        if self._visible_loader_running:
            return
        if not self.isVisible():
            return
        if not self.movie_cards:
            return
        for card in self.movie_cards:
            if not getattr(card, '_poster_loaded', False):
                QTimer.singleShot(0, self._load_visible_posters)
                return

    def on_game_card_clicked(self, game):
        self.detail_panel.show_loading_state(game.display_title())
        QTimer.singleShot(0, lambda: self.detail_panel.show_game(game))

    def on_game_card_right_clicked(self, game, global_pos):
        menu = QMenu(self)
        if game.quark_link:
            menu.addAction("🔗 打开下载链接", lambda: self._open_download_link(game.quark_link))
        if game.installed and game.installed_exe:
            menu.addAction("▶ 启动游戏", lambda: self._launch_game(game.installed_exe))
        if game.steam_appid:
            menu.addAction("🛒 打开 Steam 商店页",
                           lambda: self._open_download_link(
                               f"https://store.steampowered.com/app/{game.steam_appid}/"))
        menu.addSeparator()

        aaa_menu = menu.addMenu("3A 分类")
        aaa_menu.addAction("🤖 LLM 判定 3A", lambda: self._start_llm_classify(game))
        aaa_menu.addAction("🤖 LLM 判定所有新增游戏", lambda: self._start_llm_classify_new())
        aaa_menu.addAction("🤖 LLM 判定所有游戏", lambda: self._start_llm_classify_all())
        aaa_menu.addSeparator()
        aaa_menu.addAction("标记为 3A", lambda: self._set_manual_aaa_override(game, True))
        aaa_menu.addAction("标记为非 3A", lambda: self._set_manual_aaa_override(game, False))
        aaa_menu.addAction("恢复自动判断", lambda: self._set_manual_aaa_override(game, None))

        if not game.installed:
            menu.addAction("⚙ 设置游戏主程序…", lambda: self._pick_game_exe(game))
        else:
            menu.addAction("🚫 取消安装标记", lambda: self._unmark_installed(game))
        menu.addSeparator()
        menu.addAction("📁 打开游戏目录",
                       lambda: self._open_folder(os.path.dirname(game.installed_exe))
                       if game.installed and game.installed_exe else None)

        if menu.isEmpty():
            menu.addAction("（暂无可用操作）").setEnabled(False)
        menu.exec(global_pos)

    def _set_manual_aaa_override(self, game, override):
        """保存人工 3A 结论，并同步筛选、卡片和详情。"""
        game.aaa_manual_override = override
        self.cache.set_manual_aaa_override(game.norm_key, override)
        self.cache.save()
        self._sync_aaa_ui(game)
        if override is True:
            status = f"已手动标记为 3A: {game.display_title()}"
        elif override is False:
            status = f"已手动标记为非 3A: {game.display_title()}"
        else:
            status = f"已恢复自动 3A 判断: {game.display_title()}"
        self.status_label.setText(status)

    def _sync_aaa_ui(self, game):
        """3A 展示结论变化后同步筛选、卡片和详情。"""
        if self.aaa_only:
            self.apply_filters()
        card = self._card_pool.get(game.norm_key)
        if card:
            card.update_game_info(game)
        if (self.detail_panel.current_game is not None
                and self.detail_panel.current_game.norm_key == game.norm_key):
            self.detail_panel.show_game(game)

    def _start_llm_classify(self, game):
        """对单款游戏启动 LLM 3A 判定。"""
        self._start_llm_classify_batch(
            [game], f"正在用 LLM 判定《{game.display_title()}》是否 3A…")

    def _start_llm_classify_all(self):
        """对所有游戏启动 LLM 3A 判定（覆盖已判定）。"""
        self._start_llm_classify_batch(
            self.all_games, f"正在用 LLM 判定全部 {len(self.all_games)} 款游戏…")

    def _start_llm_classify_new(self):
        """对尚未做过 LLM 判定的游戏启动判定。"""
        new_games = [g for g in self.all_games if not g.aaa_llm_verdict]
        self._start_llm_classify_batch(
            new_games, f"正在用 LLM 判定 {len(new_games)} 款新增游戏…")

    def _start_llm_classify_batch(self, games, label):
        """批量 LLM 3A 判定（需在设置中配置 LLM API）。"""
        base_url = (self.config.get_value("llm_base_url", "") or "").strip()
        api_key = (self.config.get_value("llm_api_key", "") or "").strip()
        model = (self.config.get_value("llm_model", "") or "gpt-4o-mini").strip()
        if not base_url or not api_key:
            QMessageBox.information(
                self, "未配置 LLM",
                "请先在「设置」中启用 LLM 3A 判定，并填写 API Base URL 与 API Key。")
            return
        games = list(games)
        if not games:
            self.status_label.setText("没有需要判定的游戏")
            return

        games_by_key = {g.norm_key: g for g in self.all_games}
        self.status_label.setText(label)
        self.progress_bar.setRange(0, len(games))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"LLM 判定 0/{len(games)}")
        self.progress_bar.show()

        worker = LLMClassifyWorker(games, base_url, api_key, model, parent=self)

        def _on_verdict(norm_key, verdict):
            g = games_by_key.get(norm_key)
            if g is None or not isinstance(verdict, dict):
                return
            g.aaa_llm_verdict = verdict
            self.cache.set_llm_aaa_verdict(g.norm_key, verdict)
            self._sync_aaa_ui(g)
            done = self.progress_bar.value() + 1
            self.progress_bar.setValue(done)
            self.progress_bar.setFormat(f"LLM 判定 {done}/{len(games)}")
            verdict_is_aaa = verdict.get("is_aaa")
            conf = verdict.get("confidence", "low")
            self.status_label.setText(
                f"LLM 判定《{g.display_title()}》：{'是 3A' if verdict_is_aaa else '非 3A'}（置信度 {conf}）")

        def _on_finished(summary):
            self.cache.save()
            self.status_label.setText(summary)

        worker.game_verdict.connect(_on_verdict)
        worker.finished_with.connect(_on_finished)
        self._llm_worker = worker
        worker.start()

    def _pick_game_exe(self, game):
        """手动标记已安装：选择游戏主程序 exe"""
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择「{game.display_title()}」的主程序",
            "", "可执行文件 (*.exe);;所有文件 (*)")
        if not path:
            return
        exe_path = os.path.normpath(path)
        game.installed = True
        game.installed_exe = exe_path
        game.installed_source = "manual"
        self.cache.set_installed_state(game.norm_key, True, exe_path, "manual")
        self.cache.save()
        self._sync_installed_ui(game)
        self.status_label.setText(f"已标记「{game.display_title()}」为已安装")

    def _unmark_installed(self, game):
        game.installed = False
        game.installed_exe = ""
        game.installed_source = ""
        self.cache.set_installed_state(game.norm_key, False, "", "")
        self.cache.save()
        self._sync_installed_ui(game)
        self.status_label.setText(f"已取消「{game.display_title()}」的安装标记")

    def _sync_installed_ui(self, game):
        """安装状态变化后同步卡片与详情面板"""
        card = self._card_pool.get(game.norm_key)
        if card:
            card.update_game_info(game)
        if (self.detail_panel.current_game is not None
                and self.detail_panel.current_game.norm_key == game.norm_key):
            self.detail_panel.show_game(game)

    def _launch_game(self, exe_path):
        try:
            cwd = os.path.dirname(exe_path)
            subprocess.Popen(
                [exe_path],
                cwd=cwd,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            logger.info(f"启动游戏: {exe_path}")
        except Exception as e:
            logger.error(f"启动游戏失败 [{exe_path}]: {e}")
            self.status_label.setText(f"启动失败: {e}")

    def _open_download_link(self, url):
        webbrowser.open(url)

    def _open_folder(self, folder):
        try:
            os.startfile(folder)
        except Exception as e:
            logger.error(f"打开目录失败 [{folder}]: {e}")

    def _import_excel_dialog(self):
        """选择新的 Excel 文件并执行差分更新（先检查差异，确认后入库）"""
        start_dir = os.path.dirname(self.config.get_value("excel_path", "")) or str(DATA_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择游戏库 Excel 文件", start_dir,
            "Excel 文件 (*.xlsx *.xlsm);;所有文件 (*)")
        if not path:
            return
        self.config.set_value("excel_path", os.path.normpath(path))
        self.config.save_config()
        self._on_settings_saved()

    def _open_settings(self):
        """打开设置对话框；保存后按需重载数据源"""
        dialog = GameSettingsDialog(self, self.config)
        dialog.settings_saved.connect(self._on_settings_saved)
        dialog.enrich_requested.connect(self._start_background_tasks_safely)
        dialog.rescan_requested.connect(self._start_local_scan)
        dialog.exec()

    def _on_settings_saved(self):
        """设置保存：Excel 换文件或文件内容更新时，差分确认后入库"""
        excel_path = self.config.get_value("excel_path", "")
        if not excel_path:
            setattr(self, "_loaded_excel_path", "")
            logger.info("数据源已清空，重载游戏库")
            self._startup_load()
            return

        path_changed = excel_path != getattr(self, "_loaded_excel_path", "")
        if not path_changed:
            mtime = self.config.get_value("_excel_mtime", 0)
            try:
                current_mtime = os.path.getmtime(excel_path)
                content_changed = current_mtime != mtime
            except OSError:
                content_changed = True
            if not content_changed:
                return

        worker = getattr(self, "_excel_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.import_finished.disconnect()
                worker.import_error.disconnect()
            except TypeError:
                pass
            worker.wait()

        self.status_label.setText("正在检查 Excel 更新…")
        worker = ExcelImportWorker(excel_path, self.cache)
        self._excel_worker = worker
        worker.diff_checked.connect(self._on_excel_diff_checked)
        worker.diff_error.connect(self._on_excel_diff_error)
        worker.start()

    def _on_excel_diff_checked(self, games, meta):
        """差分结果确认：展示新增/更新/移除计数，用户确认后应用"""
        previous_games = self.all_games
        try:
            from gamewall.excel_parser import diff_games
            added, updated, removed = diff_games(self.all_games, games)
            if not (added or updated or removed):
                self._loaded_excel_path = meta.get("path", "")
                self._excel_mtime = meta.get("mtime")
                self.status_label.setText(f"Excel 无差异（{len(self.all_games)} 款游戏）")
                return
            lines = [f"新文件: {meta.get('path', '')}",
                     f"当前库 {len(self.all_games)} 款 → 新库 {len(games)} 款",
                     "",
                     f"新增 {len(added)} 款",
                     f"字段更新 {len(updated)} 款",
                     f"移除 {len(removed)} 款"]
            if added:
                names = "、".join(g.display_title() for g in added[:5])
                lines.append(f"新增示例: {names}{'…' if len(added) > 5 else ''}")
            ret = QMessageBox.question(
                self, "应用 Excel 更新",
                "\n".join(lines) + "\n\n是否应用更新？")
            if ret != QMessageBox.StandardButton.Yes:
                self.config.set_value("excel_path",
                                      getattr(self, "_loaded_excel_path", ""))
                self.config.save_config()
                self.status_label.setText("已取消 Excel 更新")
                return
            self.all_games = games
            self._prune_card_pool({g.norm_key for g in self.all_games})
            for game in self.all_games:
                self.cache.apply_to_game(game)
            self._refresh_auto_aaa_classifications()
            self.cache.snapshot_games(self.all_games)
            self.cache.save()
            self._loaded_excel_path = meta.get("path", "")
            self._excel_mtime = meta.get("mtime")
            self.generate_genre_options()
            self.generate_year_options()
            self.generate_developer_options()
            self.apply_filters()
            self.status_label.setText(
                f"Excel 已更新: 新增 {len(added)} / 更新 {len(updated)} / 移除 {len(removed)}")
            logger.info(f"Excel 差分更新: 新增 {len(added)} / 更新 {len(updated)} / 移除 {len(removed)}")
        except Exception:
            logger.exception("应用 Excel 更新失败")
            self.all_games = previous_games
            if previous_games:
                try:
                    self.generate_genre_options()
                    self.generate_year_options()
                    self.generate_developer_options()
                    self.apply_filters()
                except Exception:
                    logger.exception("恢复先前游戏库失败")
                self.status_label.setText(f"已保留 {len(previous_games)} 款游戏，Excel 更新未应用")
            else:
                self.status_label.setText("应用 Excel 更新失败")
            return

    def _on_excel_diff_error(self, error):
        self.status_label.setText(f"Excel 检查失败: {error}")
        logger.error(f"Excel 差分检查失败: {error}")

    def _start_background_tasks_safely(self):
        """启动可选后台工作；失败时不影响已展示的游戏库。"""
        try:
            self._start_background_tasks()
        except Exception:
            logger.exception("启动后台任务失败")
            notice = "后台任务未启动，当前游戏库仍可使用"
            if self.status_label.text():
                notice = f"{self.status_label.text()}（{notice}）"
            self.status_label.setText(notice)

    def _start_background_tasks(self):
        """启动本地扫描与联网补全（增量：仅处理缺失字段且未命中负缓存的游戏）"""
        self._start_local_scan()
        if not self.config.get_value("network_enabled", True):
            logger.info("联网开关已关闭，跳过联网补全")
            return
        if not self.config.get_value("enable_enrichment", True):
            return

        enable_gamersky = bool(self.config.get_value("enable_gamersky_scraper", True))
        enable_ign = bool(self.config.get_value("enable_ign_scraper", False))

        self._games_by_key = {g.norm_key: g for g in self.all_games}
        steam_candidates = set()
        gamersky_candidates = set()
        ign_candidates = set()
        todo = []
        for g in self.all_games:
            missing_gamersky = enable_gamersky and g.gamersky_score <= 0
            missing_ign = enable_ign and g.ign_score <= 0
            if missing_gamersky:
                gamersky_candidates.add(g.norm_key)
            if missing_ign:
                ign_candidates.add(g.norm_key)

            steam_eligible = self.cache.needs_enrichment(g)
            if steam_eligible and self.cache.get_scraper_neg(g.norm_key, "steam_match"):
                # 负缓存命中：仅当内置别名可确定性命中时才绕过
                if not steam_client.lookup_steam_alias([g.title_cn, g.title_en, g.raw_name]):
                    steam_eligible = False
            if steam_eligible:
                steam_candidates.add(g.norm_key)

            if steam_eligible or missing_gamersky or missing_ign:
                todo.append(g)

        if not todo:
            logger.info("游戏数据完整，无需联网补全")
            return

        worker = getattr(self, "_enrichment_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait()

        self._enriched_save_counter = 0
        worker = EnrichmentWorker(
            todo,
            parent=self,
            enable_steam=True,
            enable_gamersky=enable_gamersky,
            enable_ign=enable_ign,
            steam_candidates=steam_candidates,
            gamersky_candidates=gamersky_candidates,
            ign_candidates=ign_candidates,
        )
        self._enrichment_worker = worker
        worker.stage_changed.connect(self._on_enrichment_stage)
        worker.progress_updated.connect(self._on_enrichment_progress)
        worker.game_enriched.connect(self._on_game_enriched)
        worker.negative_recorded.connect(self._on_negative_recorded)
        worker.finished_with.connect(self._on_enrichment_finished)
        worker.failed.connect(self._on_enrichment_failed)

        self.progress_bar.setRange(0, len(todo))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"联网补全 0/{len(todo)}")
        self.progress_bar.show()
        worker.start()

    def _start_local_scan(self):
        game_dirs = self.config.get_value("game_dirs", []) or []
        old = getattr(self, "_scan_worker", None)
        if old is not None and old.isRunning():
            old.cancel()
            old.wait(2000)
        self._scan_worker = InstalledGameScanner(game_dirs)
        self._scan_worker.finished_with.connect(self._on_local_scan_finished)
        self._scan_worker.start()

    def _on_local_scan_finished(self, entries):
        if not entries or not self.all_games:
            return
        # 原始名/中文名/英文名全部参与匹配（快捷方式名可能是其中任意一种）
        index = {}
        for g in self.all_games:
            for name in (g.raw_name, g.title_cn, g.title_en):
                if name:
                    index.setdefault(normalize_name(name), g)
        # 按归一化名首字符分桶，子串扫描阶段只看同桶，避免 O(n×m) 全量比较
        buckets = {}
        for key in index:
            buckets.setdefault(key[0], {})[key] = index[key]
        matched = 0
        for entry in entries:
            game = self._match_local_entry(entry["name"], index, buckets)
            if not game or game.installed:
                continue
            game.installed = True
            game.installed_exe = entry["exe_path"]
            game.installed_source = entry["source"]
            self.cache.set_installed_state(game.norm_key, True,
                                           entry["exe_path"], entry["source"])
            matched += 1
            self._sync_installed_ui(game)
        if matched:
            self.cache.save()
            logger.info(f"本地游戏识别: {matched} 款已安装并匹配到游戏库")

    @staticmethod
    def _match_local_entry(name, index, buckets):
        """扫描到的名称 → 游戏库匹配：归一化精确 → 长度比≥0.6 的唯一包含

        性能：精确匹配走 dict；子串扫描按首字符分桶，仅在同桶内比较，
        将每条扫描的 O(n) 降为 O(桶大小)。归一化名过短（≤4 字符）时
        跨桶都可能是子串，兜底走全量扫描避免漏判。
        """
        nq = normalize_name(name)
        if not nq:
            return None
        game = index.get(nq)
        if game:
            return game

        # 候选桶：同首字符的键；短串兜底全量
        if len(nq) <= 4:
            candidates = index.items()
        else:
            candidates = buckets.get(nq[0], {}).items()

        hits = []
        for key, g in candidates:
            if len(key) < 3:
                continue
            ratio = min(len(nq), len(key)) / max(len(nq), len(key))
            if ratio < 0.6:
                continue
            if nq in key or key in nq:
                hits.append(g)
        return hits[0] if len(hits) == 1 else None

    def _on_enrichment_stage(self, stage):
        self.progress_bar.setFormat(f"{stage} %v/%m")

    def _on_enrichment_progress(self, done, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)

    def _on_game_enriched(self, norm_key, fields):
        """主线程合并补全结果：仅填充空字段，再同步卡片与详情面板"""
        game = self._games_by_key.get(norm_key)
        developer_applied = False
        if game:
            for field, value in fields.items():
                if (GameCacheManager._is_empty(getattr(game, field, None))
                        and not GameCacheManager._is_empty(value)):
                    setattr(game, field, value)
                    developer_applied = developer_applied or field == "developer"
        self.cache.merge_fields(norm_key, fields)
        if game:
            self._refresh_auto_aaa_classifications([game])
        if developer_applied:
            self._schedule_developer_options_refresh()
        self._enriched_save_counter += 1
        if self._enriched_save_counter >= 25:
            self._enriched_save_counter = 0
            self.cache.save()

        card = self._card_pool.get(norm_key)
        if card:
            card.update_game_info(game)
            if game and game.has_cover() and not card._poster_loading and not card._poster_loaded:
                card._poster_loading = False
                card._poster_fail_count = 0
                card._poster_next_retry_at = 0.0
                self._schedule_visible_poster_retry()
        if (game and self.detail_panel.current_game is not None
                and self.detail_panel.current_game.norm_key == norm_key):
            self.detail_panel.show_game(game)

    def _on_negative_recorded(self, norm_key, source):
        self.cache.set_scraper_neg(norm_key, source)

    def _on_enrichment_finished(self, summary):
        self.progress_bar.hide()
        self.cache.save()
        self.generate_year_options()
        self.generate_developer_options()
        logger.info(f"联网补全: {summary}")

    def _on_enrichment_failed(self, message):
        self.progress_bar.hide()
        self.cache.save()
        self._schedule_developer_options_refresh()
        self.status_label.setText("联网补全中止（网络异常），可稍后重试")
        logger.warning(f"联网补全中止: {message}")

    def _schedule_visible_poster_retry(self, delay_ms=200):
        """安排最早到期的可见封面重试。"""
        delay_ms = max(50, int(delay_ms))
        if self._cover_retry_timer.isActive():
            remaining = self._cover_retry_timer.remainingTime()
            if remaining > 0 and remaining <= delay_ms:
                return
        self._cover_retry_timer.start(delay_ms)

    def closeEvent(self, event):
        logger.info("正在关闭游戏墙...")
        self._cover_load_generation += 1
        self._cover_retry_timer.stop()
        if self._cover_loader is not None and self._cover_loader.isRunning():
            self._cover_loader.cancel()
        self._visible_loader_running = False

        for loader in [getattr(self, "_excel_worker", None),
                       getattr(self, "_enrichment_worker", None),
                       getattr(self, "_scan_worker", None)]:
            if loader is not None and loader.isRunning():
                loader.wait(2000)

        self.cache.save()
        try:
            get_poster_cache_manager().flush_index()
        except Exception as e:
            logger.error(f"落盘封面缓存索引时出错: {e}")

        try:
            self.config.set_splitter_sizes(
                list(self.main_splitter.sizes()),
                list(self.right_splitter.sizes()))
            self.config.save_config()
        except Exception as e:
            logger.error(f"关闭清理失败: {e}")
        event.accept()
