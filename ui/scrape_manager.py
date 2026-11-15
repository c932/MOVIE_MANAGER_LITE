"""TMM 风格管理主页；电影墙只通过 saved 信号接收精确刷新。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QProgressBar, QPushButton, QSplitter, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from models.movie import Movie
from scraper.management import ManagementRow, inspect_target, load_library, path_key, row_from_movie, save_library
from scraper.scrape_models import VideoTarget
from ui.scrape_inspector import MovieInspector
from ui.scrape_table import HEADERS, MovieFilterModel, MovieTableModel
from ui.scrape_tasks import TaskRunner, safe_message


class ScrapeManagerDialog(QDialog):
    saved = pyqtSignal(list)

    def __init__(self, movies=None, parent=None, mode='full', service=None):
        super().__init__(parent)
        self.setObjectName('scrapeManager')
        self.setWindowTitle('电影资料管理')
        self.resize(1500, 850)
        self.setMinimumSize(1000, 620)
        self.service = service
        self.tasks = TaskRunner(self)
        self.tasks.result.connect(self._result)
        self.tasks.error.connect(self._error)
        self.tasks.progress.connect(self._progress)
        self.tasks.idle.connect(self._idle)
        self._closing = False
        self._loaded = False
        self._can_persist = False
        self._persist_pending = False
        self._persist_active = False
        self._pending_paths = set()
        self._refresh_active = False
        self._child = None
        seed = []
        for movie in movies or []:
            if isinstance(movie, Movie) and movie.nfo_path:
                seed.append(row_from_movie(movie))
            elif isinstance(movie, VideoTarget):
                seed.append(ManagementRow(deepcopy(movie), Movie(title=movie.title, year=movie.year,
                            video_path=str(movie.video_path), nfo_path=str(movie.nfo_path)), metadata_valid=movie.existing and not movie.error))
        self._build_ui(seed)
        self._initial_mode = {'douban_only': 'douban', 'update': 'existing', 'new': 'new'}.get(mode, mode)
        self.inspector.tasks.idle.connect(self._idle)
        def restore(context):
            from scraper.scan_queue import load_queue
            from scraper.scrape_service import ScrapeService
            warnings = []
            try:
                stored, state = load_library(with_state=True)
                can_persist = True
            except ValueError as exc:
                stored, state, can_persist = [], {}, False
                warnings.append(str(exc))
            known = {row.key: row for row in stored}
            try:
                for target in load_queue():
                    if path_key(target.video_path) not in known:
                        known[path_key(target.video_path)] = ManagementRow(target, Movie(title=target.title, year=target.year,
                            video_path=str(target.video_path), nfo_path=str(target.nfo_path)), metadata_valid=target.existing and not target.error)
            except ValueError as exc:
                warnings.append(str(exc))
            for row in seed:
                if row.key in known:
                    # 显式扫描/保存读回的资料优先，避免电影墙旧缓存覆盖新快照。
                    if not known[row.key].checked_at:
                        known[row.key].movie = row.movie
                        known[row.key].metadata_valid = True
                else:
                    known[row.key] = row
            return list(known.values()), state, self.service or ScrapeService(), warnings, can_persist
        self.tasks.start('restore', restore)

    def _build_ui(self, rows):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        toolbar = QWidget()
        toolbar.setObjectName('managementToolbar')
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(16, 10, 16, 10)
        self.scan_button = QPushButton('更新媒体库')
        self.scan_button.clicked.connect(self.scan)
        bar.addWidget(self.scan_button)
        self.folder_button = QPushButton('选择目录…')
        self.folder_button.clicked.connect(self._choose_folder)
        bar.addWidget(self.folder_button)
        self.search_button = QPushButton('搜索&&刮削')
        self.search_button.clicked.connect(self.open_search)
        self.search_button.setToolTip('为选中电影搜索候选，人工确认并刮削')
        bar.addWidget(self.search_button)
        self.douban_button = QPushButton('仅补豆瓣')
        self.douban_button.clicked.connect(lambda: self.open_search(douban=True))
        bar.addWidget(self.douban_button)
        self.edit_button = QPushButton('编辑')
        self.edit_button.clicked.connect(self.open_editor)
        bar.addWidget(self.edit_button)
        bar.addStretch()
        self.settings_button = QPushButton('刮削设置')
        self.settings_button.clicked.connect(self.open_settings)
        bar.addWidget(self.settings_button)
        close = QPushButton('关闭')
        close.clicked.connect(self.reject)
        bar.addWidget(close)
        root.addWidget(toolbar)
        filters = QHBoxLayout()
        filters.setContentsMargins(12, 10, 12, 10)
        self.query = QLineEdit()
        self.query.setAccessibleName('筛选电影标题和文件名')
        self.query.setPlaceholderText('搜索标题、原名或文件名…')
        self.query.setClearButtonEnabled(True)
        filters.addWidget(self.query, 1)
        self.filter_combo = QComboBox()
        for text, value in [('全部电影', 'all'), ('新增 / 未刮削', 'new'), ('已有电影', 'existing'),
                            ('待补信息', 'missing'), ('仅缺豆瓣评分或链接', 'douban'), ('操作失败', 'failed')]:
            self.filter_combo.addItem(text, value)
        filters.addWidget(self.filter_combo)
        self.columns_button = QToolButton()
        self.columns_button.setText('显示列 ▾')
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        columns = QMenu(self.columns_button)
        for index, label in enumerate(HEADERS):
            action = columns.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.setEnabled(index != 0)
            action.toggled.connect(lambda checked, i=index: self.table.setColumnHidden(i, not checked))
        self.columns_button.setMenu(columns)
        filters.addWidget(self.columns_button)
        root.addLayout(filters)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.model = MovieTableModel(rows, self)
        self.proxy = MovieFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setObjectName('managementTable')
        self.table.setAccessibleName('电影刮削状态表')
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, width in enumerate([155, 50, 88, 220, 55, 55, 55, 68, 65, 46, 46, 48, 114, 200]):
            self.table.setColumnWidth(i, width)
        self.table.setMinimumWidth(480)
        self.table.selectionModel().selectionChanged.connect(self._selection)
        self.table.selectionModel().currentRowChanged.connect(self._selection)
        self.table.doubleClicked.connect(self.open_editor)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.inspector = MovieInspector()
        self.inspector.setMinimumWidth(385)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.inspector)
        self.splitter.setSizes([940, 500])
        root.addWidget(self.splitter, 1)
        footer = QWidget()
        footer.setObjectName('managementFooter')
        bottom = QVBoxLayout(footer)
        bottom.setContentsMargins(12, 8, 12, 8)
        status = QHBoxLayout()
        self.count_label = QLabel('')
        self.status_label = QLabel('正在恢复本地电影列表…')
        self.status_label.setWordWrap(True)
        status.addWidget(self.count_label)
        status.addWidget(self.status_label, 1)
        self.retry_button = QPushButton('重试')
        self.retry_button.clicked.connect(self._retry)
        self.retry_button.hide()
        self.cancel_button = QPushButton('取消任务')
        self.cancel_button.clicked.connect(self.cancel_tasks)
        status.addWidget(self.retry_button)
        status.addWidget(self.cancel_button)
        bottom.addLayout(status)
        self.scan_progress = QProgressBar()
        self.scan_progress.hide()
        bottom.addWidget(self.scan_progress)
        self.scan_directory = QLineEdit()
        self.scan_directory.setReadOnly(True)
        self.scan_directory.setAccessibleName('当前扫描目录')
        self.scan_directory.hide()
        bottom.addWidget(self.scan_directory)
        root.addWidget(footer)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._filter_changed)
        self.query.textChanged.connect(lambda: self._filter_timer.start())
        self.filter_combo.currentIndexChanged.connect(self._filter_changed)
        self._selection()

    def selected_rows(self):
        return [index.data(Qt.ItemDataRole.UserRole) for index in self.table.selectionModel().selectedRows()]

    def _selection(self, *args):
        rows = self.selected_rows()
        index = self.table.currentIndex()
        current = index.data(Qt.ItemDataRole.UserRole) if index.isValid() and rows else None
        if current is not self.inspector.current_row:
            self.inspector.show_row(current)
        enabled = self._loaded and not self._closing and self.service is not None
        self.search_button.setEnabled(enabled and bool(rows))
        self.douban_button.setEnabled(enabled and any(not row.is_new for row in rows))
        self.edit_button.setEnabled(enabled and len(rows) == 1 and not rows[0].is_new and not rows[0].target.error)
        self.edit_button.setToolTip('请选择一部有有效 NFO 的电影' if len(rows) != 1 or rows[0].is_new else '编辑所选电影资料')
        self.scan_button.setEnabled(enabled and not self.tasks.busy)
        self.folder_button.setEnabled(self.scan_button.isEnabled())
        self.count_label.setText(f'{self.proxy.rowCount()} / {self.model.rowCount()} 部　已选 {len(rows)} 部')

    def _filter_changed(self, *args):
        self.proxy.set_query(self.query.text())
        self.proxy.set_mode(self.filter_combo.currentData())
        self._selection()

    def _set_rows(self, rows, preferred=None):
        selected = {row.key for row in self.selected_rows()}
        if preferred:
            selected.add(preferred)
        self.inspector.current_row = None
        self.model.set_rows(rows)
        from PyQt6.QtCore import QItemSelectionModel
        for i in range(self.proxy.rowCount()):
            index = self.proxy.index(i, 0)
            if index.data(Qt.ItemDataRole.UserRole).key in selected:
                self.table.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                self.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        if not self.selected_rows() and self.proxy.rowCount():
            self.table.selectRow(0)
        self._selection()

    def scan(self, checked=False, *, paths=None):
        if not self._loaded or self._closing or self.tasks.busy:
            return
        self._retry_paths = paths
        self._last_operation = 'scan'
        self.retry_button.hide()
        self.status_label.setText('正在更新媒体库…')
        self.scan_progress.show()
        self.scan_progress.setRange(0, 0)
        self.scan_directory.show()
        def scan(context):
            from scraper.management import scan_rows
            from utils.config_manager import ConfigManager
            config = ConfigManager()
            roots = paths if paths is not None else config.get_movie_paths()
            if not roots:
                raise ValueError('尚未配置电影目录，请选择目录或在设置中配置')
            return scan_rows(roots, blacklist_folders=config.get_blacklist_folders(), blacklist_patterns=config.get_blacklist_patterns(),
                             check_cancelled=context.check_cancelled, progress=context.report)
        self.tasks.start('scan', scan)
        self._selection()

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '选择电影目录')
        if path:
            self.scan(paths=[path])

    def _progress(self, channel, generation, value):
        if channel == 'scan':
            self.scan_directory.setText(value.directory)
            self.scan_directory.setCursorPosition(0)
            self.scan_progress.setRange(0, value.total or 0)
            self.scan_progress.setValue(value.current)
            self.scan_progress.setFormat(f'{value.stage}：{value.current}/{value.total}' if value.total else f'{value.stage}：已发现 {value.found} 个视频')

    def _result(self, channel, generation, value):
        if channel == 'restore':
            rows, state, self.service, warnings, self._can_persist = value
            self._loaded = True
            if state.get('splitter'):
                self.splitter.restoreState(QByteArray.fromHex(state['splitter'].encode()))
            self.query.setText(state.get('query', ''))
            mode = self._initial_mode if self._initial_mode in {'douban', 'existing', 'new'} else state.get('filter', 'all')
            self.filter_combo.setCurrentIndex(max(0, self.filter_combo.findData(mode)))
            self._set_rows(rows)
            # 控件获得完整祖先 QSS 后会重新初始化表头；此时再应用列宽。
            if state.get('header'):
                self.table.horizontalHeader().restoreState(QByteArray.fromHex(state['header'].encode()))
            else:
                for i, width in enumerate([155, 50, 88, 220, 55, 55, 55, 68, 65, 46, 46, 48, 114, 200]):
                    self.table.setColumnWidth(i, width)
            self._filter_changed()
            for i, action in enumerate(self.columns_button.menu().actions()):
                action.setChecked(not self.table.isColumnHidden(i))
            self.status_label.setText('；'.join(warnings) if warnings else '已恢复本地列表；点击“更新媒体库”才扫描 NAS。')
        elif channel == 'scan':
            known = {row.key: row for row in self.model.rows}
            known.update({row.key: row for row in value})
            self._set_rows(list(known.values()))
            self._can_persist = True
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(1)
            self.scan_progress.setFormat(f'扫描完成：发现 {len(value)} 部')
            self.status_label.setText(f'媒体库更新完成，扫描 {len(value)} 部，列表共 {len(known)} 部。')
            self._persist_pending = True
        elif channel == 'refresh':
            known = {row.key: row for row in self.model.rows}
            for row in value:
                row.outcome = '已保存'
                known[row.key] = row
            self._set_rows(list(known.values()))
            self._persist_pending = True
            self.status_label.setText(f'已更新 {len(value)} 部电影的资料与海报缓存。')
        elif channel == 'queue-save':
            self._persist_active = False
        self._selection()

    def _error(self, channel, generation, message):
        if channel == 'queue-save':
            self._persist_active = False
        self.status_label.setText('操作失败：' + safe_message(message, getattr(self.service, 'settings', None)))
        if channel == 'scan':
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(0)
            self.scan_progress.setFormat('扫描失败，已保留原列表')
        self.retry_button.setVisible(channel in {'scan', 'refresh'})

    def _retry(self):
        if getattr(self, '_last_operation', '') == 'scan':
            self.scan(paths=getattr(self, '_retry_paths', None))
        else:
            self._pending_paths.update(getattr(self, '_refresh_paths', ()))
            self._idle()

    def _ui_state(self):
        return {'header': bytes(self.table.horizontalHeader().saveState().toHex()).decode(),
                'splitter': bytes(self.splitter.saveState().toHex()).decode(),
                'query': self.query.text(), 'filter': self.filter_combo.currentData()}

    def _idle(self):
        if self.tasks.busy:
            return
        if self._pending_paths:
            paths = self._pending_paths
            self._pending_paths = set()
            self._refresh_paths = paths
            self._last_operation = 'refresh'
            targets = {path_key(row.target.nfo_path): deepcopy(row.target) for row in self.model.rows}
            def refresh(context):
                from utils.poster_cache_manager import PosterCacheManager
                rows = []
                for path in paths:
                    context.checkpoint()
                    target = targets.get(path_key(path))
                    if target:
                        row = inspect_target(target)
                        if row.movie.poster_path:
                            PosterCacheManager().refresh_from_source(row.movie.poster_path)
                        rows.append(row)
                return rows
            self.tasks.start('refresh', refresh)
            return
        if self._persist_pending and self._can_persist:
            self._persist_pending = False
            self._persist_active = True
            rows, state = deepcopy(self.model.rows), self._ui_state()
            def persist(context):
                from scraper.scan_queue import save_queue
                save_library(rows, state)
                save_queue([row.target for row in rows])
            self.tasks.start('queue-save', persist)
            return
        self._selection()
        if self._closing and not self.inspector.tasks.busy and self._child is None:
            QDialog.done(self, 0)

    def _child_saved(self, paths):
        self._pending_paths.update(paths)
        self.saved.emit(paths)
        self._idle()

    def open_search(self, checked=False, *, douban=False):
        rows = self.selected_rows()
        if douban:
            rows = [row for row in rows if not row.is_new]
        if not rows or not self.service:
            return
        from ui.scrape_search_dialog import SearchScrapeDialog
        dialog = SearchScrapeDialog([deepcopy(row.target) for row in rows], self, mode='douban' if douban else 'full', service=self.service)
        dialog.saved.connect(self._child_saved)
        dialog.operation_failed.connect(self._child_failed)
        self._child = dialog
        dialog.exec()
        self._child = None
        dialog.deleteLater()
        self._idle()

    def _child_failed(self, path, message):
        for row in self.model.rows:
            if path_key(row.target.nfo_path) == path_key(path):
                row.outcome, row.message = '失败', message
        self._set_rows(self.model.rows)
        self._persist_pending = True
        self._idle()

    def open_editor(self, *args):
        rows = self.selected_rows()
        if len(rows) != 1 or rows[0].is_new or rows[0].target.error:
            return
        from ui.metadata_editor import MetadataEditorDialog
        row = rows[0]
        dialog = MetadataEditorDialog(str(row.target.nfo_path), str(row.target.video_path), self)
        dialog.saved.connect(self._child_saved)
        dialog.operation_failed.connect(self._child_failed)
        self._child = dialog
        dialog.exec()
        self._child = None
        dialog.deleteLater()
        self._idle()

    def open_settings(self):
        if self._child is not None:
            return
        from ui.scrape_settings_dialog import ScrapeSettingsDialog
        dialog = ScrapeSettingsDialog(parent=self)
        self._child = dialog
        dialog.settings_saved.connect(self._settings_saved)
        dialog.finished.connect(lambda: self._settings_closed(dialog))
        dialog.show()

    def _settings_saved(self, settings):
        from scraper.scrape_service import ScrapeService
        self.service = ScrapeService(settings)

    def _settings_closed(self, dialog):
        self._child = None
        dialog.deleteLater()
        self._idle()

    def _context_menu(self, point):
        index = self.table.indexAt(point)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row(), index.parent()):
            self.table.selectRow(index.row())
        row = index.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction('打开所在文件夹', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(row.target.video_path.parent))))
        menu.addAction('搜索&刮削', self.open_search)
        menu.addAction('编辑', self.open_editor).setEnabled(self.edit_button.isEnabled())
        menu.exec(self.table.viewport().mapToGlobal(point))

    def cancel_tasks(self):
        self.tasks.cancel(protect={'refresh'})
        self.status_label.setText('已取消后续任务，正在等待当前操作结束；已有列表和已保存结果会保留。')
        if self.scan_progress.isVisible():
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(0)
            self.scan_progress.setFormat('扫描已取消')

    def done(self, result):
        if not self._closing:
            self._closing = True
            self._persist_pending = self._loaded and self._can_persist
            self.tasks.cancel(protect={'refresh'})
            self.inspector.tasks.cancel()
            if self._child:
                self._child.reject()
        self._idle()

    def closeEvent(self, event):
        self.done(0)
        if self.tasks.busy or self.inspector.tasks.busy or self._child:
            event.ignore()
        else:
            event.accept()
