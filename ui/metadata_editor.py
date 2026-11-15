"""电影资料编辑窗口：表单修改与后台原子提交，取消不产生写入。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from scraper.management import load_edit, save_edit
from scraper.scrape_persistence import read_ids
from ui.scrape_tasks import TaskRunner


SCALARS = [('title', '标题'), ('original_title', '原标题'), ('tagline', '标语'),
           ('year', '年份'), ('premiered', '上映日期'), ('runtime', '时长（分钟）'), ('set_name', '系列')]
MULTI = [('genres', '类型'), ('countries', '国家 / 地区'), ('directors', '导演'), ('tags', '自定义标签')]


class MetadataEditorDialog(QDialog):
    saved = pyqtSignal(list)
    operation_failed = pyqtSignal(str, str)

    def __init__(self, nfo_path: str, video_path: str = '', parent=None):
        super().__init__(parent)
        self.nfo_path = nfo_path
        self.setObjectName('metadataEditor')
        self.setWindowTitle('编辑电影资料')
        self.resize(1180, 850)
        self.setMinimumSize(920, 620)
        self.tasks = TaskRunner(self)
        self.tasks.result.connect(self._result)
        self.tasks.error.connect(self._error)
        self.tasks.idle.connect(self._idle)
        self.snapshot = None
        self._closing = False
        self._completion = QDialog.DialogCode.Rejected
        self._poster_data = None
        self._initial = {}
        self.fields = {}
        self._build_ui()
        self._load_video = video_path
        self.reload()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        self.path_label = QLineEdit(self.nfo_path)
        self.path_label.setReadOnly(True)
        root.addWidget(self.path_label)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        basic = QWidget()
        basic_layout = QHBoxLayout(basic)
        basic_layout.setContentsMargins(8, 10, 8, 6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, label in SCALARS[:3]:
            edit = QLineEdit()
            edit.setAccessibleName(label)
            self.fields[key] = edit
            form.addRow(label, edit)
        self.fields['plot'] = QPlainTextEdit()
        self.fields['plot'].setMinimumHeight(160)
        form.addRow('剧情', self.fields['plot'])
        for key, label in SCALARS[3:] + MULTI:
            edit = QLineEdit()
            edit.setAccessibleName(label)
            if key == 'premiered':
                edit.setPlaceholderText('YYYY-MM-DD')
            if (key, label) in MULTI:
                edit.setPlaceholderText('多项用 / 分隔')
            self.fields[key] = edit
            form.addRow(label, edit)
        self.ratings = {}
        self.vote_inputs = {}
        scores = QTableWidget(3, 3)
        scores.setHorizontalHeaderLabels(['来源', '评分（0–10）', '投票人数'])
        scores.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scores.verticalHeader().hide()
        scores.setMaximumHeight(155)
        for i, source in enumerate(('douban', 'imdb', 'tmdb')):
            label = QTableWidgetItem({'douban': '豆瓣', 'imdb': 'IMDb', 'tmdb': 'TMDB'}[source])
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            scores.setItem(i, 0, label)
            edit = QLineEdit()
            edit.setPlaceholderText('未取得')
            edit.setAccessibleName(source + '评分')
            votes = QSpinBox()
            votes.setRange(0, 2_147_483_647)
            votes.setAccessibleName(source + '评分人数')
            scores.setCellWidget(i, 1, edit)
            scores.setCellWidget(i, 2, votes)
            self.ratings[source], self.vote_inputs[source] = edit, votes
        form.addRow('评分', scores)
        scroll.setWidget(form_widget)
        basic_layout.addWidget(scroll, 1)
        art = QVBoxLayout()
        self.poster_info = QLabel('海报')
        art.addWidget(self.poster_info)
        self.poster = QLabel('暂无海报')
        self.poster.setObjectName('managementPoster')
        self.poster.setFixedSize(240, 360)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.addWidget(self.poster)
        self.poster_button = QPushButton('从本地选择海报…')
        self.poster_button.clicked.connect(self.choose_poster)
        art.addWidget(self.poster_button)
        self.poster_path = QLabel('')
        self.poster_path.setWordWrap(True)
        art.addWidget(self.poster_path)
        art.addStretch()
        art_widget = QWidget()
        art_widget.setLayout(art)
        art_widget.setFixedWidth(264)
        basic_layout.addWidget(art_widget)
        self.tabs.addTab(basic, '影视信息')
        cast = QWidget()
        cast_layout = QVBoxLayout(cast)
        self.actors = QTableWidget(0, 3)
        self.actors.setHorizontalHeaderLabels(['演员', '角色', '头像链接'])
        self.actors.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        cast_layout.addWidget(self.actors)
        controls = QHBoxLayout()
        add = QPushButton('添加演员')
        add.clicked.connect(lambda: self.actors.insertRow(self.actors.rowCount()))
        remove = QPushButton('移除选中演员')
        remove.clicked.connect(self.remove_actor)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        cast_layout.addLayout(controls)
        self.tabs.addTab(cast, '演职员')
        sources = QWidget()
        sources_form = QFormLayout(sources)
        self.ids = {}
        for source, label in [('douban', '豆瓣 ID / 链接'), ('imdb', 'IMDb ID / 链接'), ('tmdb', 'TMDB ID / 链接')]:
            edit = QLineEdit()
            self.ids[source] = edit
            sources_form.addRow(label, edit)
        self.tabs.addTab(sources, '来源链接')
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        self.tabs.addTab(self.files, '视频文件')
        self.status_label = QLabel('正在读取 NFO…')
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        self.reload_button = QPushButton('重新加载')
        self.reload_button.clicked.connect(self.reload)
        footer.addWidget(self.reload_button)
        footer.addStretch()
        self.cancel_button = QPushButton('取消')
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton('保存')
        self.save_button.setObjectName('scrapePrimary')
        self.save_button.clicked.connect(self.save)
        self.save_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self.tabs.setEnabled(False)

    def reload(self):
        if self.tasks.busy or self._closing:
            return
        self.tabs.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText('正在后台读取电影资料…')
        def load(context):
            snapshot = load_edit(self.nfo_path, self._load_video)
            context.checkpoint()
            return snapshot, self._poster_image(snapshot.movie.poster_path)
        self.tasks.start('read', load)

    @staticmethod
    def _poster_image(path):
        from PyQt6.QtGui import QImage
        from utils.poster_cache_manager import PosterCacheManager
        from utils.network_mode import is_offline_cache_only
        from utils.image_loader import _is_network_path
        if not path:
            return QImage()
        cache = PosterCacheManager()
        if not is_offline_cache_only() or not _is_network_path(path):
            original = QImage(path)
            if not original.isNull():
                return original
        image = cache.get_cached_image(path, 280, 420)
        return image or cache.get_cached_image(path, 280, 420, True) or QImage()

    def _values(self):
        result = {key: edit.toPlainText().strip() if isinstance(edit, QPlainTextEdit) else edit.text().strip()
                  for key, edit in self.fields.items()}
        for key, _ in MULTI:
            result[key] = [part.strip() for part in result[key].split('/') if part.strip()]
        return result

    def _result(self, channel, generation, value):
        if channel == 'read':
            self.snapshot, image = value
            movie = self.snapshot.movie
            self.setWindowTitle('编辑电影资料 · ' + movie.title)
            for key, edit in self.fields.items():
                value = getattr(movie, key, '')
                if isinstance(value, list):
                    value = ' / '.join(value)
                if isinstance(edit, QPlainTextEdit):
                    edit.setPlainText(value)
                else:
                    edit.setText(value)
            self._initial = self._values()
            self._initial_ratings = {}
            for source, edit in self.ratings.items():
                value = movie.ratings.get(source, movie.ratings.get('themoviedb') if source == 'tmdb' else None)
                text = str(value) if value is not None else ''
                edit.setText(text)
                self._initial_ratings[source] = text
                self.vote_inputs[source].setValue(max(0, min(2_147_483_647, self.snapshot.votes.get(source, 0))))
            self._initial_votes = {s: spin.value() for s, spin in self.vote_inputs.items()}
            self._initial_ids = read_ids(self.snapshot.root)
            for source, edit in self.ids.items():
                edit.setText(self._initial_ids.get(source, ''))
            self.actors.setRowCount(len(movie.actors))
            for i, actor in enumerate(movie.actors):
                for j, key in enumerate(('name', 'role', 'thumb')):
                    self.actors.setItem(i, j, QTableWidgetItem(getattr(actor, key)))
            self._initial_actors = [asdict(actor) for actor in movie.actors]
            self.files.setPlainText(f'视频：{self.snapshot.target.video_path}\n\nNFO：{self.nfo_path}'
                                    f'\n\n分辨率：{movie.resolution}\nHDR：{movie.hdr_type}'
                                    f'\n视频编码：{movie.video_codec}\n音频编码：{movie.audio_codec}')
            self._poster_data = None
            self.poster_path.setText(movie.poster_path or '尚未设置海报')
            self._set_poster(image)
            self.tabs.setEnabled(True)
            self.save_button.setEnabled(True)
            self.status_label.setText('仅保存修改的字段；保存前备份原文件，取消不会写入。')
        elif channel == 'poster-read':
            self._poster_data, image, filename = value
            self._set_poster(image)
            self.poster_path.setText(filename)
            self.status_label.setText('海报已选中，点击“保存”后才替换原文件。')
        elif channel == 'write':
            self.saved.emit([self.nfo_path])
            self._completion = QDialog.DialogCode.Accepted
            self._closing = True
            self.status_label.setText('保存成功')

    def _set_poster(self, image):
        if image.isNull():
            self.poster.clear()
            self.poster.setText('暂无可用海报')
            self.poster_info.setText('海报')
        else:
            self.poster.setPixmap(QPixmap.fromImage(image).scaled(self.poster.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                                  Qt.TransformationMode.SmoothTransformation))
            self.poster_info.setText(f'海报预览　{image.width()} × {image.height()}')

    def remove_actor(self):
        for row in sorted({index.row() for index in self.actors.selectedIndexes()}, reverse=True):
            self.actors.removeRow(row)

    def choose_poster(self):
        if self.tasks.busy:
            return
        filename, _ = QFileDialog.getOpenFileName(self, '选择海报', '', '图片 (*.jpg *.jpeg *.png *.webp)')
        if filename:
            def read(context):
                from pathlib import Path
                from PyQt6.QtGui import QImage
                from scraper.scrape_persistence import jpeg_bytes
                with Path(filename).open('rb') as stream:
                    data = jpeg_bytes(stream.read(15 * 1024 * 1024 + 1))
                return data, QImage.fromData(data), filename
            self.tasks.start('poster-read', read)
            self.save_button.setEnabled(False)

    @staticmethod
    def _identity(source, text):
        text = text.strip()
        if not text:
            return ''
        if '://' in text:
            from urllib.parse import urlsplit
            url = urlsplit(text)
            hosts = {'tmdb': {'themoviedb.org', 'www.themoviedb.org'}, 'imdb': {'imdb.com', 'www.imdb.com'},
                     'douban': {'movie.douban.com', 'www.douban.com', 'douban.com'}}
            pattern = {'tmdb': r'/movie/(\d+)(?:[-/]|$)', 'imdb': r'/title/(tt\d+)(?:/|$)', 'douban': r'/subject/(\d+)(?:/|$)'}[source]
            match = re.search(pattern, url.path) if url.hostname in hosts[source] else None
            if not match:
                raise ValueError(f'{source} 电影链接无效')
            text = match.group(1)
        if not re.fullmatch(r'tt\d+' if source == 'imdb' else r'\d+', text):
            raise ValueError(f'{source} 电影 ID 无效')
        return text

    def save(self):
        if not self.snapshot or self.tasks.busy or self._closing:
            return
        try:
            values = self._values()
            changes = {key: value for key, value in values.items() if value != self._initial[key]}
            if 'year' in changes and values['year'] and not re.fullmatch(r'\d{4}', values['year']):
                raise ValueError('年份应为四位数字')
            if 'premiered' in changes and values['premiered']:
                date.fromisoformat(values['premiered'])
            if 'runtime' in changes and values['runtime'] and not values['runtime'].isdigit():
                raise ValueError('时长应为非负整数分钟')
            ratings = {}
            for source, edit in self.ratings.items():
                text = edit.text().strip()
                if text != self._initial_ratings[source]:
                    ratings[source] = float(text) if text else None
            if ratings:
                changes['ratings'] = ratings
            changed_ids = {source: self._identity(source, edit.text()) for source, edit in self.ids.items()
                           if edit.text().strip() != self._initial_ids.get(source, '')}
            if changed_ids:
                changes['uniqueids'] = changed_ids
            actors = []
            for i in range(self.actors.rowCount()):
                actor = {key: (self.actors.item(i, j).text().strip() if self.actors.item(i, j) else '')
                         for j, key in enumerate(('name', 'role', 'thumb'))}
                if actor['name']:
                    actors.append(actor)
            if actors != self._initial_actors:
                changes['actors'] = actors
            votes = {s: spin.value() for s, spin in self.vote_inputs.items() if spin.value() != self._initial_votes[s]}
        except ValueError as exc:
            self.status_label.setText('请检查输入：' + str(exc))
            return
        snapshot, data = self.snapshot, self._poster_data
        self.tabs.setEnabled(False)
        self.save_button.setEnabled(False)
        self.reload_button.setEnabled(False)
        self.status_label.setText('正在备份并保存…')
        self.tasks.start('write', lambda context: save_edit(snapshot, changes, votes=votes, poster_data=data))

    def _error(self, channel, generation, message):
        self.status_label.setText('操作失败：' + message)
        self.tabs.setEnabled(self.snapshot is not None)
        self.save_button.setEnabled(self.snapshot is not None)
        self.reload_button.setEnabled(True)
        if channel == 'write':
            self.operation_failed.emit(self.nfo_path, message)

    def _idle(self):
        if self._closing:
            QDialog.done(self, self._completion)
        else:
            self.reload_button.setEnabled(True)
            self.save_button.setEnabled(self.snapshot is not None)

    def done(self, result):
        self._closing = True
        self.tasks.cancel()
        if not self.tasks.busy:
            QDialog.done(self, self._completion)

    def closeEvent(self, event):
        self.done(0)
        event.ignore() if self.tasks.busy else event.accept()
