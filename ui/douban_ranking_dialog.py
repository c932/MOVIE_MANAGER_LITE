"""
豆瓣电影排行榜对比对话框

功能：
- 展示豆瓣 Top250 / 近期热门榜单与本地库的对比结果
- 支持按状态筛选（全部 / 仅缺失 / 仅已有）
- 支持导出缺失列表为 JSON
- 缺失电影可复制豆瓣链接
"""
import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox,
    QAbstractItemView, QGroupBox, QRadioButton, QButtonGroup,
    QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QCursor

from scraper.douban_ranking import RankingFetcher, RankedMovie

logger = logging.getLogger(__name__)


class DoubanRankingDialog(QDialog):
    """豆瓣电影排行榜对比对话框"""

    # 用户双击「已有」行时发出，携带本地 Movie 对象，供主界面跳转详情
    navigate_to_movie = pyqtSignal(object)

    def __init__(self, local_movies: list, parent=None):
        super().__init__(parent)
        self._local_movies = local_movies
        self._owned: List[RankedMovie] = []
        self._missing: List[RankedMovie] = []
        self._fetcher: Optional[RankingFetcher] = None
        self._is_closing = False
        self._init_ui()
        # 对话框创建时自动加载缓存（如果有），不联网
        QTimer.singleShot(200, self._load_from_cache)

    def _init_ui(self):
        self.setWindowTitle("豆瓣电影排行榜对比")
        self.setMinimumSize(860, 620)
        self.resize(920, 680)
        self.setStyleSheet(_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # === 标题区域 ===
        title = QLabel("电影排行榜 vs 本地影库")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a1a; margin-bottom: 2px;")
        layout.addWidget(title)

        desc = QLabel("对比豆瓣/IMDB榜单与你的本地电影库，找出缺失的好电影。")
        desc.setStyleSheet("color: #6C757D; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(desc)

        # === 榜单选择 + 操作按钮行 ===
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        ctrl_row.addWidget(QLabel("榜单:"))
        self._src_group = QButtonGroup(self)
        self._rb_top250 = QRadioButton("豆瓣Top250")
        self._rb_top250.setChecked(True)
        self._rb_chart = QRadioButton("豆瓣热门")
        self._rb_imdb = QRadioButton("IMDB Top250")
        for btn in (self._rb_top250, self._rb_chart, self._rb_imdb):
            self._src_group.addButton(btn)
            ctrl_row.addWidget(btn)
            btn.toggled.connect(self._on_source_changed)

        ctrl_row.addSpacing(16)

        self._start_btn = QPushButton("开始对比")
        self._start_btn.setFixedHeight(30)
        self._start_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._start_btn.setStyleSheet(_BTN_PRIMARY)
        self._start_btn.clicked.connect(self._start_fetch)
        ctrl_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消抓取")
        self._cancel_btn.setFixedHeight(30)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._cancel_btn.setStyleSheet(_BTN_DANGER)
        self._cancel_btn.clicked.connect(self._cancel_fetch)
        ctrl_row.addWidget(self._cancel_btn)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # === 进度条 ===
        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(_PROGRESS_STYLE)
        layout.addWidget(self._progress)

        # === 日志区 ===
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        self._log_text.setFixedHeight(70)
        self._log_text.setStyleSheet(_LOG_STYLE)
        layout.addWidget(self._log_text)

        # === 统计 + 筛选行 ===
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)

        self._stat_label = QLabel("")
        self._stat_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._stat_label.setStyleSheet("color: #333;")
        stat_row.addWidget(self._stat_label)

        stat_row.addStretch()

        stat_row.addWidget(QLabel("显示:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "仅缺失", "仅已有"])
        self._filter_combo.setFixedWidth(100)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        stat_row.addWidget(self._filter_combo)

        self._export_btn = QPushButton("导出缺失列表")
        self._export_btn.setFixedHeight(28)
        self._export_btn.setEnabled(False)
        self._export_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._export_btn.setStyleSheet(_BTN_SECONDARY)
        self._export_btn.clicked.connect(self._export_missing)
        stat_row.addWidget(self._export_btn)

        layout.addLayout(stat_row)

        # === 结果表格 ===
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["排名", "片名", "上映日期", "豆瓣评分", "来源", "本地状态"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 50)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 80)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(_TABLE_STYLE)

        # 右键菜单：复制豆瓣链接
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        # 双击已有电影 → 跳转到主界面详情
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.setToolTip("双击「已有」行可跳转到主界面查看电影详情")

        layout.addWidget(self._table, stretch=1)

        # === 底部按钮 ===
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(32)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(_BTN_CLOSE)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ─────────────── 抓取控制 ───────────────

    def _get_sources(self) -> list:
        if self._rb_chart.isChecked():
            return ['chart']
        if self._rb_imdb.isChecked():
            return ['imdb_top250']
        return ['top250']

    def _start_fetch(self, use_cache: bool = False):
        """启动抓取/加载。use_cache=True 时优先读本地缓存；False 时强制联网刷新"""
        self._log_text.clear()
        self._table.setRowCount(0)
        self._owned.clear()
        self._missing.clear()
        self._stat_label.setText("")
        self._export_btn.setEnabled(False)

        # 根据选择的榜单更新评分列标题
        rating_label = "IMDB评分" if self._rb_imdb.isChecked() else "豆瓣评分"
        self._table.setHorizontalHeaderLabels(["排名", "片名", "上映日期", rating_label, "来源", "本地状态"])

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(True)

        self._fetcher = RankingFetcher(
            self._local_movies, self._get_sources(), use_cache=use_cache, parent=self
        )
        self._fetcher.progress.connect(self._on_progress)
        self._fetcher.finished.connect(self._on_finished)
        self._fetcher.error.connect(self._on_error)
        self._fetcher.start()

    def _on_source_changed(self, checked: bool):
        """切换榜单类型时，优先从本地缓存加载（不联网）"""
        if not checked:
            return
        if self._fetcher and self._fetcher.isRunning():
            return  # 正在抓取中，忽略切换
        self._load_from_cache()

    def _load_from_cache(self):
        """从本地缓存加载榜单数据并对比，不联网"""
        from scraper.douban_ranking import (
            load_ranking_cache, load_imdb_cache, compare_with_local,
        )
        self._log_text.clear()
        self._table.setRowCount(0)
        self._owned.clear()
        self._missing.clear()
        self._stat_label.setText("")
        self._export_btn.setEnabled(False)

        # 根据选择的榜单更新评分列标题
        rating_label = "IMDB评分" if self._rb_imdb.isChecked() else "豆瓣评分"
        self._table.setHorizontalHeaderLabels(["排名", "片名", "上映日期", rating_label, "来源", "本地状态"])

        sources = self._get_sources()
        all_ranked = []

        top250, chart = load_ranking_cache()
        imdb_movies = load_imdb_cache()

        if 'top250' in sources and top250:
            all_ranked.extend(top250)
        if 'chart' in sources and chart:
            all_ranked.extend(chart)
        if 'imdb_top250' in sources and imdb_movies:
            all_ranked.extend(imdb_movies)

        if all_ranked:
            self._log(f"从缓存加载: {len(all_ranked)} 部电影")
            owned, missing = compare_with_local(all_ranked, self._local_movies)
            self._log(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
            self._on_finished(owned, missing)
        else:
            self._log("本地暂无缓存数据，请点击「开始对比」联网获取。")
            self._stat_label.setText("暂无缓存数据")

    def _cancel_fetch(self):
        if self._fetcher and self._fetcher.isRunning():
            self._fetcher.cancel()
        self._cancel_btn.setEnabled(False)
        self._log("抓取已取消。")

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
        if missing:
            self._export_btn.setEnabled(True)
        self._apply_filter()

    def _on_error(self, err: str):
        if self._is_closing:
            return
        self._progress.setVisible(False)
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._log(f"错误: {err}")
        QMessageBox.warning(self, "抓取失败", f"无法获取榜单数据：\n{err}")

    # ─────────────── 表格渲染 ───────────────

    def _build_imdb_title_lookup(self) -> dict:
        """构建本地电影英文名→中文名的查询表（仅供 IMDB 标题翻译用）"""
        from scraper.douban_ranking import _normalize_title
        lookup = {}
        for movie in self._local_movies:
            if movie.original_title:
                key = _normalize_title(movie.original_title)
                year = (movie.year or "")[:4]
                if key and movie.title:
                    lookup[key] = movie.title
                    if year:
                        lookup[f"{key}_{year}"] = movie.title
            # 也用中文名做 key（处理本地库只有中文名的情况）
            key = _normalize_title(movie.title)
            year = (movie.year or "")[:4]
            if key:
                lookup.setdefault(key, movie.title)
                if year:
                    lookup.setdefault(f"{key}_{year}", movie.title)
        return lookup

    def _find_local_chinese_title(self, ranked_movie, lookup: dict = None) -> str:
        """尝试从本地库匹配 IMDB 英文电影的中文标题"""
        if ranked_movie.source != 'imdb_top250':
            return ranked_movie.title
        if lookup is None:
            lookup = self._build_imdb_title_lookup()
        from scraper.douban_ranking import _normalize_title, _get_title_aliases, _IMDB_TITLE_TRANSLATIONS
        norm = _normalize_title(ranked_movie.title)
        if not norm:
            return ranked_movie.title

        # 构建候选标题列表：IMDB 原标题 + 翻译表别名
        candidates = [norm]
        aliases = _get_title_aliases(ranked_movie.title)
        for alias in aliases:
            an = _normalize_title(alias)
            if an and an != norm:
                candidates.append(an)

        # 尝试匹配：先试带年份，再试不带年份
        for candidate in candidates:
            if ranked_movie.year:
                key_year = f"{candidate}_{ranked_movie.year[:4]}"
                if key_year in lookup:
                    return lookup[key_year]
            if candidate in lookup:
                return lookup[candidate]

        # 翻译表中有中文名时直接使用（即使本地库未匹配）
        if aliases:
            for alias in aliases:
                if any('\u4e00' <= c <= '\u9fff' for c in alias):
                    return alias

        return ranked_movie.title

    def _apply_filter(self):
        filter_mode = self._filter_combo.currentIndex()  # 0=全部 1=仅缺失 2=仅已有

        if filter_mode == 1:
            items = self._missing
        elif filter_mode == 2:
            items = self._owned
        else:
            items = self._owned + self._missing
            items.sort(key=lambda m: m.rank)

        # 构建 IMDB 标题翻译查询表（仅在有 IMDB 数据时构建一次）
        has_imdb = any(m.source == 'imdb_top250' for m in items)
        title_lookup = self._build_imdb_title_lookup() if has_imdb else {}

        self._table.setRowCount(len(items))
        for row, m in enumerate(items):
            is_missing = m in self._missing
            status = "缺失" if is_missing else "已有"

            rank_item = QTableWidgetItem(str(m.rank))
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, rank_item)

            # IMDB 电影尝试匹配本地中文名
            display_title = self._find_local_chinese_title(m, title_lookup)
            title_item = QTableWidgetItem(display_title)
            if is_missing:
                title_item.setForeground(QColor("#007AFF"))  # 蓝色表示可点击跳转
                # 构造跳转 URL
                if m.source == 'imdb_top250' and m.douban_id:
                    url = f"https://www.imdb.com/title/{m.douban_id}/"
                elif m.douban_id:
                    url = f"https://movie.douban.com/subject/{m.douban_id}/"
                else:
                    url = ""
                title_item.setData(Qt.ItemDataRole.UserRole + 2, url)
                title_item.setToolTip(f"双击打开网页: {url}")
            self._table.setItem(row, 1, title_item)

            year_item = QTableWidgetItem(m.premiered or m.year or "?")
            year_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, year_item)

            rating_text = f"{m.rating:.1f}" if m.rating > 0 else "?"
            rating_item = QTableWidgetItem(rating_text)
            rating_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if m.rating >= 8.0:
                rating_item.setForeground(QColor("#28A745"))
            elif m.rating >= 7.0:
                rating_item.setForeground(QColor("#007AFF"))
            self._table.setItem(row, 3, rating_item)

            source_map = {"top250": "豆瓣Top250", "chart": "豆瓣热门", "imdb_top250": "IMDB Top250"}
            source_item = QTableWidgetItem(source_map.get(m.source, m.source))
            source_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, source_item)

            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_missing:
                status_item.setForeground(QColor("#DC3545"))
            else:
                status_item.setForeground(QColor("#28A745"))
            self._table.setItem(row, 5, status_item)

            # 存储 douban_id 供右键菜单使用
            title_item.setData(Qt.ItemDataRole.UserRole, m.douban_id)
            # 存储 RankedMovie 对象供双击跳转使用
            rank_item.setData(Qt.ItemDataRole.UserRole + 1, m)

    def _on_row_double_clicked(self, index):
        """双击表格行：缺失电影跳转网页，已有电影跳转详情"""
        row = index.row()
        rank_item = self._table.item(row, 0)
        if not rank_item:
            return
        ranked_movie: RankedMovie = rank_item.data(Qt.ItemDataRole.UserRole + 1)
        if not ranked_movie:
            return

        # 缺失电影：双击跳转网页
        if ranked_movie in self._missing:
            title_item = self._table.item(row, 1)
            url = title_item.data(Qt.ItemDataRole.UserRole + 2) if title_item else ""
            if url:
                import webbrowser
                webbrowser.open(url)
            return

        # 在本地电影列表中查找匹配的电影
        from scraper.douban_ranking import _find_local_match
        local_movie = _find_local_match(ranked_movie, self._local_movies)

        if local_movie:
            self.navigate_to_movie.emit(local_movie)
            self.hide()  # 隐藏而非关闭，保持后台运行

    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        from urllib.parse import quote
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        title_item = self._table.item(row, 1)
        rank_item = self._table.item(row, 0)
        movie_id = title_item.data(Qt.ItemDataRole.UserRole) if title_item else None
        ranked_movie = rank_item.data(Qt.ItemDataRole.UserRole + 1) if rank_item else None
        if not movie_id:
            return

        is_owned = ranked_movie and ranked_movie not in self._missing
        is_imdb = ranked_movie and ranked_movie.source == 'imdb_top250'

        # 获取电影标题用于搜索
        movie_title = ranked_movie.title if ranked_movie else ""

        menu = QMenu(self)
        if is_owned:
            detail_action = menu.addAction("查看电影详情（跳转主界面）")
            menu.addSeparator()

        # 搜索下载链接
        search_action = menu.addAction(f"搜索下载链接 - {movie_title}")
        menu.addSeparator()

        if is_imdb:
            copy_action = menu.addAction("复制IMDB链接")
            open_action = menu.addAction("在浏览器中打开")
            url = f"https://www.imdb.com/title/{movie_id}/"
        else:
            copy_action = menu.addAction("复制豆瓣链接")
            open_action = menu.addAction("在浏览器中打开")
            url = f"https://movie.douban.com/subject/{movie_id}/"
        selected = menu.exec(self._table.viewport().mapToGlobal(pos))

        if selected == search_action:
            # 打开中创网盘搜索
            search_url = f"https://www.zhongchuangwl.com/s/{quote(movie_title)}/"
            import webbrowser
            webbrowser.open(search_url)
        elif is_owned and selected == detail_action:
            # 复用双击跳转逻辑
            fake_index = self._table.model().index(row, 0)
            self._on_row_double_clicked(fake_index)
        elif selected == copy_action:
            QApplication.clipboard().setText(url)
            self._log(f"已复制: {url}")
        elif selected == open_action:
            import os
            os.startfile(url)

    # ─────────────── 导出 ───────────────

    def _export_missing(self):
        if not self._missing:
            QMessageBox.information(self, "提示", "没有缺失的电影。")
            return

        default_path = os.path.join(
            str(Path.home()),
            f"missing_movies_{len(self._missing)}.json"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出缺失电影列表", default_path,
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if not file_path:
            return

        data = []
        for m in self._missing:
            entry = {
                "rank": m.rank,
                "title": m.title,
                "year": m.year,
                "rating": m.rating,
                "source": m.source,
            }
            if m.source == 'imdb_top250':
                entry["imdb_id"] = m.douban_id
                entry["imdb_url"] = f"https://www.imdb.com/title/{m.douban_id}/"
            else:
                entry["douban_id"] = m.douban_id
                entry["douban_url"] = f"https://movie.douban.com/subject/{m.douban_id}/"
            data.append(entry)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log(f"已导出到: {file_path}")
            QMessageBox.information(self, "导出成功", f"已导出 {len(data)} 部缺失电影到：\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

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

_STYLESHEET = """
    QDialog { background-color: #FFFFFF; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; }
    QLabel  { color: #495057; }
    QComboBox {
        border: 1px solid #CED4DA; border-radius: 4px;
        padding: 3px 8px; min-height: 22px; background-color: #FFFFFF;
    }
    QRadioButton {
        spacing: 6px; font-size: 13px; color: #343A40;
    }
    QRadioButton::indicator {
        width: 15px; height: 15px;
        border: 1.5px solid #ADB5BD; border-radius: 8px;
        background-color: #FFFFFF;
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

_BTN_SECONDARY = """
    QPushButton { background-color: #6C757D; color: white; border: none;
                  border-radius: 6px; padding: 0 14px; }
    QPushButton:hover { background-color: #5A6268; }
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
