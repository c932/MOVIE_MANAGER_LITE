"""桌面字幕候选、原站验证与保存确认。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from models.movie import Movie
from ui.scrape_tasks import TaskRunner
from utils.subtitle_sources import SOURCES, SiteCheck, download_subtitles, search_subtitles
from utils.subtitles import (
    IMPORT_EXTENSIONS, LANGUAGES, MAX_PACKAGE, SubtitleFile, archive_subtitles,
    detect_subtitles, save_subtitle, subtitle_summary, sync_subtitles,
)


class SubtitleDialog(QDialog):
    def __init__(self, movie: Movie, parent=None):
        super().__init__(parent)
        self.movie = movie
        self.video = Path(movie.video_path)
        self.nfo = Path(movie.nfo_path)
        self.tracks = movie.subtitles
        self.changed = False
        self.draft: list[SubtitleFile] = []
        self.runner = TaskRunner(self)
        self.runner.result.connect(self._result)
        self.runner.error.connect(self._error)
        self.runner.idle.connect(self._update_buttons)
        self.setWindowTitle(f'{movie.title} · 字幕')
        self.resize(720, 500)

        layout = QVBoxLayout(self)
        self.local = QLabel(subtitle_summary(self.tracks))
        layout.addWidget(self.local)
        tools = QHBoxLayout()
        self.detect = QPushButton('检测本地字幕')
        self.sync = QPushButton('同步字幕到 NFO')
        self.load = QPushButton('导入字幕或压缩包')
        for button in (self.detect, self.sync, self.load):
            tools.addWidget(button)
        layout.addLayout(tools)

        search = QHBoxLayout()
        self.query = QLineEdit(movie.title)
        self.query.setAccessibleName('字幕搜索')
        self.query.setMaxLength(300)
        self.search = QPushButton('搜索字幕')
        self.search.setAutoDefault(False)
        search.addWidget(self.query, 1)
        search.addWidget(self.search)
        layout.addLayout(search)

        self.status = QLabel('可按片名或发行版搜索，候选按电影文件名排序。')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.results = QListWidget()
        self.results.setAccessibleName('字幕候选')
        layout.addWidget(self.results, 1)

        actions = QHBoxLayout()
        self.download = QPushButton('下载候选')
        self.browse = QPushButton('打开所选原站')
        actions.addWidget(self.download)
        actions.addWidget(self.browse)
        layout.addLayout(actions)

        preview = QHBoxLayout()
        self.files = QComboBox()
        self.files.setAccessibleName('压缩包字幕文件')
        self.languages = QComboBox()
        self.languages.setAccessibleName('字幕语言')
        for code, name in LANGUAGES.items():
            self.languages.addItem(name, code)
        self.save = QPushButton('保存到电影目录')
        self.close_button = QPushButton('关闭')
        preview.addWidget(self.files, 1)
        preview.addWidget(self.languages)
        preview.addWidget(self.save)
        preview.addWidget(self.close_button)
        layout.addLayout(preview)

        self.detect.clicked.connect(lambda: self._start('detect', '正在读取本地字幕…',
                                                        lambda: detect_subtitles(self.video, self.nfo)))
        self.sync.clicked.connect(lambda: self._start('sync', '正在同步字幕记录…',
                                                      lambda: sync_subtitles(self.video, self.nfo)))
        self.load.clicked.connect(self._import)
        self.search.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.download.clicked.connect(self._download)
        self.browse.clicked.connect(self._browse)
        self.results.currentItemChanged.connect(self._update_buttons)
        self.files.currentIndexChanged.connect(self._select_track)
        self.save.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)
        self._update_buttons()

    def _update_buttons(self, *_):
        busy = self.runner.busy
        for button in (self.detect, self.sync, self.load, self.search, self.query, self.close_button):
            button.setEnabled(not busy)
        current = self.results.currentItem()
        has_item = current is not None and bool(current.data(Qt.ItemDataRole.UserRole).get('id'))
        self.download.setEnabled(not busy and has_item)
        self.browse.setEnabled(not busy and current is not None)
        for widget in (self.files, self.languages, self.save):
            widget.setEnabled(not busy and bool(self.draft))

    def reject(self):
        if not self.runner.busy:
            super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def _start(self, channel, label, action):
        if self.runner.busy:
            return
        self.status.setText(label)
        self.runner.start(channel, lambda context: action())
        self._update_buttons()

    def _search(self):
        keyword = self.query.text().strip()
        if keyword:
            original = self.movie.original_title if keyword == self.movie.title else ''
            self._start('search', '正在搜索三个字幕站…',
                        lambda: search_subtitles(keyword, self.video.stem, original))

    def _download(self):
        item = self.results.currentItem().data(Qt.ItemDataRole.UserRole)
        def download():
            try:
                return download_subtitles(item['source'], item['id'], item['language'])
            except SiteCheck as exc:
                return {'page': item['page'], 'error': str(exc)}
        self._start('download', '正在下载并检查字幕…', download)

    def _browse(self):
        item = self.results.currentItem().data(Qt.ItemDataRole.UserRole)
        QDesktopServices.openUrl(QUrl(item['page']))

    def _import(self):
        extensions = ' '.join('*' + value for value in sorted(IMPORT_EXTENSIONS))
        filename, _ = QFileDialog.getOpenFileName(self, '导入字幕', '', f'字幕和压缩包 ({extensions})')
        if filename:
            path = Path(filename)
            def load():
                with path.open('rb') as stream:
                    return archive_subtitles(path.name, stream.read(MAX_PACKAGE + 1))
            self._start('import', '正在读取导入文件…', load)

    def _select_track(self, index: int):
        if 0 <= index < len(self.draft):
            self.languages.setCurrentIndex(self.languages.findData(self.draft[index].language))

    def _save(self):
        track = self.draft[self.files.currentIndex()]
        language = self.languages.currentData()
        def save():
            filename = save_subtitle(self.video, self.nfo, track, language)
            return detect_subtitles(self.video, self.nfo), filename.name
        self._start('write', '正在保存字幕和 NFO…', save)

    def _result(self, channel, generation, value):
        if channel == 'search':
            self.results.clear()
            for item in value['items']:
                match = '文件名匹配' if item['score'] == 100 else f'匹配度 {item["score"]}%'
                row = QListWidgetItem(f'{item["release"]}\n{SOURCES[item["source"]][0]} · {LANGUAGES[item["language"]]} · {match}')
                row.setData(Qt.ItemDataRole.UserRole, item)
                self.results.addItem(row)
            for source in value['sources']:
                if source['message'] or not value['items']:
                    row = QListWidgetItem(f'{source["name"]} · {source["message"] or "在原站搜索"}')
                    row.setData(Qt.ItemDataRole.UserRole, {'page': source['url']})
                    self.results.addItem(row)
            self.status.setText(f'找到 {len(value["items"])} 条候选，可打开原站验证后导入下载文件。')
        elif channel in {'download', 'import'}:
            if isinstance(value, dict):
                self.status.setText(value['error'] + '。在浏览器完成后，导入下载的文件。')
                QDesktopServices.openUrl(QUrl(value['page']))
                return
            self.draft = value
            self.files.clear()
            self.files.addItems([track.name for track in value])
            self.status.setText('请选择字幕文件和语言，再保存到电影目录。')
        else:
            self.tracks, filename = value if channel == 'write' else (value, '')
            self.changed = True
            self.local.setText(subtitle_summary(self.tracks))
            self.local.setToolTip('\n'.join(
                f'{track["file"] or "内嵌字幕"} · {LANGUAGES[track["language"]]}' for track in self.tracks))
            if channel == 'write':
                self.draft = []
                self.files.clear()
            self.status.setText(f'已保存 {filename}' if filename else
                                '字幕记录已同步到 NFO' if channel == 'sync' else '已更新本地字幕状态')

    def _error(self, _channel, _generation, message):
        self.status.setText(message)
