"""
新片推荐对话框

展示豆瓣正在热映 / 即将上映的新片，与本地库对比，
以表格形式展示结果，支持按类型筛选。
"""
import logging
import webbrowser
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QRadioButton,
    QButtonGroup, QAbstractItemView, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QCursor

from scraper.new_movie_checker import NewMovieFetcher, NewMovie

logger = logging.getLogger(__name__)


class NewMovieDialog(QDialog):
    """新片推荐对话框"""

    # 用户双击「已有」行时发出，携带本地 Movie 对象，供主界面跳转详情
    navigate_to_movie = pyqtSignal(object)

    def __init__(self, local_movies: list, parent=None):
        super().__init__(parent)
        self._local_movies = local_movies
        self._owned: List[NewMovie] = []
        self._missing: List[NewMovie] = []
        self._fetcher: Optional[NewMovieFetcher] = None
        self._is_closing = False
        self._init_ui()
        # 对话框创建时自动加载缓存（不联网）
        QTimer.singleShot(200, self._load_from_cache)

    def _init_ui(self):
        self.setWindowTitle("新片推荐")
        self.setMinimumSize(860, 620)
        self.resize(920, 680)
        self.setStyleSheet(_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("最新电影推荐")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 2px;")
        layout.addWidget(title)

        desc = QLabel("获取豆瓣正在热映和即将上映的电影，看看你的影库还缺什么。")
        desc.setStyleSheet("color: #6C757D; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(desc)

        # 控制行
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        ctrl_row.addWidget(QLabel("范围:"))
        self._src_group = QButtonGroup(self)
        self._rb_now = QRadioButton("正在热映")
        self._rb_now.setChecked(True)
        self._rb_coming = QRadioButton("即将上映")
        self._rb_both = QRadioButton("两者")
        for btn in (self._rb_now, self._rb_coming, self._rb_both):
            self._src_group.addButton(btn)
            ctrl_row.addWidget(btn)
            btn.toggled.connect(self._on_source_changed)

        ctrl_row.addSpacing(12)

        self._start_btn = QPushButton("开始检查")
        self._start_btn.setFixedHeight(30)
        self._start_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._start_btn.setStyleSheet(_BTN_PRIMARY)
        self._start_btn.clicked.connect(self._start_fetch)
        ctrl_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setFixedHeight(30)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._cancel_btn.setStyleSheet(_BTN_DANGER)
        self._cancel_btn.clicked.connect(self._cancel_fetch)
        ctrl_row.addWidget(self._cancel_btn)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(_PROGRESS_STYLE)
        layout.addWidget(self._progress)

        # 日志
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        self._log_text.setFixedHeight(60)
        self._log_text.setStyleSheet(_LOG_STYLE)
        layout.addWidget(self._log_text)

        # 统计 + 筛选行
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)

        self._stat_label = QLabel("")
        self._stat_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._stat_label.setStyleSheet("color: #333;")
        stat_row.addWidget(self._stat_label)
        stat_row.addStretch()

        stat_row.addWidget(QLabel("筛选:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "仅缺失", "仅已有"])
        self._filter_combo.setFixedWidth(100)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        stat_row.addWidget(self._filter_combo)

        layout.addLayout(stat_row)

        # === 结果表格 ===
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["片名", "上映日期", "豆瓣评分", "状态", "本地状态"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 80)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(_TABLE_STYLE)

        # 双击跳转
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.setToolTip("双击「缺失」行打开豆瓣网页，双击「已有」行跳转电影详情")

        # 右键菜单
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self._table, stretch=1)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(32)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(_BTN_CLOSE)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ─────────────── 缓存加载 ───────────────

    def _load_from_cache(self):
        """从本地缓存加载新片数据并对比，不联网"""
        from scraper.new_movie_checker import load_new_movie_cache, compare_with_local
        self._log_text.clear()
        self._table.setRowCount(0)
        self._owned.clear()
        self._missing.clear()
        self._stat_label.setText("")

        cached_nowplaying, cached_coming = load_new_movie_cache()

        # 根据选择的范围筛选
        all_cached = []
        sources = self._get_sources()
        if 'nowplaying' in sources and cached_nowplaying:
            self._log(f"从缓存加载: 正在热映 {len(cached_nowplaying)} 部")
            all_cached.extend(cached_nowplaying)
        if 'coming' in sources and cached_coming:
            self._log(f"从缓存加载: 即将上映 {len(cached_coming)} 部")
            all_cached.extend(cached_coming)

        if all_cached:
            owned, missing = compare_with_local(all_cached, self._local_movies)
            self._log(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
            self._on_finished(owned, missing)
        else:
            self._log("本地暂无缓存数据，请点击「开始检查」联网获取。")
            self._stat_label.setText("暂无缓存数据")

    def _on_source_changed(self, checked: bool):
        """切换范围时，优先从本地缓存加载（不联网）"""
        if not checked:
            return
        if self._fetcher and self._fetcher.isRunning():
            return
        self._load_from_cache()

    # ─────────────── 抓取控制 ───────────────

    def _get_sources(self) -> list:
        if self._rb_coming.isChecked():
            return ['coming']
        if self._rb_both.isChecked():
            return ['nowplaying', 'coming']
        return ['nowplaying']

    def _start_fetch(self):
        self._log_text.clear()
        self._table.setRowCount(0)
        self._owned.clear()
        self._missing.clear()
        self._stat_label.setText("")

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(True)

        self._fetcher = NewMovieFetcher(
            self._local_movies, self._get_sources(), use_cache=False, parent=self
        )
        self._fetcher.progress.connect(self._on_progress)
        self._fetcher.finished.connect(self._on_finished)
        self._fetcher.error.connect(self._on_error)
        self._fetcher.start()

    def _cancel_fetch(self):
        if self._fetcher and self._fetcher.isRunning():
            self._fetcher.cancel()
        self._cancel_btn.setEnabled(False)
        self._log("检查已取消。")

    # ─────────────── 回调 ───────────────

    def _on_progress(self, msg: str):
        if not self._is_closing:
            self._log(msg)

    def _on_finished(self, owned: list, missing: list):
        if self._is_closing:
            return
        self._progress.setVisible(False)
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

        self._owned = owned
        self._missing = missing
        self._stat_label.setText(
            f"合计: {len(owned)+len(missing)} | "
            f"本地已有: {len(owned)} | "
            f"缺失: {len(missing)}"
        )
        self._apply_filter()

    def _on_error(self, err: str):
        if self._is_closing:
            return
        self._progress.setVisible(False)
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._log(f"错误: {err}")
        QMessageBox.warning(self, "抓取失败", f"无法获取新片信息：\n{err}")

    # ─────────────── 表格渲染 ───────────────

    def _apply_filter(self):
        filter_mode = self._filter_combo.currentIndex()  # 0=全部 1=仅缺失 2=仅已有

        if filter_mode == 1:
            items = [(m, False) for m in self._missing]
        elif filter_mode == 2:
            items = [(m, True) for m in self._owned]
        else:
            items = [(m, True) for m in self._owned] + [(m, False) for m in self._missing]

        self._table.setRowCount(len(items))
        for row, (m, is_owned) in enumerate(items):
            is_missing = not is_owned

            # 片名
            title_item = QTableWidgetItem(m.title)
            if is_missing:
                title_item.setForeground(QColor("#007AFF"))
                url = f"https://movie.douban.com/subject/{m.douban_id}/"
                title_item.setData(Qt.ItemDataRole.UserRole + 2, url)
                title_item.setToolTip(f"双击打开豆瓣: {url}")
            self._table.setItem(row, 0, title_item)

            # 上映日期
            date_text = m.premiered or m.year or "?"
            date_item = QTableWidgetItem(date_text)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, date_item)

            # 豆瓣评分
            if m.rating > 0:
                rating_text = f"{m.rating:.1f}"
            else:
                rating_text = "?"
            rating_item = QTableWidgetItem(rating_text)
            rating_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if m.rating >= 8.0:
                rating_item.setForeground(QColor("#28A745"))
            elif m.rating >= 7.0:
                rating_item.setForeground(QColor("#007AFF"))
            self._table.setItem(row, 2, rating_item)

            # 状态（热映/即将上映）
            status_map = {"nowplaying": "热映", "coming": "即将上映"}
            status_item = QTableWidgetItem(status_map.get(m.status, m.status))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if m.status == "coming":
                status_item.setForeground(QColor("#AF52DE"))
            self._table.setItem(row, 3, status_item)

            # 本地状态
            local_status = "已有" if is_owned else "缺失"
            local_item = QTableWidgetItem(local_status)
            local_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_missing:
                local_item.setForeground(QColor("#DC3545"))
            else:
                local_item.setForeground(QColor("#28A745"))
            self._table.setItem(row, 4, local_item)

            # 存储 NewMovie 对象供双击跳转使用
            title_item.setData(Qt.ItemDataRole.UserRole + 1, m)

    def _on_row_double_clicked(self, index):
        """双击表格行：缺失电影跳转豆瓣网页，已有电影跳转本地详情"""
        row = index.row()
        title_item = self._table.item(row, 0)
        if not title_item:
            return
        new_movie: NewMovie = title_item.data(Qt.ItemDataRole.UserRole + 1)
        if not new_movie:
            return

        # 缺失电影：双击跳转豆瓣网页
        if new_movie in self._missing:
            url = title_item.data(Qt.ItemDataRole.UserRole + 2)
            if url:
                webbrowser.open(url)
            return

        # 已有电影：查找本地匹配的 Movie 对象并跳转
        from scraper.douban_ranking import _find_local_match
        local_movie = _find_local_match(new_movie, self._local_movies)
        if local_movie:
            self.navigate_to_movie.emit(local_movie)
            self.hide()

    def _show_context_menu(self, pos):
        """右键菜单：搜索下载链接、复制豆瓣链接等"""
        from PyQt6.QtWidgets import QMenu
        from urllib.parse import quote
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        title_item = self._table.item(row, 0)
        if not title_item:
            return
        new_movie: NewMovie = title_item.data(Qt.ItemDataRole.UserRole + 1)
        if not new_movie:
            return

        menu = QMenu(self)

        # 搜索下载链接
        search_action = menu.addAction(f"搜索下载链接 - {new_movie.title}")
        menu.addSeparator()

        # 复制豆瓣链接
        douban_url = f"https://movie.douban.com/subject/{new_movie.douban_id}/"
        copy_action = menu.addAction("复制豆瓣链接")
        open_action = menu.addAction("在浏览器中打开豆瓣")

        selected = menu.exec(self._table.viewport().mapToGlobal(pos))

        if selected == search_action:
            search_url = f"https://www.zhongchuangwl.com/s/{quote(new_movie.title)}/"
            webbrowser.open(search_url)
        elif selected == copy_action:
            QApplication.clipboard().setText(douban_url)
            self._log(f"已复制: {douban_url}")
        elif selected == open_action:
            webbrowser.open(douban_url)

    # ─────────────── 工具方法 ───────────────

    def _log(self, msg: str):
        if self._is_closing:
            return
        try:
            self._log_text.append(msg)
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._is_closing = True
        if self._fetcher and self._fetcher.isRunning():
            try:
                self._fetcher.progress.disconnect()
                self._fetcher.finished.disconnect()
                self._fetcher.error.disconnect()
            except Exception:
                pass
            self._fetcher.cancel()
            self._fetcher.wait(1500)
        super().closeEvent(event)


# ─────────────── 样式常量 ───────────────

_DIALOG_STYLE = """
    QDialog { background-color: #FFFFFF; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; }
    QLabel  { color: #495057; }
    QComboBox {
        border: 1px solid #CED4DA; border-radius: 4px;
        padding: 3px 8px; min-height: 22px; background-color: #FFFFFF;
    }
    QRadioButton { spacing: 6px; font-size: 13px; color: #343A40; }
    QRadioButton::indicator {
        width: 15px; height: 15px;
        border: 1.5px solid #ADB5BD; border-radius: 8px; background-color: #FFFFFF;
    }
    QRadioButton::indicator:checked { background-color: #007AFF; border-color: #007AFF; }
"""

_BTN_PRIMARY = """
    QPushButton { background-color: #007AFF; color: white; border: none;
                  border-radius: 6px; padding: 0 18px; font-weight: bold; }
    QPushButton:hover { background-color: #0056CC; }
    QPushButton:disabled { background-color: #ADB5BD; }
"""

_BTN_DANGER = """
    QPushButton { background-color: #DC3545; color: white; border: none;
                  border-radius: 6px; padding: 0 14px; }
    QPushButton:hover { background-color: #C82333; }
    QPushButton:disabled { background-color: #ADB5BD; }
"""

_BTN_CLOSE = """
    QPushButton { background-color: #6C757D; color: white; border: none;
                  border-radius: 6px; padding: 0 18px; }
    QPushButton:hover { background-color: #5A6268; }
"""

_PROGRESS_STYLE = """
    QProgressBar { border: none; background-color: #E9ECEF; border-radius: 3px; }
    QProgressBar::chunk { background-color: #007AFF; border-radius: 3px; }
"""

_LOG_STYLE = """
    QTextEdit { background-color: #1e1e1e; color: #d4d4d4;
                border: 1px solid #3c3c3c; border-radius: 6px; padding: 6px; }
"""

_TABLE_STYLE = """
    QTableWidget {
        border: 1px solid #DEE2E6; border-radius: 6px;
        gridline-color: #F1F3F5; font-size: 13px;
    }
    QTableWidget::item { padding: 4px 8px; }
    QHeaderView::section {
        background-color: #F8F9FA; border: 1px solid #DEE2E6;
        padding: 5px 8px; font-weight: bold; color: #495057;
    }
    QTableWidget::item:selected { background-color: #E8F0FE; color: #1a1a1a; }
"""
