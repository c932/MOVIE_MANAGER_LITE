"""刮削凭据和网络设置；配置读写与连接测试均在后台。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from scraper.scrape_settings import ScrapeSettings
from ui.scrape_tasks import TaskRunner, safe_message


def test_connection(settings: ScrapeSettings, source: str) -> str:
    """使用与正式请求相同的提供者；不保存测试结果到媒体库。"""
    from scraper.metadata_sources import DoubanProvider, OmdbProvider, TmdbProvider
    settings.validate()
    if source == "omdb":
        if not settings.omdb_api_key:
            raise ValueError("请先填写 OMDb API Key")
        rating, _votes = OmdbProvider(settings).rating("tt0111161")
        if rating is None:
            raise ValueError("连接已返回，但未取得测试条目的 IMDb 评分")
    elif source == "imdb":
        from scraper.imdb_provider import ImdbProvider
        rating, _votes = ImdbProvider(settings).rating("tt0111161")
        if rating is None:
            raise ValueError("IMDb 未提供测试电影的评分")
    else:
        if source == "tmdb" and not (settings.tmdb_api_key or settings.tmdb_token):
            raise ValueError("请先填写 TMDB API Key 或 Token")
        provider = TmdbProvider(settings) if source == "tmdb" else DoubanProvider(settings)
        if not provider.search("肖申克的救赎", year="1994", page=1):
            raise ValueError("连接已返回，但没有取得测试候选")
    return "连接测试成功：已取得测试条目。此操作未写入影库。"


class ScrapeSettingsDialog(QDialog):
    settings_saved = pyqtSignal(object)

    def __init__(self, parent=None, settings: ScrapeSettings | None = None,
                 connection_test: Callable | None = None):
        super().__init__(parent)
        self.setObjectName("scrapeSettingsDialog")
        self.setWindowTitle("刮削设置")
        self.resize(640, 620)
        self.setMinimumSize(480, 400)
        self.tasks = TaskRunner(self)
        self.tasks.result.connect(self._result)
        self.tasks.error.connect(self._error)
        self.tasks.idle.connect(self._idle)
        self._closing = False
        self._saving = False
        self._completion_result = QDialog.DialogCode.Rejected
        self._settings = settings or ScrapeSettings()
        self._connection_test = connection_test or test_connection
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        title = QLabel("数据源与网络")
        title.setObjectName("scrapeHeading")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.tmdb_key_edit = QLineEdit()
        self.tmdb_token_edit = QLineEdit()
        self.omdb_key_edit = QLineEdit()
        self._credentials = (self.tmdb_key_edit, self.tmdb_token_edit, self.omdb_key_edit)
        for label, edit in zip(("TMDB API Key", "TMDB Read Token", "OMDb API Key"), self._credentials):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setAccessibleName(label)
            form.addRow(label, edit)
        self.show_credentials_check = QCheckBox("显示凭据")
        self.show_credentials_check.toggled.connect(self._toggle_credentials)
        form.addRow("", self.show_credentials_check)
        self.language_edit = QLineEdit()
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890（留空直连）")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setSuffix(" 秒")
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0, 60)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setSuffix(" 秒")
        form.addRow("首选语言", self.language_edit)
        form.addRow("HTTP(S) 代理", self.proxy_edit)
        form.addRow("请求超时", self.timeout_spin)
        form.addRow("豆瓣请求间隔", self.delay_spin)
        note = QLabel("凭据保存在本机配置文件中，未加密。TMDB Key 用于 TMDB；IMDb 评分无需 Key，OMDb 是可选来源。确认匹配后按明确 IMDb ID 补充跨站评分。豆瓣需要 Node / npx，其 CLI 代理支持以连接测试结果为准。")
        note.setWordWrap(True)
        note.setObjectName("scrapeHint")
        form.addRow(note)
        test_row = QHBoxLayout()
        self.test_source_combo = QComboBox()
        for label, value in (("TMDB", "tmdb"), ("IMDb（无需 Key）", "imdb"), ("OMDb（可选）", "omdb"), ("豆瓣", "douban")):
            self.test_source_combo.addItem(label, value)
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test)
        test_row.addWidget(self.test_source_combo)
        test_row.addWidget(self.test_button)
        form.addRow(test_row)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.status_label = QLabel("正在读取配置…")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("scrapePrimary")
        self.save_button.clicked.connect(self._save)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.save_button)
        root.addLayout(bottom)
        self._set_form_enabled(False)
        if settings is None:
            QTimer.singleShot(0, self._load)
        else:
            self._populate(settings)

    def _load(self) -> None:
        if not self._closing:
            self.tasks.start("settings-load", lambda context: ScrapeSettings.load())

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (*self._credentials, self.language_edit, self.proxy_edit,
                       self.timeout_spin, self.delay_spin, self.save_button, self.test_button):
            widget.setEnabled(enabled)

    def _populate(self, settings: ScrapeSettings) -> None:
        self._settings = replace(settings)
        for edit, value in zip(self._credentials, (settings.tmdb_api_key, settings.tmdb_token, settings.omdb_api_key)):
            edit.setText(value)
        self.language_edit.setText(settings.language)
        self.proxy_edit.setText(settings.proxy)
        self.timeout_spin.setValue(settings.timeout)
        self.delay_spin.setValue(settings.douban_delay)
        self._set_form_enabled(True)
        self.status_label.setText("配置仅用于本机刮削请求。")

    def _values(self) -> ScrapeSettings:
        return ScrapeSettings(
            tmdb_api_key=self.tmdb_key_edit.text().strip(),
            tmdb_token=self.tmdb_token_edit.text().strip(),
            omdb_api_key=self.omdb_key_edit.text().strip(),
            language=self.language_edit.text().strip() or "zh-CN",
            proxy=self.proxy_edit.text().strip(), timeout=self.timeout_spin.value(),
            douban_delay=self.delay_spin.value(),
        )

    def _toggle_credentials(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        for edit in self._credentials:
            edit.setEchoMode(mode)

    def _save(self) -> None:
        settings = self._values()
        try:
            settings.validate()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._settings = settings
        self._saving = True
        self._set_form_enabled(False)
        self.status_label.setText("正在保存设置…")
        def save(context):
            settings.save()
            return settings
        self.tasks.start("settings-save", save)

    def _test(self) -> None:
        settings, source = self._values(), self.test_source_combo.currentData()
        self.test_button.setEnabled(False)
        self.status_label.setText("正在测试连接，可取消并等待当前请求结束…")
        self._settings = settings
        self.tasks.start("connection-test", lambda context: self._connection_test(settings, source))

    @pyqtSlot(str, int, object)
    def _result(self, channel: str, generation: int, value: object) -> None:
        if channel == "settings-load":
            self._populate(value)
        elif channel == "settings-save":
            self._saving = False
            self._completion_result = QDialog.DialogCode.Accepted
            self.settings_saved.emit(value)
            self._closing = True
        elif channel == "connection-test":
            self.status_label.setText(str(value))
            self.test_button.setEnabled(True)

    @pyqtSlot(str, int, str)
    def _error(self, channel: str, generation: int, message: str) -> None:
        self._saving = False
        self._set_form_enabled(True)
        self.status_label.setText("操作失败：" + safe_message(message, self._settings))

    def _idle(self) -> None:
        if self._closing:
            super().done(self._completion_result)

    def done(self, result: int) -> None:
        if self.tasks.busy:
            self._completion_result = result
            self._closing = True
            self.tasks.cancel()
            self.status_label.setText("正在等待当前操作结束后关闭…")
        else:
            super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tasks.busy:
            self._closing = True
            self.tasks.cancel()
            self.status_label.setText("正在等待当前操作结束后关闭…")
            event.ignore()
        else:
            event.accept()
