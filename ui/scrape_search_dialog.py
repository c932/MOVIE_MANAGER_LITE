"""独立的候选匹配窗口：复用成熟刮削事务，替换旧三栏布局。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ui.scrape_dialog import ScrapeDialog, _key


class SearchScrapeDialog(ScrapeDialog):
    operation_failed = pyqtSignal(str, str)
    complete_ratings = True

    def __init__(self, movies=None, parent=None, mode='full', service=None, *, start_index=0):
        super().__init__(movies, parent, mode, service, restore_queue=False)
        self.setObjectName('scrapeSearchDialog')
        self.setWindowTitle('搜索电影与刮削')
        self.setMinimumSize(960, 650)
        self.resize(1250, 840)
        if self.target_list.count():
            self.target_list.setCurrentRow(max(0, min(start_index, self.target_list.count() - 1)))
        self._sync_targets()

    def _build_ui(self):
        # 保留控制器所需控件，但主界面只显示新的两栏工作流。
        super()._build_ui()
        root = self.layout()
        self._legacy_header = root.takeAt(0).layout()
        for i in range(self._legacy_header.count()):
            widget = self._legacy_header.itemAt(i).widget()
            if widget:
                widget.hide()
        self._legacy_body = self.body_scroll.takeWidget()
        self._legacy_body.setParent(self)
        self._legacy_body.hide()
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(200)
        self.target_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target_combo.setMinimumContentsLength(24)
        self.target_combo.setAccessibleName('当前刮削电影')
        self.target_combo.currentIndexChanged.connect(self._choose_target)
        navigation.addWidget(self.target_combo, 1)
        self.previous_target_button = QPushButton('上一部')
        self.previous_target_button.setAutoDefault(False)
        self.previous_target_button.clicked.connect(lambda: self.target_list.setCurrentRow(max(0, self.target_list.currentRow() - 1)))
        self.next_target_button = QPushButton('下一部 / 跳过')
        self.next_target_button.setAutoDefault(False)
        self.next_target_button.clicked.connect(lambda: self.target_list.setCurrentRow(min(self.target_list.count() - 1, self.target_list.currentRow() + 1)))
        navigation.addWidget(self.previous_target_button)
        navigation.addWidget(self.next_target_button)
        layout.addLayout(navigation)
        self.video_path_label = QLineEdit()
        self.video_path_label.setReadOnly(True)
        self.video_path_label.setAccessibleName('当前视频完整路径')
        layout.addWidget(self.video_path_label)
        search = QHBoxLayout()
        search.addWidget(QLabel('刮削器'))
        for widget in (self.source_combo, self.query_edit, self.year_edit, self.search_button, self.clear_button):
            search.addWidget(widget, 1 if widget is self.query_edit else 0)
        layout.addLayout(search)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 4, 6, 0)
        left_layout.addWidget(QLabel('搜索结果 · 选择候选后预览'))
        self.candidate_table = QTableWidget(0, 3)
        self.candidate_table.setHorizontalHeaderLabels(['标题', '年份', '来源 ID'])
        self.candidate_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.setColumnWidth(1, 65)
        self.candidate_table.setColumnWidth(2, 95)
        self.candidate_table.verticalHeader().hide()
        self.candidate_table.setAlternatingRowColors(True)
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.itemSelectionChanged.connect(self._choose_candidate)
        left_layout.addWidget(self.candidate_table)
        pager = QHBoxLayout()
        for widget in (self.previous_button, self.page_label, self.next_button):
            pager.addWidget(widget)
        left_layout.addLayout(pager)
        self.douban_button.setText('补全选中电影的豆瓣')
        left_layout.addWidget(self.douban_button)
        self.douban_button.setVisible(False)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 4, 0, 0)
        top = QHBoxLayout()
        self.hero_poster = QLabel('请选择搜索候选')
        self.hero_poster.setObjectName('managementPoster')
        self.hero_poster.setFixedSize(172, 258)
        self.hero_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.hero_poster, alignment=Qt.AlignmentFlag.AlignTop)
        meta = QVBoxLayout()
        meta.addWidget(self.title_edit)
        self.hero_summary = QLabel('')
        self.hero_summary.setWordWrap(True)
        meta.addWidget(self.hero_summary)
        self.plot_edit.setMaximumHeight(10000)
        meta.addWidget(self.plot_edit, 1)
        top.addLayout(meta, 1)
        right_layout.addLayout(top, 1)
        right_layout.addWidget(self.rating_label)
        right_layout.addWidget(self.match_label)
        right_layout.addWidget(self.tmdb_match_button)
        self.douban_match_button = QPushButton('匹配豆瓣补充评分')
        self.douban_match_button.setAutoDefault(False)
        self.douban_match_button.clicked.connect(self._match_douban)
        self.douban_match_button.hide()
        right_layout.addWidget(self.douban_match_button)
        right_layout.addWidget(self.confirm_button)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 750])
        layout.addWidget(splitter, 1)
        self.policy_tabs = QTabWidget()
        fields = QWidget()
        fields_layout = QVBoxLayout(fields)
        fields_layout.setContentsMargins(8, 4, 8, 4)
        fields_layout.addWidget(self.fields_widget)
        flags = QHBoxLayout()
        flags.addWidget(self.overwrite_check)
        flags.addWidget(self.metadata_only_check)
        flags.addWidget(QLabel('简介来源'))
        flags.addWidget(self.plot_source_combo)
        fields_layout.addLayout(flags)
        fields_layout.addWidget(self.identity_label)
        fields_layout.addWidget(self.rebuild_check)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        self.policy_tabs.addTab(scroll, '写入内容与策略')
        posters = QWidget()
        posters_layout = QVBoxLayout(posters)
        self.artwork_list.setMaximumHeight(10000)
        posters_layout.addWidget(self.artwork_list)
        posters_layout.addWidget(self.poster_policy_label)
        self.policy_tabs.addTab(posters, '海报选择')
        self.policy_tabs.addTab(self.preview_text, '写入预览 / 诊断')
        self.policy_tabs.setMinimumHeight(175)
        self.policy_tabs.setMaximumHeight(245)
        layout.addWidget(self.policy_tabs)
        self.body_scroll.setWidget(body)
        for widget in (self.mode_combo, self.scan_button, self.settings_button, self.choose_folder_button):
            widget.hide()
        self.target_list.hide()
        self.target_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.candidate_list.hide()

    def _refresh_targets(self):
        old = self._active_key
        self.target_list.blockSignals(True)
        self.target_list.clear()
        from PyQt6.QtWidgets import QListWidgetItem
        selected = 0
        for i, target in enumerate(self.targets):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, target)
            self._label_target(item, target)
            self.target_list.addItem(item)
            if _key(target) == old:
                selected = i
        self.target_list.blockSignals(False)
        if self.target_list.count():
            self.target_list.setCurrentRow(selected)
            if self.mode == 'douban':
                self.target_list.selectAll()
        else:
            self._target_changed(None, None)
        self._sync_targets()

    def _sync_targets(self):
        if not hasattr(self, 'target_combo'):
            return
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for i in range(self.target_list.count()):
            self.target_combo.addItem(f'{i + 1}/{self.target_list.count()}　' + self.target_list.item(i).text().replace('\n', ' · '))
        self.target_combo.setCurrentIndex(self.target_list.currentRow())
        self.target_combo.blockSignals(False)
        target = self.current_target
        self.video_path_label.setText(str(target.video_path) if target else '')
        self.video_path_label.setCursorPosition(0)
        self.douban_button.setVisible(self.mode == 'douban')
        self._update_navigation()

    def _update_navigation(self):
        if not hasattr(self, 'previous_target_button'):
            return
        writing = bool(self._write_active or self._write_queue)
        current, count = self.target_list.currentRow(), self.target_list.count()
        self.previous_target_button.setEnabled(not writing and current > 0 and not self._closing)
        self.next_target_button.setEnabled(not writing and 0 <= current < count - 1 and not self._closing)
        self.target_combo.setEnabled(not writing and not self._closing)
        hint = '仅有一部电影可处理；返回主页可更改筛选或多选电影' if count == 1 else '按当前电影列表顺序切换，未保存内容不会自动写入'
        self.previous_target_button.setToolTip(hint)
        self.next_target_button.setToolTip(hint)

    def _update_buttons(self):
        super()._update_buttons()
        self._update_navigation()
        if hasattr(self, 'douban_match_button'):
            draft = self.drafts.get(self._active_key)
            self.douban_match_button.setVisible(bool(draft and draft.confirmed and not self._preview and self.mode != 'douban'
                                                    and 'douban' not in draft.fields.get('ratings', {})))
            self.douban_match_button.setEnabled(not bool(self._write_active or self._write_queue or self._preview_pending)
                                               and not self._closing)

    def _confirm(self):
        if self.mode == 'douban':
            super()._confirm()
        elif self._preview and not self._preview_pending and not self._draft_blocked(self._preview[0]):
            # 预览已经完成跨站补分；确认时沿用整份资料，避免只重建最后一个来源。
            self._accept_match(*self._preview)

    def _match_douban(self):
        draft = self.drafts.get(self._active_key)
        if not draft or not draft.confirmed:
            return
        plot_source = self.plot_source_combo.currentData()
        self.source_combo.setCurrentIndex(self.source_combo.findData('douban'))
        self.plot_source_combo.setCurrentIndex(self.plot_source_combo.findData(plot_source))
        self.query_edit.setText(str(draft.fields.get('title') or draft.fields.get('original_title') or ''))
        self.year_edit.setText(str(draft.fields.get('year') or ''))
        self.search()

    def _choose_target(self, index):
        if index >= 0:
            self.target_list.setCurrentRow(index)

    def _target_changed(self, current, previous):
        super()._target_changed(current, previous)
        target = self.current_target
        if target and _key(target) not in self._choices:
            self.plot_source_combo.setCurrentIndex(self.plot_source_combo.findData(self.source_combo.currentData()))
        self._sync_targets()

    def _persist_queue(self):
        pass  # 子窗口仅处理所选影片，不能覆盖管理主页的全库队列。

    def clear_search(self, *args, **kwargs):
        super().clear_search(*args, **kwargs)
        if hasattr(self, 'candidate_table'):
            self.candidate_table.setRowCount(0)
            self.hero_poster.clear()
            self.hero_poster.setText('请选择搜索候选')
            self.hero_summary.clear()

    def _show_candidates(self, candidates):
        super()._show_candidates(candidates)
        self.candidate_table.blockSignals(True)
        self.candidate_table.clearSelection()
        from PyQt6.QtCore import QModelIndex
        self.candidate_table.setCurrentIndex(QModelIndex())
        self.candidate_table.setRowCount(self.candidate_list.count())
        for i in range(self.candidate_list.count()):
            candidate = self.candidate_list.item(i).data(Qt.ItemDataRole.UserRole)
            for col, value in enumerate([candidate.title, candidate.year, candidate.id]):
                item = QTableWidgetItem(value)
                item.setToolTip(candidate.overview)
                self.candidate_table.setItem(i, col, item)
        self.candidate_table.blockSignals(False)
        if self.candidate_list.currentRow() >= 0:
            self.candidate_table.selectRow(self.candidate_list.currentRow())

    def _choose_candidate(self):
        selected = self.candidate_table.currentRow()
        if selected >= 0:
            self.candidate_list.setCurrentRow(selected)

    def _render_draft(self, draft, confirmed=False):
        super()._render_draft(draft, confirmed)
        fields = draft.fields
        self.hero_summary.setText(' / '.join(str(fields.get(name, '')) for name in ('original_title', 'year', 'premiered') if fields.get(name)) +
                                  '\n' + ' / '.join(fields.get('genres', [])) + '\n' + ' / '.join(fields.get('countries', [])))

    def _load_images(self, channel, urls):
        if channel == 'candidate-images':
            return
        super()._load_images(channel, urls)

    def _on_progress(self, channel, generation, value):
        super()._on_progress(channel, generation, value)
        if channel == 'artwork-images':
            index, image, error = value
            if image is not None and (index == self.artwork_list.currentRow() or not self.hero_poster.pixmap() or self.hero_poster.pixmap().isNull()):
                from PyQt6.QtGui import QPixmap
                self.hero_poster.setPixmap(QPixmap.fromImage(image).scaled(self.hero_poster.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                                          Qt.TransformationMode.SmoothTransformation))

    def _poster_changed(self, current, previous):
        super()._poster_changed(current, previous)
        if current and not current.icon().isNull() and hasattr(self, 'hero_poster'):
            self.hero_poster.setPixmap(current.icon().pixmap(self.hero_poster.size()))

    def _set_state(self, key, state):
        super()._set_state(key, state)
        self._sync_targets()

    def _on_error(self, channel, generation, message):
        target = None
        if channel == 'write' and self._write_active:
            kind, key, payload, *_ = self._write_active
            target = payload.target if kind == 'save' else payload
        if channel == 'write' and target:
            self.operation_failed.emit(str(target.nfo_path), message)
        super()._on_error(channel, generation, message)
