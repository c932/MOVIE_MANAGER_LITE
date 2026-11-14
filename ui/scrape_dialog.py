"""统一桌面刮削工作台：人工匹配、逐视频草稿和后台保存。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QMenu, QProgressBar, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from scraper.scrape_models import Candidate, Metadata, ScrapeDraft, ScrapeError, VideoTarget, ScanProgress, can_rebuild_nfo, capture_target_version
from scraper.scrape_settings import ScrapeSettings
from ui.scrape_tasks import TaskContext, TaskRunner, download_preview, safe_message


FIELD_LABELS = {
    "title": "片名", "original_title": "原名", "year": "年份",
    "premiered": "上映日期", "plot": "简介", "tagline": "宣传语",
    "runtime": "片长", "genres": "类型", "countries": "国家",
    "directors": "导演", "actors": "演员", "set_name": "系列",
    "uniqueids": "来源 ID / 链接", "ratings": "评分 / 人数", "poster": "海报",
}
DOUBAN_FIELDS = {"uniqueids", "ratings"}


def _key(target: VideoTarget) -> str:
    return str(target.video_path).casefold()


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return "；".join(f"{k}: {_text(v)}" for k, v in value.items())
    if isinstance(value, (tuple, list)):
        return " / ".join(_text(v) for v in value)
    return str(value) if value is not None else "未取得"


def _title_key(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def _douban_complete(movie: Any) -> bool:
    try:
        score = float((getattr(movie, "ratings", {}) or {}).get("douban", 0))
    except (TypeError, ValueError):
        score = 0
    return bool(0 < score <= 10 and str(getattr(movie, "douban_url", "") or "").strip())


class ScrapeDialog(QDialog):
    """service 可注入；saved 只发送已经保存成功的 NFO 路径。"""

    saved = pyqtSignal(list)

    def __init__(self, movies=None, parent=None, mode='full', service=None):
        super().__init__(parent)
        self.setObjectName("scrapeDialog")
        self.setWindowTitle("电影刮削工作台")
        self.setMinimumSize(780, 520)
        self.resize(1100, 740)
        self.tasks = TaskRunner(self)
        self.tasks.result.connect(self._on_result)
        self.tasks.error.connect(self._on_error)
        self.tasks.progress.connect(self._on_progress)
        self.tasks.idle.connect(self._on_idle)
        self.service = service
        self.targets: list[VideoTarget] = []
        for movie in movies or []:
            if isinstance(movie, VideoTarget):
                self.targets.append(movie)
            elif getattr(movie, "nfo_path", ""):
                # stat 留给 service.build_draft，在后台捕获文件版本。
                nfo = Path(movie.nfo_path)
                video = Path(movie.video_path) if getattr(movie, "video_path", "") else nfo.with_suffix(".mkv")
                self.targets.append(VideoTarget(video, nfo, movie.title, movie.year, existing=True,
                                                douban_complete=_douban_complete(movie)))
        self.drafts: dict[str, ScrapeDraft] = {}
        self._confirmed_metadata: dict[str, list[Metadata]] = {}
        self._choices: dict[str, dict] = {}
        self._saved_keys: set[str] = set()
        self._draft_stores = {"full": (self.drafts, self._confirmed_metadata, self._choices, self._saved_keys),
                              "douban": ({}, {}, {}, set())}
        self._preview_pending = False
        self._states: dict[str, str] = {}
        self._active_key: str | None = None
        self._preview: tuple[ScrapeDraft, list[Metadata]] | None = None
        self._page = 1
        self._search_spec: tuple | None = None
        self._retry: tuple | None = None
        self._write_queue: list[tuple] = []
        self._write_active: tuple | None = None
        self._queue_cancelled = False
        self._closing = False
        self._scanning = False
        self._queue_loaded = False
        self._queue_save_active = False
        self._queue_save_pending = None
        self._pending_tmdb_match: tuple[str, str, str] | None = None
        self._settings_window = None
        self._build_ui()
        mode = {"douban_only": "douban", "new": "full", "update": "existing"}.get(mode, mode)
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(max(index, 0))
        self._mode_changed()
        if service is None:
            self._set_ready(False)
            QTimer.singleShot(0, self._initialize_service)
        else:
            self._configure_sources()
        from scraper.scan_queue import load_queue
        self.tasks.start("queue-load", lambda context: load_queue())

    def sizeHint(self) -> QSize:
        return QSize(1000, 680)

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData()

    @property
    def current_target(self) -> VideoTarget | None:
        item = self.target_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _button(self, text: str, slot, name: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        if name:
            button.setObjectName(name)
        button.clicked.connect(slot)
        return button

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)
        header = QHBoxLayout()
        heading = QLabel("电影刮削")
        heading.setObjectName("scrapeHeading")
        header.addWidget(heading)
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("处理模式")
        for label, mode in (("新电影完整刮削", "full"), ("已有电影补缺 / 重新匹配", "existing"), ("仅豆瓣评分和链接", "douban")):
            self.mode_combo.addItem(label, mode)
        header.addWidget(self.mode_combo)
        header.addStretch()
        self.scan_button = self._button("扫描电影目录", self.scan)
        header.addWidget(self.scan_button)
        self.settings_button = self._button("刮削设置", self._open_settings)
        header.addWidget(self.settings_button)
        root.addLayout(header)

        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setObjectName("scrapeBodyScroll")
        body = QWidget()
        body.setObjectName("scrapeBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        search = QGridLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("TMDB", "tmdb")
        self.source_combo.addItem("豆瓣", "douban")
        self.source_combo.setAccessibleName("搜索来源")
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("输入中文片名、当前来源 ID 或 TMDB / IMDb / 豆瓣链接")
        self.query_edit.setAccessibleName("电影搜索词或 ID 链接")
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("年份")
        self.year_edit.setAccessibleName("搜索年份")
        self.year_edit.setMaximumWidth(76)
        self.search_button = self._button("搜索", self.search, "scrapePrimary")
        self.clear_button = self._button("清空", self.clear_search)
        search.addWidget(self.source_combo, 0, 0)
        search.addWidget(self.query_edit, 0, 1)
        search.addWidget(self.year_edit, 0, 2)
        search.addWidget(self.search_button, 0, 3)
        search.addWidget(self.clear_button, 0, 4)
        search.setColumnStretch(1, 1)
        body_layout.addLayout(search)
        self.query_edit.returnPressed.connect(self.search)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        hint = QLabel("选候选 → 预览详情 → 确认匹配。跨来源资料仅在你选择并确认候选后补充。")
        hint.setObjectName("scrapeHint")
        hint.setWordWrap(True)
        body_layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        self.queue_label = QLabel("待处理电影")
        self.queue_label.setObjectName("scrapeSection")
        left_layout.addWidget(self.queue_label)
        self.target_list = QListWidget()
        self.target_list.setMinimumWidth(130)
        self.target_list.setMinimumHeight(160)
        self.target_list.setAccessibleName("待处理电影列表")
        self.target_list.currentItemChanged.connect(self._target_changed)
        self.target_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.target_list.customContextMenuRequested.connect(self._target_menu)
        left_layout.addWidget(self.target_list, 1)
        self.choose_folder_button = self._button("选择目录扫描…", self._choose_folder)
        left_layout.addWidget(self.choose_folder_button)
        self.douban_button = self._button("补全选中电影的豆瓣", self._douban_batch)
        left_layout.addWidget(self.douban_button)
        splitter.addWidget(left)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(4, 0, 4, 0)
        label = QLabel("搜索候选")
        label.setObjectName("scrapeSection")
        middle_layout.addWidget(label)
        self.candidate_list = QListWidget()
        self.candidate_list.setMinimumWidth(160)
        self.candidate_list.setAccessibleName("搜索候选列表")
        self.candidate_list.setIconSize(QSize(56, 84))
        self.candidate_list.setWordWrap(True)
        self.candidate_list.currentItemChanged.connect(self._candidate_changed)
        middle_layout.addWidget(self.candidate_list, 1)
        pager = QHBoxLayout()
        self.previous_button = self._button("上一页", lambda: self._turn_page(-1))
        self.page_label = QLabel("第 1 页")
        self.next_button = self._button("下一页", lambda: self._turn_page(1))
        pager.addWidget(self.previous_button)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_button)
        middle_layout.addLayout(pager)
        splitter.addWidget(middle)

        right = QWidget()
        right.setMinimumWidth(270)
        preview_layout = QVBoxLayout(right)
        preview_layout.setContentsMargins(4, 0, 0, 0)
        label = QLabel("详情与写入预览")
        label.setObjectName("scrapeSection")
        preview_layout.addWidget(label)
        self.match_label = QLabel("请选择电影并搜索候选。")
        self.match_label.setWordWrap(True)
        self.match_label.setObjectName("scrapeHint")
        preview_layout.addWidget(self.match_label)
        preview_layout.addWidget(QLabel("片名（确认匹配后可编辑）"))
        self.title_edit = QLineEdit()
        self.title_edit.setAccessibleName("草稿片名")
        self.title_edit.textChanged.connect(self._edit_draft)
        preview_layout.addWidget(self.title_edit)
        preview_layout.addWidget(QLabel("简介（确认匹配后可编辑）"))
        self.plot_edit = QPlainTextEdit()
        self.plot_edit.setAccessibleName("草稿简介")
        self.plot_edit.setMinimumHeight(100)
        self.plot_edit.setMaximumHeight(150)
        self.plot_edit.textChanged.connect(self._edit_draft)
        preview_layout.addWidget(self.plot_edit)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(155)
        self.preview_text.setAccessibleName("将保存的字段与文件路径")
        preview_layout.addWidget(self.preview_text)
        self.rating_label = QLabel("TMDB：未取得   IMDb：未取得   豆瓣：未取得")
        self.rating_label.setWordWrap(True)
        preview_layout.addWidget(self.rating_label)
        self.tmdb_match_button = self._button("匹配 TMDB 补充评分", self._match_tmdb)
        self.tmdb_match_button.setToolTip("保留当前资料，搜索并人工确认对应 TMDB 条目后补齐 TMDB / IMDb 评分。")
        self.tmdb_match_button.setVisible(False)
        preview_layout.addWidget(self.tmdb_match_button)
        plot_row = QHBoxLayout()
        plot_row.addWidget(QLabel("简介来源"))
        self.plot_source_combo = QComboBox()
        self.plot_source_combo.addItem("TMDB", "tmdb")
        self.plot_source_combo.addItem("豆瓣", "douban")
        self.plot_source_combo.currentIndexChanged.connect(self._plot_changed)
        plot_row.addWidget(self.plot_source_combo, 1)
        preview_layout.addLayout(plot_row)
        self.artwork_list = QListWidget()
        self.artwork_list.setAccessibleName("可选海报、语言和尺寸")
        self.artwork_list.setIconSize(QSize(60, 90))
        self.artwork_list.setMinimumHeight(125)
        self.artwork_list.setMaximumHeight(180)
        self.artwork_list.currentItemChanged.connect(self._poster_changed)
        preview_layout.addWidget(self.artwork_list)
        self.poster_policy_label = QLabel("新片无海报时，请明确勾选「仅保存元数据」。")
        self.poster_policy_label.setWordWrap(True)
        self.poster_policy_label.setObjectName("scrapeHint")
        preview_layout.addWidget(self.poster_policy_label)
        self.confirm_button = self._button("确认匹配 / 补充此来源", self._confirm, "scrapePrimary")
        preview_layout.addWidget(self.confirm_button)
        fields_label = QLabel("选择写入字段")
        preview_layout.addWidget(fields_label)
        self.fields_widget = QWidget()
        self.fields_layout = QGridLayout(self.fields_widget)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)
        self.field_checks: dict[str, QCheckBox] = {}
        for name in FIELD_LABELS:
            self._ensure_field(name)
        preview_layout.addWidget(self.fields_widget)
        self.overwrite_check = QCheckBox("覆盖勾选字段（默认仅补缺）")
        self.metadata_only_check = QCheckBox("仅保存元数据，不下载 / 替换海报")
        self.overwrite_check.toggled.connect(self._poster_policy_changed)
        self.metadata_only_check.toggled.connect(self._poster_policy_changed)
        preview_layout.addWidget(self.overwrite_check)
        preview_layout.addWidget(self.metadata_only_check)
        self.identity_label = QLabel("")
        self.identity_label.setObjectName("scrapeWarning")
        self.identity_label.setWordWrap(True)
        preview_layout.addWidget(self.identity_label)
        self.rebuild_check = QCheckBox("备份原 NFO 并重新生成电影信息")
        self.rebuild_check.setAccessibleName("备份原 NFO 并重建")
        self.rebuild_check.setToolTip("仅替换可读取的下载说明或异常 XML；保存前会再次确认并保留原文件备份。")
        self.rebuild_check.setVisible(False)
        self.rebuild_check.toggled.connect(self._rebuild_changed)
        preview_layout.addWidget(self.rebuild_check)
        splitter.addWidget(right)
        splitter.setSizes([200, 260, 430])
        body_layout.addWidget(splitter, 1)
        # 正文最小高度高于小窗口；滚动正文，保留底部操作。
        body.setMinimumHeight(730)
        self.body_scroll.setWidget(body)
        root.addWidget(self.body_scroll, 1)
        self.status_label = QLabel("请选择电影；未发现新视频时可切换到已有电影，或配置电影目录。")
        self.status_label.setObjectName("scrapeStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumHeight(64)
        root.addWidget(self.status_label)
        self.scan_progress = QProgressBar()
        self.scan_progress.setAccessibleName("电影扫描进度")
        self.scan_progress.setRange(0, 1)
        self.scan_progress.setValue(0)
        self.scan_progress.setVisible(False)
        root.addWidget(self.scan_progress)
        self.scan_directory = QLineEdit()
        self.scan_directory.setAccessibleName("当前扫描目录")
        self.scan_directory.setPlaceholderText("当前扫描目录")
        self.scan_directory.setReadOnly(True)
        self.scan_directory.setVisible(False)
        root.addWidget(self.scan_directory)
        footer = QHBoxLayout()
        self.retry_button = self._button("重试失败操作", self._retry_last)
        self.cancel_button = self._button("取消任务", self.cancel_tasks)
        self.save_button = self._button("保存当前", self._save_current, "scrapePrimary")
        self.save_all_button = self._button("保存已确认草稿", self._save_all)
        self.close_button = self._button("关闭", self.reject)
        for button in (self.retry_button, self.cancel_button):
            footer.addWidget(button)
        footer.addStretch()
        for button in (self.save_button, self.save_all_button, self.close_button):
            footer.addWidget(button)
        root.addLayout(footer)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self._update_buttons()

    def _ensure_field(self, name: str) -> None:
        if name in self.field_checks:
            return
        check = QCheckBox(FIELD_LABELS.get(name, name))
        check.setChecked(True)
        index = len(self.field_checks)
        self.fields_layout.addWidget(check, index // 3, index % 3)
        self.field_checks[name] = check

    def _set_ready(self, ready: bool) -> None:
        for widget in (self.search_button, self.scan_button, self.choose_folder_button, self.settings_button):
            widget.setEnabled(ready)
        self._update_buttons()

    def _initialize_service(self) -> None:
        if self._closing:
            return
        def initialize(context):
            from scraper.scrape_service import ScrapeService
            return ScrapeService(settings=None)
        self.tasks.start("initialize", initialize)
        self.status_label.setText("正在读取刮削配置…")

    def _configure_sources(self) -> None:
        settings = self.service.settings if self.service else ScrapeSettings()
        available = bool(settings.tmdb_api_key or settings.tmdb_token)
        self.source_combo.model().item(0).setEnabled(available and self.mode != "douban")
        self.source_combo.setToolTip("TMDB 搜索需要在刮削设置中填写 API Key 或 Token。" if not available else "选择搜索来源")
        if not available or self.mode == "douban":
            self.source_combo.setCurrentIndex(1)
        self.source_combo.setEnabled(self.mode != "douban")
        self.plot_source_combo.setEnabled(self.mode != "douban")
        if self.mode == "douban":
            self.plot_source_combo.setCurrentIndex(1)
        self.search_button.setEnabled(self.service is not None)
        self.scan_button.setEnabled(self.mode != "douban" and self.service is not None)
        self.choose_folder_button.setEnabled(self.mode != "douban" and self.service is not None)

    def _capture_choices(self) -> None:
        if self._active_key:
            self._choices[self._active_key] = {
                "fields": {name for name, check in self.field_checks.items() if check.isChecked()},
                "overwrite": self.overwrite_check.isChecked(),
                "metadata_only": self.metadata_only_check.isChecked(),
                "plot_source": self.plot_source_combo.currentData(),
                "rebuild_nfo": self.rebuild_check.isChecked(),
            }

    def _mode_changed(self) -> None:
        self._capture_choices()
        store = "douban" if self.mode == "douban" else "full"
        self.drafts, self._confirmed_metadata, self._choices, self._saved_keys = self._draft_stores[store]
        self._active_key = None
        self.clear_search(clear_query=False)
        self.target_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if self.mode == "douban" else QAbstractItemView.SelectionMode.SingleSelection)
        self.douban_button.setVisible(self.mode == "douban")
        self.queue_label.setText("已有电影（可多选）" if self.mode == "douban" else "待处理电影")
        for name, check in self.field_checks.items():
            check.setEnabled(self.mode != "douban" or name in DOUBAN_FIELDS)
        self.overwrite_check.setEnabled(self.mode != "douban")
        self.metadata_only_check.setEnabled(self.mode != "douban")
        self._configure_sources()
        self._refresh_targets()

    def _refresh_targets(self) -> None:
        old = self._active_key
        self.target_list.blockSignals(True)
        self.target_list.clear()
        selected_row = 0
        for target in self.targets:
            if self.mode == "full" and target.existing and not target.error:
                continue
            if self.mode in {"existing", "douban"} and not target.existing:
                continue
            if self.mode == "douban" and target.douban_complete is True:
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, target)
            self._label_target(item, target)
            self.target_list.addItem(item)
            if _key(target) == old:
                selected_row = self.target_list.count() - 1
        self.target_list.blockSignals(False)
        self._active_key = None
        if self.target_list.count():
            self.target_list.setCurrentRow(selected_row)
        else:
            self._target_changed(None, None)
            self.status_label.setText(
                "暂无待处理新视频。扫描电影目录，或切换到已有电影。" if self.mode == "full" else
                "没有缺少豆瓣评分或链接的电影。" if self.mode == "douban" else
                "暂无已有电影，请从电影墙选择电影后打开。")

    def _label_target(self, item: QListWidgetItem, target: VideoTarget) -> None:
        state = self._states.get(_key(target), "原 NFO 损坏" if target.error else "待处理")
        kinds = {"not_metadata": "下载说明 NFO（可备份重建）", "invalid_xml": "NFO 格式异常（可备份重建）",
                 "unreadable": "NFO 无法读取", "path_conflict": "NFO 路径冲突"}
        if target.error_kind in kinds:
            state = kinds[target.error_kind] + (f"；{self._states[_key(target)]}" if _key(target) in self._states else "")
        if self.mode == "douban" and not target.error and _key(target) not in self._states:
            state = "缺少豆瓣评分或链接"
        item.setText(f"{target.title or target.video_path.stem} {target.year}\n{state}")
        item.setToolTip(f"视频：{target.video_path}\nNFO：{target.nfo_path}\n{target.error or state}\n{target.error_detail}")

    def _set_state(self, key: str, state: str) -> None:
        self._states[key] = state
        for index in range(self.target_list.count()):
            item = self.target_list.item(index)
            target = item.data(Qt.ItemDataRole.UserRole)
            if _key(target) == key:
                self._label_target(item, target)

    def _target_menu(self, point) -> None:
        item = self.target_list.itemAt(point)
        if item is None:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        action = menu.addAction("打开所在文件夹")
        action.triggered.connect(lambda: self._open_target_folder(target))
        menu.exec(self.target_list.viewport().mapToGlobal(point))

    def _open_target_folder(self, target: VideoTarget) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.video_path.parent))):
            self.status_label.setText("打开目录失败，请检查网络或目录是否可访问：" + str(target.video_path.parent))

    def _persist_queue(self) -> None:
        self._queue_save_pending = deepcopy(self.targets)
        self._dispatch_queue_save()

    def _dispatch_queue_save(self) -> None:
        if not self._queue_loaded or self._queue_save_active or self._queue_save_pending is None:
            return
        from scraper.scan_queue import save_queue
        snapshot, self._queue_save_pending = self._queue_save_pending, None
        self._queue_save_active = True
        self.tasks.start("queue-save", lambda context: save_queue(snapshot))

    def _target_changed(self, current, previous) -> None:
        self._capture_choices()
        self.clear_search(clear_query=False)
        target = self.current_target
        self._active_key = _key(target) if target else None
        self.preview_text.clear()
        self._populate_editors(None)
        self.artwork_list.clear()
        self.identity_label.clear()
        self.rebuild_check.blockSignals(True)
        self.rebuild_check.setChecked(False)
        self.rebuild_check.setVisible(False)
        self.rebuild_check.blockSignals(False)
        self.rating_label.setText("TMDB：未取得   IMDb：未取得   豆瓣：未取得")
        self.tmdb_match_button.setVisible(False)
        if target:
            self.query_edit.setText(target.title)
            self.year_edit.setText(target.year)
            choices = self._choices.get(self._active_key, {})
            for name, check in self.field_checks.items():
                check.setChecked(name in choices.get("fields", FIELD_LABELS))
            self.overwrite_check.setChecked(choices.get("overwrite", False))
            self.metadata_only_check.setChecked(choices.get("metadata_only", False))
            self.plot_source_combo.blockSignals(True)
            source = choices.get("plot_source", "douban" if self.mode == "douban" else "tmdb")
            self.plot_source_combo.setCurrentIndex(self.plot_source_combo.findData(source))
            self.plot_source_combo.blockSignals(False)
            draft = self.drafts.get(self._active_key)
            if draft:
                self._render_draft(draft, confirmed=True)
            else:
                self.preview_text.setPlainText(f"视频：{target.video_path}\n将写入：{target.nfo_path}" + (f"\nNFO 状态：{target.error}\n{target.error_detail}" if target.error else ""))
                self.match_label.setText("请搜索并选择候选；不会自动匹配。")
        else:
            self.match_label.setText("请选择电影并搜索候选。")
        self._update_buttons()

    def _source_changed(self) -> None:
        self.clear_search(clear_query=False)

    def clear_search(self, checked=False, *, clear_query=True) -> None:
        for channel in ("search", "preview", "enrich", "artwork-images", "candidate-images"):
            self.tasks.invalidate(channel)
        self.candidate_list.clear()
        self._preview = None
        self._preview_pending = False
        self._pending_tmdb_match = None
        self._search_spec = None
        self._page = 1
        self.page_label.setText("第 1 页")
        if clear_query:
            self.query_edit.clear()
            self.year_edit.clear()
        if self.current_target and self._active_key in self.drafts:
            self._render_draft(self.drafts[self._active_key], confirmed=True)
        self._update_buttons()

    def search(self, checked=False, *, tmdb_auto=False) -> None:
        if not tmdb_auto:
            self._pending_tmdb_match = None
        if not self.service or not self.current_target or self._closing:
            self.status_label.setText("请先选择待处理电影。")
            return
        query = self.query_edit.text().strip()
        if not query:
            self.clear_search()
            self.status_label.setText("输入片名、ID 或链接后点击搜索。")
            return
        self._search_spec = (self.source_combo.currentData(), query, self.year_edit.text().strip())
        self._page = 1
        self._run_search()

    def _run_search(self) -> None:
        source, query, year = self._search_spec
        page, service = self._page, self.service
        self.tasks.invalidate("preview")
        self.tasks.invalidate("enrich")
        self.tasks.invalidate("candidate-images")
        self._preview = None
        self._preview_pending = False
        self.candidate_list.clear()
        self._retry = ("search", self._search_spec, page)
        self.status_label.setText(f"正在搜索 {query}，第 {page} 页…")
        self.tasks.start("search", lambda context: service.search(source, query, year=year, page=page))
        self.page_label.setText(f"第 {page} 页")
        self._update_buttons()

    def _turn_page(self, offset: int) -> None:
        if self._search_spec and self._page + offset >= 1:
            self._page += offset
            self._run_search()

    def _show_candidates(self, candidates: list[Candidate]) -> None:
        self.candidate_list.clear()
        for candidate in candidates:
            if candidate.media_type != "movie":
                continue
            item = QListWidgetItem(f"{candidate.title} {candidate.year}\n{candidate.original_title}\n{candidate.overview[:100]}")
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            item.setToolTip(f"{candidate.source} / {candidate.id}\n{candidate.overview}")
            self.candidate_list.addItem(item)
        if self._pending_tmdb_match is not None:
            title, original_title, year = self._pending_tmdb_match
            expected = {_title_key(title), _title_key(original_title)} - {""}
            matches = []
            for index in range(self.candidate_list.count()):
                candidate = self.candidate_list.item(index).data(Qt.ItemDataRole.UserRole)
                names = {_title_key(candidate.title), _title_key(candidate.original_title)} - {""}
                if (candidate.source == "tmdb" and candidate.media_type == "movie"
                        and names & expected and (not year or candidate.year == year)):
                    matches.append(index)
            self._pending_tmdb_match = None
            if len(matches) == 1:
                self.status_label.setText("已找到唯一同名同年的 TMDB 候选，正在加载评分预览。")
                self.candidate_list.setCurrentRow(matches[0])
                self._update_buttons()
                return
        self.status_label.setText(f"找到 {self.candidate_list.count()} 个候选；请选择并预览。" if self.candidate_list.count() else "没有找到电影候选，可改词、换来源或输入 ID / 链接重试。")
        images = [(i, self.candidate_list.item(i).data(Qt.ItemDataRole.UserRole).poster_url) for i in range(self.candidate_list.count())]
        self._load_images("candidate-images", images)
        self._update_buttons()

    def _candidate_changed(self, current, previous) -> None:
        self.tasks.invalidate("preview")
        self.tasks.invalidate("artwork-images")
        self._preview = None
        self.confirm_button.setEnabled(False)
        if not current or not self.current_target or not self.service:
            self._update_buttons()
            return
        candidate = current.data(Qt.ItemDataRole.UserRole)
        self._preview_candidate(candidate)

    def _preview_candidate(self, candidate: Candidate) -> None:
        self.tasks.invalidate("enrich")
        target, service = deepcopy(self.current_target), self.service
        if not target:
            return
        key = _key(target)
        confirmed = deepcopy(self._confirmed_metadata.get(key, [])) if self.mode != "douban" else []
        plot_source = self.plot_source_combo.currentData()
        self._retry = ("preview", candidate)
        self._preview_pending = True
        self.match_label.setText("正在获取详情；当前候选尚未确认。")
        self.preview_text.clear()
        self.artwork_list.clear()
        self.status_label.setText("正在后台获取候选详情与写入预览…")
        def build(context):
            prepared = capture_target_version(target)
            context.checkpoint()
            metadata = service.details(candidate)
            context.checkpoint()
            additional = getattr(service, "automatic_tmdb_metadata", lambda m: [])(metadata)
            context.checkpoint()
            sources = [m for m in confirmed if m.source != metadata.source] + [metadata]
            sources.extend(m for m in additional if m.source not in {source.source for source in sources})
            draft = service.build_draft(prepared, sources, plot_source=plot_source)
            draft.confirmed = False
            return key, draft, sources
        self.tasks.start("preview", build)
        self._update_buttons()

    def _render_draft(self, draft: ScrapeDraft, confirmed=False) -> None:
        self.rebuild_check.blockSignals(True)
        self.rebuild_check.setVisible(can_rebuild_nfo(draft.target))
        chosen = self._choices.get(self._active_key, {}).get("rebuild_nfo", draft.rebuild_nfo)
        draft.rebuild_nfo = bool(chosen and can_rebuild_nfo(draft.target) and self.mode != "douban")
        self.rebuild_check.setChecked(draft.rebuild_nfo)
        self.rebuild_check.blockSignals(False)
        self.match_label.setText("已确认匹配；可选择字段并保存。" if confirmed else "候选仅供预览，点击「确认匹配」后才能保存。")
        self._populate_editors(draft)
        self._render_fields(draft)
        ratings = draft.fields.get("ratings", {})
        if not isinstance(ratings, dict):
            ratings = {}
        self.rating_label.setText("   ".join(f"{label}：{_text(ratings.get(name))}" for name, label in (("tmdb", "TMDB"), ("imdb", "IMDb"), ("douban", "豆瓣"))))
        settings = self.service.settings if self.service else ScrapeSettings()
        self.tmdb_match_button.setVisible(bool(confirmed and self.mode != "douban" and "tmdb" not in ratings
                                              and (settings.tmdb_api_key or settings.tmdb_token)))
        self.identity_label.setText("身份变更：将整组替换片名、简介、演职员、各站 ID、外部评分和图片关联；保留观看、标签和用户资料。保存时需明确确认。" if draft.replace_identity else "")
        self.artwork_list.blockSignals(True)
        self.artwork_list.clear()
        none = QListWidgetItem("不选择新海报（新片需勾选仅元数据）")
        none.setData(Qt.ItemDataRole.UserRole, None)
        self.artwork_list.addItem(none)
        selected = 0
        for index, artwork in enumerate(draft.artwork, 1):
            item = QListWidgetItem(f"{artwork.source} / {artwork.language or '未标语言'}\n{artwork.width or '?'} × {artwork.height or '?'}")
            item.setToolTip(artwork.url)
            item.setData(Qt.ItemDataRole.UserRole, artwork)
            self.artwork_list.addItem(item)
            if artwork == draft.poster:
                selected = index
        self.artwork_list.setCurrentRow(selected)
        self.artwork_list.blockSignals(False)
        self._poster_policy_changed()
        self._load_images("artwork-images", [(index + 1, artwork.preview_url or artwork.url) for index, artwork in enumerate(draft.artwork)])

    def _populate_editors(self, draft: ScrapeDraft | None) -> None:
        self.title_edit.blockSignals(True)
        self.plot_edit.blockSignals(True)
        self.title_edit.setText(str(draft.fields.get("title", "")) if draft else "")
        self.plot_edit.setPlainText(str(draft.fields.get("plot", "")) if draft else "")
        self.title_edit.blockSignals(False)
        self.plot_edit.blockSignals(False)

    def _edit_draft(self) -> None:
        draft = self.drafts.get(self._active_key)
        if (not draft or not draft.confirmed or self._draft_blocked(draft) or self.mode == "douban"
                or self._preview or self._preview_pending or self._write_active):
            return
        draft.fields["title"] = self.title_edit.text().strip()
        draft.fields["plot"] = self.plot_edit.toPlainText()
        self._saved_keys.discard(self._active_key)
        self._set_state(self._active_key, "已确认（已编辑）")
        self._render_fields(draft)
        self._update_buttons()

    def _render_fields(self, draft: ScrapeDraft) -> None:
        lines = [f"视频：{draft.target.video_path}", f"将写入 NFO：{draft.target.nfo_path}"]
        for name, value in draft.fields.items():
            self._ensure_field(name)
            lines.append(f"{FIELD_LABELS.get(name, name)}：{_text(value)}")
        if getattr(draft, "votes", None):
            lines.append(f"评分人数：{_text(draft.votes)}")
        lines.extend(f"提示：{warning}" for warning in draft.warnings)
        if draft.target.error:
            if can_rebuild_nfo(draft.target):
                lines.append("将备份原 NFO，并用当前匹配生成新的电影信息。" if draft.rebuild_nfo else
                             "原 NFO 不可作为电影元数据使用；勾选「备份原 NFO 并重新生成电影信息」后可确认匹配。")
            else:
                lines.append(f"原 NFO 损坏或不可用，保存已禁用：{draft.target.error}")
            if draft.target.error_detail:
                lines.append("具体原因：" + draft.target.error_detail)
        if draft.poster:
            lines.append(f"海报：{draft.poster.url}")
        self.preview_text.setPlainText("\n\n".join(lines))

    def _load_images(self, channel: str, urls: list[tuple[int, str]]) -> None:
        self.tasks.invalidate(channel)
        urls = [(index, url) for index, url in urls if url]
        if not urls or not self.service:
            return
        settings = deepcopy(self.service.settings)
        def load(context):
            for index, url in urls:
                context.checkpoint()
                try:
                    image = download_preview(url, settings, context)
                    context.report((index, image, ""))
                except InterruptedError:
                    raise
                except Exception:
                    context.report((index, None, "缩略图加载失败，重新选择候选可重试"))
        self.tasks.start(channel, load)

    def _poster_changed(self, current, previous) -> None:
        if not current:
            return
        draft = self._preview[0] if self._preview else self.drafts.get(self._active_key)
        if draft and self.mode != "douban":
            draft.poster = current.data(Qt.ItemDataRole.UserRole)
            if draft.poster:
                self.metadata_only_check.setChecked(False)
        self._poster_policy_changed()

    def _poster_policy_changed(self) -> None:
        if self.mode == "douban":
            text = "仅豆瓣模式只保存豆瓣评分和链接，不请求或替换海报。"
        elif self.metadata_only_check.isChecked():
            text = "仅保存元数据：不下载海报；同一电影的已有海报保持原关联。"
        elif self.overwrite_check.isChecked():
            text = "覆盖模式：只有勾选「海报」且选择了新海报，才会替换已有海报。"
        elif self.current_target and self.current_target.existing:
            text = "补缺模式保留已有海报。需要替换时，请勾选「覆盖勾选字段」与「海报」。"
        else:
            text = "新片请选择海报；无海报时需明确勾选「仅保存元数据」。"
        self.poster_policy_label.setText(text)

    def _plot_changed(self) -> None:
        current_draft = self._preview[0] if self._preview else self.drafts.get(self._active_key)
        if not self.current_target or self.mode == "douban" or current_draft and self._draft_blocked(current_draft):
            return
        metadata = deepcopy(self._preview[1] if self._preview else self._confirmed_metadata.get(self._active_key, []))
        if not metadata or not self.service:
            return
        self.tasks.invalidate("enrich")
        previous = deepcopy(current_draft)
        target, key = deepcopy(previous.target if previous else self.current_target), self._active_key
        source, service = self.plot_source_combo.currentData(), self.service
        self._preview = None
        self._preview_pending = True
        self.confirm_button.setEnabled(False)
        def build(context):
            draft = service.build_draft(target, metadata, plot_source=source)
            if previous is not None:
                self._preserve_snapshot(previous, draft)
            draft.confirmed = False
            return key, draft, metadata
        self.tasks.start("preview", build)
        self.status_label.setText("正在切换简介来源，请预览后确认。")

    @staticmethod
    def _preserve_snapshot(previous: ScrapeDraft, current: ScrapeDraft) -> None:
        if current.expected_files != previous.expected_files:
            raise ScrapeError("NFO 或海报自预览后已改变，存在保存冲突，请重新加载")
        current.expected_files = deepcopy(previous.expected_files)

    def _confirm(self) -> None:
        if not self._preview or self._preview_pending or self._draft_blocked(self._preview[0]):
            return
        draft, metadata = self._preview
        enrich = getattr(self.service, "enrich_metadata", None)
        if self.mode != "douban" and enrich is not None:
            self._capture_choices()
            key, service, plot_source = self._active_key, self.service, self.plot_source_combo.currentData()
            draft, metadata = deepcopy(draft), deepcopy(metadata)
            self._preview_pending = True
            self._retry = ("confirm",)
            self.status_label.setText("匹配已确认，正在后台补充 TMDB / IMDb 评分…")
            def enrich_confirmed(context):
                context.checkpoint()
                metadata[-1] = enrich(metadata[-1])
                context.checkpoint()
                result = service.build_draft(draft.target, metadata, plot_source=plot_source)
                self._preserve_snapshot(draft, result)
                result.rebuild_nfo, result.poster = draft.rebuild_nfo, draft.poster
                return key, result, metadata
            self.tasks.start("enrich", enrich_confirmed)
            self._update_buttons()
            return
        self._accept_match(draft, metadata)

    def _match_tmdb(self) -> None:
        draft = self.drafts.get(self._active_key)
        if not draft or not draft.confirmed:
            return
        original_title = str(draft.fields.get("original_title") or draft.fields.get("title", ""))
        title = str(draft.fields.get("title", ""))
        year = str(draft.fields.get("year", ""))
        self.source_combo.setCurrentIndex(self.source_combo.findData("tmdb"))
        self._pending_tmdb_match = (title, original_title, year)
        self.query_edit.setText(original_title)
        self.year_edit.setText(year)
        self.search(tmdb_auto=True)

    def _maybe_search_tmdb(self, metadata: list[Metadata]) -> None:
        settings = self.service.settings if self.service else ScrapeSettings()
        if (self.mode == "douban" or not any(item.source == "douban" for item in metadata)
                or any(item.source == "tmdb" for item in metadata)
                or any("tmdb" in item.ratings or "tmdb" in item.ids for item in metadata)
                or not (settings.tmdb_api_key or settings.tmdb_token)):
            return
        QTimer.singleShot(0, self._match_tmdb)

    def _accept_match(self, draft: ScrapeDraft, metadata: list[Metadata]) -> None:
        draft.confirmed = True
        self.drafts[self._active_key] = draft
        self._saved_keys.discard(self._active_key)
        self._confirmed_metadata[self._active_key] = metadata
        self._preview = None
        self._preview_pending = False
        self._render_draft(draft, confirmed=True)
        self._set_state(self._active_key, "已确认")
        self.match_label.setText("已确认匹配；请点击「保存当前」写入 NFO。")
        self.status_label.setText("匹配已确认。请点击「保存当前」写入 NFO；电影墙和系列页会在保存后刷新。")
        self._capture_choices()
        self._update_buttons()
        self._maybe_search_tmdb(metadata)

    def _draft_blocked(self, draft: ScrapeDraft) -> bool:
        return bool(draft.target.error and not (draft.rebuild_nfo and can_rebuild_nfo(draft.target) and self.mode != "douban"))

    def _rebuild_changed(self, checked: bool) -> None:
        draft = self._preview[0] if self._preview else self.drafts.get(self._active_key)
        if draft is not None:
            draft.rebuild_nfo = bool(checked and can_rebuild_nfo(draft.target) and self.mode != "douban")
            self._render_fields(draft)
        self._capture_choices()
        self._update_buttons()

    def scan(self, checked=False, *, paths=None) -> None:
        if not self.service or self.mode == "douban" or self._closing:
            return
        self._retry = ("scan", paths)
        self._scanning = True
        self.status_label.setText("正在后台扫描电影目录，遵循媒体库黑名单…")
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, 0)
        self.scan_progress.setFormat("正在扫描目录…")
        self.scan_directory.setVisible(True)
        self.scan_directory.setText("正在准备扫描目录…")
        def discover(context):
            from scraper.media_discovery import discover_videos
            from utils.config_manager import ConfigManager
            config = ConfigManager()
            folders = paths if paths is not None else config.get_movie_paths()
            if not folders:
                return []
            return discover_videos(folders, blacklist_folders=config.get_blacklist_folders(),
                                   blacklist_patterns=config.get_blacklist_patterns(),
                                   check_cancelled=context.check_cancelled, progress=context.report)
        self.tasks.start("scan", discover)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择电影目录")
        if path:
            self.scan(paths=[path])

    def _selected_fields(self, key: str) -> set[str]:
        fields = set(self._choices.get(key, {}).get("fields", FIELD_LABELS))
        return fields & DOUBAN_FIELDS if self.mode == "douban" else fields

    def _prepare_saves(self, keys: list[str]) -> None:
        if self._write_active or self._write_queue or not self.service:
            return
        self._capture_choices()
        queue = []
        for key in keys:
            draft = self.drafts.get(key)
            if not draft or not draft.confirmed or self._draft_blocked(draft):
                continue
            choices = self._choices.get(key, {})
            fields = self._selected_fields(key)
            explicit_metadata_only = self.mode == "douban" or choices.get("metadata_only", False)
            if (not explicit_metadata_only and (not draft.poster or "poster" not in fields)
                    and (not draft.target.existing or draft.replace_identity or draft.rebuild_nfo)):
                self.status_label.setText("未选择可用海报；请明确勾选「仅保存元数据」，或选择海报后再保存。")
                return
            metadata_only = explicit_metadata_only or "poster" not in fields
            if not fields:
                self.status_label.setText("请至少选择一个写入字段。")
                return
            if draft.rebuild_nfo:
                answer = QMessageBox.question(self, "备份并重建 NFO",
                    f"将原样备份以下文件，再用已确认的电影信息重新生成 NFO：\n{draft.target.nfo_path}\n\n"
                    "旧文件中的发布说明或不可解析内容不会混入新电影信息；原文件保存在同目录 .mml-backup-* 文件中。是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            if draft.replace_identity:
                douban = self.mode == "douban"
                answer = QMessageBox.question(self, "确认替换电影身份",
                    f"{draft.target.title} → {draft.fields.get('title', '')}\n\n" +
                    ("将更新豆瓣关联与评分。请确认该豆瓣条目对应当前电影。" if douban else "将整组替换旧身份资料、各站 ID、外部评分及图片关联；未取得的新身份字段不会沿用旧电影。\n保留用户评分、观看、收藏、标签和技术参数。") +
                    f"\n\nNFO：{draft.target.nfo_path}\n是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            payload = deepcopy(draft)
            if self.mode == "douban":
                payload.fields = {name: {"douban": values["douban"]}
                                  for name, values in payload.fields.items()
                                  if name in DOUBAN_FIELDS and isinstance(values, dict) and "douban" in values}
                payload.poster = None
                payload.artwork = []
                payload.replace_identity = False
                if hasattr(payload, "votes"):
                    payload.votes = {s: count for s, count in payload.votes.items() if s == "douban"}
            overwrite = self.mode == "douban" or choices.get("overwrite", False)
            queue.append(("save", key, payload, fields, overwrite, metadata_only))
        self._begin_queue(queue)

    def _save_current(self) -> None:
        if self._active_key and not self._preview and not self._preview_pending:
            self._prepare_saves([self._active_key])

    def _save_all(self) -> None:
        self._prepare_saves([key for key in self.drafts if key not in self._saved_keys])

    def _douban_batch(self) -> None:
        if self._write_active or not self.service:
            return
        queue = []
        for item in self.target_list.selectedItems():
            target = item.data(Qt.ItemDataRole.UserRole)
            if target.existing and not target.error:
                queue.append(("douban", _key(target), deepcopy(target)))
        if not queue:
            self.status_label.setText("请选择要补全豆瓣的已有电影（Ctrl / Shift 可多选）。")
        self._begin_queue(queue)

    def _begin_queue(self, queue: list[tuple]) -> None:
        if not queue:
            return
        self._write_queue = queue
        self._queue_cancelled = False
        self._dispatch_write()

    def _dispatch_write(self) -> None:
        if self._queue_cancelled or self._closing or not self._write_queue:
            self._write_queue.clear()
            self._update_buttons()
            return
        job = self._write_queue.pop(0)
        self._write_active = job
        kind, key, payload, *options = job
        self._retry = ("write", job)
        self._set_state(key, "保存中" if kind == "save" else "正在补全豆瓣")
        self.status_label.setText("正在后台保存当前电影；取消仅停止后续任务…")
        service = self.service
        def save(context):
            if kind == "douban":
                return service.douban_only(payload)
            fields, overwrite, metadata_only = options
            return service.save(payload, selected_fields=fields, overwrite=overwrite, metadata_only=metadata_only)
        self.tasks.start("write", save)
        self._update_buttons()

    def cancel_tasks(self) -> None:
        self._queue_cancelled = True
        self._write_queue.clear()
        self.tasks.cancel()
        if self._scanning:
            self._scanning = False
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(0)
            self.scan_progress.setFormat("扫描已取消")
        self._preview = None
        self._preview_pending = False
        self.status_label.setText("已取消后续任务；正在等待当前请求 / 保存结束。已完成的保存会保留。")
        self._update_buttons()

    def _retry_last(self) -> None:
        if not self._retry or self._closing:
            return
        kind, *args = self._retry
        self.retry_button.setEnabled(False)
        if kind == "search":
            self._search_spec, self._page = args
            self._run_search()
        elif kind == "preview":
            self._preview_candidate(args[0])
        elif kind == "confirm":
            self._confirm()
        elif kind == "scan":
            self.scan(paths=args[0])
        elif kind == "initialize":
            self._initialize_service()
        elif kind == "write" and not self._write_active:
            self._begin_queue([args[0]])

    def _update_buttons(self) -> None:
        if not hasattr(self, "save_button"):
            return
        draft = self.drafts.get(self._active_key)
        writing = bool(self._write_active or self._write_queue)
        available = not writing and not self._closing
        self.save_button.setEnabled(bool(draft and draft.confirmed and not self._draft_blocked(draft) and not self._preview and not self._preview_pending and available))
        self.save_all_button.setEnabled(bool(any(d.confirmed and not self._draft_blocked(d) and key not in self._saved_keys for key, d in self.drafts.items()) and available))
        self.confirm_button.setEnabled(bool(self._preview and not self._preview_pending and not self._draft_blocked(self._preview[0]) and not self._closing and not writing))
        self.rebuild_check.setEnabled(available and self.mode != "douban")
        self.tmdb_match_button.setEnabled(available and not self._preview_pending)
        editable = bool(draft and draft.confirmed and not self._draft_blocked(draft) and available
                        and not self._preview and not self._preview_pending and self.mode != "douban")
        self.title_edit.setEnabled(editable)
        self.plot_edit.setEnabled(editable)
        self.douban_button.setEnabled(bool(self.service and available))
        self.mode_combo.setEnabled(available)
        self.settings_button.setEnabled(self.service is not None and available)
        self.previous_button.setEnabled(bool(self._search_spec and self._page > 1))
        self.next_button.setEnabled(bool(self._search_spec and self.candidate_list.count()))
        if not self._retry:
            self.retry_button.setEnabled(False)

    @pyqtSlot(str, int, object)
    def _on_result(self, channel: str, generation: int, value: object) -> None:
        if channel == "queue-load":
            known = {_key(target) for target in self.targets}
            loaded = [target for target in value if _key(target) not in known]
            self.targets.extend(loaded)
            self._queue_loaded = True
            if self._queue_save_pending is not None:
                self._queue_save_pending = deepcopy(self.targets)
            if loaded:
                self._refresh_targets()
                self.status_label.setText(f"已恢复上次扫描列表（{len(loaded)} 项）；点击「扫描电影目录」时才重新扫描。")
            self._dispatch_queue_save()
        elif channel == "queue-save":
            self._queue_save_active = False
            self._dispatch_queue_save()
        elif channel == "initialize":
            self.service = value
            self._set_ready(True)
            self._configure_sources()
            self.status_label.setText("刮削服务已就绪。请选择电影或扫描目录。")
        elif channel == "scan":
            self._scanning = False
            if self.scan_progress.maximum() == 0:
                self.scan_progress.setRange(0, max(len(value), 1))
                self.scan_progress.setValue(len(value) or 1)
                self.scan_progress.setFormat(f"扫描完成：发现 {len(value)} 个视频")
            known = {_key(target): index for index, target in enumerate(self.targets)}
            reset = 0
            for target in value:
                key = _key(target)
                if key not in known:
                    known[key] = len(self.targets)
                    self.targets.append(target)
                else:
                    index = known[key]
                    previous = self.targets[index]
                    changed = (previous.error != target.error or previous.nfo_path != target.nfo_path
                               or previous.nfo_stamp is not None and previous.nfo_stamp != target.nfo_stamp)
                    self.targets[index] = target
                    if changed:
                        for drafts, metadata, choices, saved in self._draft_stores.values():
                            drafts.pop(key, None)
                            metadata.pop(key, None)
                            choices.pop(key, None)
                            saved.discard(key)
                        self._states.pop(key, None)
                        reset += 1
            self._refresh_targets()
            self._persist_queue()
            warnings = [t.error for t in value if t.error]
            self.status_label.setText(f"扫描完成：发现 {len(value)} 项。" +
                                      (f"{reset} 项文件状态已变，需重新确认。" if reset else "") +
                                      (f" {len(warnings)} 项 NFO 需处理，选择条目查看原因或备份重建。" if warnings else "无新片时可切换到已有电影。"))
        elif channel == "search":
            self._show_candidates(value)
        elif channel == "preview":
            key, draft, metadata = value
            if key != self._active_key:
                return
            draft.confirmed = False
            self._preview_pending = False
            self._preview = (draft, metadata)
            self._render_draft(draft)
            self._set_state(key, "待确认")
            if draft.target.error:
                message = "原 NFO 是下载说明或格式异常：可勾选备份重建后确认匹配。" if can_rebuild_nfo(draft.target) else "原 NFO 损坏或不可用：当前仅预览，请先解决文件读取或路径问题。"
                if self.mode == "douban" and can_rebuild_nfo(draft.target):
                    message = "仅豆瓣补分不能重建 NFO，请切换到完整刮削模式。"
                self.status_label.setText(message)
            else:
                auto_tmdb = (any(item.source == "douban" for item in metadata)
                             and any(item.source == "tmdb" for item in metadata))
                self.status_label.setText(
                    "详情已取得，并自动关联唯一精确的 TMDB 候选；核对三站评分和系列后点击确认匹配。"
                    if auto_tmdb else
                    "详情已取得。核对身份、评分、简介和海报后点击确认匹配。")
        elif channel == "enrich":
            key, draft, metadata = value
            if key != self._active_key or self._closing:
                return
            self._accept_match(draft, metadata)
        elif channel == "write" and self._write_active:
            job = self._write_active
            self._write_active = None
            kind, key, payload, *options = job
            if kind == "save":
                # 服务提交后更新了快照；保留它，避免本窗口下一次保存误报冲突。
                original = self.drafts.get(key)
                if original:
                    original.expected_files = deepcopy(payload.expected_files)
                    original.target = deepcopy(payload.target)
                    original.rebuild_nfo = payload.rebuild_nfo
                    original.warnings = list(payload.warnings)
                    if not payload.rebuild_nfo:
                        self._choices.setdefault(key, {})["rebuild_nfo"] = False
                    if key == self._active_key and not self._preview and not self._preview_pending:
                        self.rebuild_check.blockSignals(True)
                        self.rebuild_check.setChecked(original.rebuild_nfo)
                        self.rebuild_check.setVisible(can_rebuild_nfo(original.target))
                        self.rebuild_check.blockSignals(False)
                        self._render_fields(original)
                self._saved_keys.add(key)
                for target in self.targets:
                    if _key(target) == key:
                        target.existing = True
                        target.nfo_stamp = payload.target.nfo_stamp
                        target.nfo_fingerprint = payload.target.nfo_fingerprint
                        target.version_captured = payload.target.version_captured
                        target.error = payload.target.error
                        target.error_kind = payload.target.error_kind
                        target.error_detail = payload.target.error_detail
                path = str(getattr(value, "nfo_path", "") or payload.target.nfo_path)
                self.saved.emit([path])
                self._set_state(key, "部分成功" if payload.warnings else "成功")
                self.status_label.setText("保存成功：" + path + ("；" + "；".join(payload.warnings) if payload.warnings else ""))
                self._persist_queue()
            elif value.get("success"):
                self.saved.emit([str(payload.nfo_path)])
                for target in self.targets:
                    if _key(target) == key:
                        target.douban_complete = True
                self._set_state(key, "成功")
                success_text = "豆瓣补全成功：" + str(value.get("message", ""))
                self._refresh_targets()
                self.status_label.setText(success_text)
            else:
                self._set_state(key, "待确认：" + str(value.get("message", "未取得唯一匹配")))
                self.status_label.setText("豆瓣补全待确认：请选择该电影，在本窗口搜索豆瓣并手动确认候选。" + str(value.get("message", "")))
            self._dispatch_write()
        self._update_buttons()

    @pyqtSlot(str, int, object)
    def _on_progress(self, channel: str, generation: int, value: object) -> None:
        if channel == "scan" and isinstance(value, ScanProgress):
            self.scan_directory.setText(value.directory)
            self.scan_directory.setCursorPosition(0)
            self.scan_directory.setToolTip(value.directory)
            self.scan_progress.setRange(0, value.total if value.total else 0)
            if value.total:
                self.scan_progress.setValue(value.current)
            self.scan_progress.setFormat(f"{value.stage}：{value.current}/{value.total}，发现 {value.found} 个视频" if value.total else
                                         f"{value.stage}：已扫描 {value.current} 个目录，发现 {value.found} 个视频")
            if value.stage == "扫描完成":
                self._scanning = False
                if not value.total:
                    self.scan_progress.setRange(0, 1)
                    self.scan_progress.setValue(1)
                    self.scan_progress.setFormat("扫描完成：未发现视频")
            return
        if channel not in {"artwork-images", "candidate-images"}:
            return
        index, image, error = value
        listing = self.artwork_list if channel == "artwork-images" else self.candidate_list
        item = listing.item(index)
        if not item:
            return
        if isinstance(image, QImage) and not image.isNull():
            # 唯一 QPixmap 创建点，位于主线程 Qt 槽。
            item.setIcon(QIcon(QPixmap.fromImage(image)))
        elif error:
            item.setToolTip(item.toolTip() + "\n" + error)

    @pyqtSlot(str, int, str)
    def _on_error(self, channel: str, generation: int, message: str) -> None:
        if channel == "queue-load":
            self._queue_loaded = True
            self._dispatch_queue_save()
        elif channel == "queue-save":
            self._queue_save_active = False
            self.status_label.setText("待处理列表保存失败：" + safe_message(message, self.service.settings if self.service else None))
            self._dispatch_queue_save()
            return
        if channel == "scan":
            self._scanning = False
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(0)
            self.scan_progress.setFormat("扫描失败，可重试")
        if channel == "search":
            self._pending_tmdb_match = None
        if channel in {"preview", "enrich"}:
            self._preview_pending = False
        if channel == "write" and self._write_active:
            kind, key, payload, *_ = self._write_active
            if kind == "save" and key in self.drafts:
                # 完整回滚后的新时间戳也必须同步，重试按钮和再次保存共用同一版本。
                self.drafts[key].expected_files = deepcopy(payload.expected_files)
                self.drafts[key].target = deepcopy(payload.target)
                for target in self.targets:
                    if _key(target) == key:
                        target.nfo_stamp = payload.target.nfo_stamp
                        target.nfo_fingerprint = payload.target.nfo_fingerprint
                        target.version_captured = payload.target.version_captured
            self._set_state(self._write_active[1], "失败：" + safe_message(message, self.service.settings))
            self._retry = ("write", self._write_active)
            self._write_active = None
            self._write_queue.clear()
        elif channel == "initialize":
            self._retry = ("initialize",)
        self.status_label.setText("操作失败：" + safe_message(message, self.service.settings if self.service else None))
        if channel == "write":
            # 底部提示高度有限，完整原因和文件路径也放在可滚动、可复制的预览中。
            self.preview_text.appendPlainText("\n" + self.status_label.text())
        self.retry_button.setEnabled(True)
        self._update_buttons()

    def _on_idle(self) -> None:
        child_busy = bool(self._settings_window and self._settings_window.tasks.busy)
        if self._closing and not self.tasks.busy and not child_busy and self.isVisible():
            super().done(QDialog.DialogCode.Rejected)

    def _open_settings(self) -> None:
        if not self.service:
            return
        from ui.scrape_settings_dialog import ScrapeSettingsDialog
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.raise_()
            return
        dialog = ScrapeSettingsDialog(self, settings=deepcopy(self.service.settings))
        dialog.settings_saved.connect(self._settings_saved)
        dialog.finished.connect(self._on_idle, Qt.ConnectionType.QueuedConnection)
        self._settings_window = dialog
        dialog.open()

    def _settings_saved(self, settings: ScrapeSettings) -> None:
        if self._closing:
            return
        # 构造服务也在后台；避免服务提供者继续持有旧配置。
        self.clear_search(clear_query=False)
        self._set_ready(False)
        def rebuild(context):
            from scraper.scrape_service import ScrapeService
            return ScrapeService(settings=settings)
        self.tasks.start("initialize", rebuild)

    def done(self, result: int) -> None:
        if self._request_close():
            return
        super().done(result)

    def _request_close(self) -> bool:
        self._closing = True
        if self.tasks.busy:
            self.cancel_tasks()
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.reject()
        child_busy = bool(self._settings_window and self._settings_window.tasks.busy)
        if child_busy:
            self.status_label.setText("正在等待设置窗口的后台操作结束后关闭…")
        return self.tasks.busy or child_busy

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._request_close():
            event.ignore()
        else:
            event.accept()
