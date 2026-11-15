"""电影状态表：显示与排序分离，所有操作按路径身份映射。"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor

from scraper.management import ManagementRow

HEADERS = ['标题', '年份', '上映时间', '文件名', '豆瓣', 'IMDb', 'TMDB', '分辨率', 'HDR', '新增', '海报', '字幕', '刮削状态', '缺失信息']
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class MovieTableModel(QAbstractTableModel):
    def __init__(self, rows: list[ManagementRow] | None = None, parent=None):
        super().__init__(parent)
        self.rows = list(rows or [])

    def set_rows(self, rows: list[ManagementRow]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row, col = self.rows[index.row()], index.column()
        movie = row.movie
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 3:
                return str(row.target.video_path)
            if col == 10:
                return ('最近扫描原文件：存在' if row.poster_exists else '最近扫描原文件：不存在') if row.poster_exists is not None else '尚未检查原海报；离线缓存不等于 NAS 原文件存在'
            if col == 11:
                return f'检测到 {row.subtitle_count} 组字幕（NFO 内嵌轨 + 同名外挂）；' + ('NFO 已记录内嵌字幕' if row.subtitle_known else '内嵌字幕未知，未探测视频流')
            if col in (7, 8) and row.inferred_tech:
                return '部分技术参数根据文件名推测，未探测视频流'
            return row.message or row.target.error or ('缺少：' + '、'.join(row.missing) if row.missing else '现有资料齐全')
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if col in (0, 3, 12, 13) else Qt.AlignmentFlag.AlignHCenter))
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 12 and row.state == '失败':
                return QColor('#B42318')
            if col == 9 and row.is_new:
                return QColor('#1768AF')
            if col == 10 and row.poster_exists is not None:
                return QColor('#26764C' if row.poster_exists else '#A0392B')
        values = [movie.title or row.target.title, movie.year, movie.premiered, row.target.video_path.name,
                  row.score('douban'), row.score('imdb'), row.score('tmdb'), movie.resolution,
                  movie.hdr_type, '是' if row.is_new else '否',
                  '✓' if row.poster_exists is True else ('✕' if row.poster_exists is False else '—'),
                  str(row.subtitle_count) if row.subtitle_count else '未知', row.state, '、'.join(row.missing)]
        value = values[col]
        if role == SORT_ROLE:
            if col in (1, 4, 5, 6):
                try:
                    return float(value) if value is not None else -1.0
                except ValueError:
                    return -1.0
            if col == 9:
                return int(row.is_new)
            if col == 10:
                return -1 if row.poster_exists is None else int(row.poster_exists)
            if col == 11:
                return row.subtitle_count
            return str(value or '').casefold()
        if role == Qt.ItemDataRole.DisplayRole:
            if col in (4, 5, 6):
                return f'{value:.1f}' if value is not None else '—'
            return value or '—'
        return None


class MovieFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ''
        self.mode = 'all'
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_query(self, query: str) -> None:
        self.query = query.strip().casefold()
        self.invalidateFilter()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, parent):
        row = self.sourceModel().rows[source_row]
        if self.query and self.query not in ' '.join([row.movie.title, row.movie.original_title, str(row.target.video_path)]).casefold():
            return False
        return {'all': True, 'new': row.is_new, 'missing': not row.is_new and bool(row.missing),
                'douban': row.douban_missing, 'failed': row.state == '失败',
                'existing': not row.is_new}.get(self.mode, True)
