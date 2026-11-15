"""管理页只读详情；海报读取在后台，快速切换后旧响应失效。"""
from __future__ import annotations

from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QTextBrowser

from scraper.management import ManagementRow
from ui.scrape_tasks import TaskRunner


class MovieInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('managementInspector')
        self.current_row = None
        self.tasks = TaskRunner(self)
        self.tasks.result.connect(self._result)
        self.tasks.error.connect(lambda *args: self.poster.setText('海报无法读取'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        self.title = QLabel('请选择电影')
        self.title.setObjectName('managementMovieTitle')
        self.title.setWordWrap(True)
        self.original = QLabel('')
        self.original.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.original)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        information = QWidget()
        info_layout = QVBoxLayout(information)
        info_layout.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.poster = QLabel('暂无海报')
        self.poster.setObjectName('managementPoster')
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster.setFixedSize(160, 240)
        self.summary = QTextBrowser()
        self.summary.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.summary.setOpenExternalLinks(True)
        top.addWidget(self.poster, alignment=Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.summary, 1)
        info_layout.addLayout(top)
        ratings = QHBoxLayout()
        self.rating_values = {}
        from ui.detail_panel import MovieDetailPanel
        for source, label in [('douban', '豆瓣'), ('imdb', 'IMDb'), ('tmdb', 'TMDB')]:
            column = QVBoxLayout()
            logo = MovieDetailPanel._create_rating_logo(self, source)
            number = QLabel('—')
            number.setAccessibleName(label + '评分')
            number.setObjectName('managementScore')
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)
            column.addWidget(number)
            ratings.addLayout(column)
            self.rating_values[source] = number
        info_layout.addLayout(ratings)
        self.plot = QTextBrowser()
        self.plot.setAccessibleName('电影简介和缺失信息')
        info_layout.addWidget(self.plot, 1)
        self.tabs.addTab(information, '影视信息')
        self.cast = QTextBrowser()
        self.tabs.addTab(self.cast, '演职员')
        self.files = QTextBrowser()
        self.tabs.addTab(self.files, '视频文件')

    def show_row(self, row: ManagementRow | None) -> None:
        self.tasks.invalidate('poster')
        self.current_row = row
        self.poster.clear()
        self.poster.setText('暂无海报')
        if row is None:
            self.title.setText('请选择电影')
            self.original.clear()
            for widget in (self.summary, self.plot, self.cast, self.files):
                widget.clear()
            for number in self.rating_values.values():
                number.setText('—')
            return
        movie = row.movie
        self.title.setText(movie.title or row.target.title)
        self.original.setText(movie.original_title)
        details = [('年份', movie.year), ('上映日期', movie.premiered), ('时长', movie.runtime + ' 分钟' if movie.runtime else ''),
                   ('类型', ' / '.join(movie.genres)), ('国家 / 地区', ' / '.join(movie.countries)),
                   ('导演', ' / '.join(movie.directors)), ('系列', movie.set_name)]
        html = ''.join(f'<p><b>{label}</b><br>{escape(str(value or "—"))}</p>' for label, value in details)
        for source, identity, url in [('IMDb', movie.imdb_id, f'https://www.imdb.com/title/{movie.imdb_id}/'),
                                       ('TMDB', movie.tmdb_id, f'https://www.themoviedb.org/movie/{movie.tmdb_id}'),
                                       ('豆瓣', movie.douban_url, movie.douban_url)]:
            if identity and url.startswith('https://'):
                html += f'<p>{source}：<a href="{escape(url, quote=True)}">{escape(identity)}</a></p>'
        self.summary.setHtml(html)
        for source, label in self.rating_values.items():
            value = row.score(source)
            label.setText(f'{value:.1f}' if value is not None else '—')
        self.plot.setPlainText('剧情简介\n\n' + (movie.plot or '尚无简介，可通过“搜索&刮削”补充。') +
                               '\n\n状态：' + row.state + ('\n缺少：' + '、'.join(row.missing) if row.missing else '') +
                               ('\n' + (row.message or row.target.error) if row.message or row.target.error else ''))
        self.cast.setHtml('<h3>导演</h3><p>' + escape(' / '.join(movie.directors) or '—') + '</p><h3>演员</h3>' +
                          ''.join(f'<p>{escape(a.name)}　{escape(a.role)}</p>' for a in movie.actors))
        self.files.setPlainText(f'视频\n{row.target.video_path}\n\nNFO\n{row.target.nfo_path}\n\n海报\n{movie.poster_path or "未取得"}'
                               f'\n\n分辨率：{movie.resolution or "未知"}\nHDR：{movie.hdr_type or "未知"}'
                               f'\n视频编码：{movie.video_codec or "未知"}\n音频编码：{movie.audio_codec or "未知"}'
                               f'\n字幕：{row.subtitle_count} 组（' + ('有内嵌轨记录）' if row.subtitle_known else '内嵌未知）') +
                               ('\n部分参数由文件名推测' if row.inferred_tech else ''))
        if movie.poster_path:
            self.poster.setText('正在加载海报…')
            path = movie.poster_path
            def load(context):
                from utils.poster_cache_manager import PosterCacheManager
                from utils.network_mode import is_offline_cache_only
                from utils.image_loader import _load_and_scale_image
                cache = PosterCacheManager()
                image = cache.get_cached_image(path, 280, 420)
                if image is None and not is_offline_cache_only():
                    context.checkpoint()
                    original = _load_and_scale_image(path, 280, 420)
                    if not original.isNull():
                        image = original
                        cache.save_to_cache_from_image(path, 280, 420, image)
                        cache.flush_index()
                if image is None:
                    image = cache.get_cached_image(path, 280, 420, True)
                return image or QImage()
            self.tasks.start('poster', load)

    def _result(self, channel, generation, image):
        if channel == 'poster':
            if image.isNull():
                self.poster.setText('暂无可用海报缓存')
            else:
                self.poster.setPixmap(QPixmap.fromImage(image).scaled(self.poster.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                                       Qt.TransformationMode.SmoothTransformation))
