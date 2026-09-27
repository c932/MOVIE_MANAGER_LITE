"""
游戏资料弹窗

- SteamSearchDialog：手动搜索 Steam，从候选列表中挑选匹配项
- GameInfoEditDialog：手动编辑简介与海报 URL，或从 Steam 重新拉取资料
"""
import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QLineEdit, QPlainTextEdit, QDialogButtonBox,
)

from gamewall import steam_client

logger = logging.getLogger(__name__)

_INPUT_STYLE = """
    QLineEdit, QPlainTextEdit {
        border: 1px solid #CED4DA; border-radius: 6px;
        padding: 6px 10px; font-size: 12px; background-color: white;
    }
    QLineEdit:focus, QPlainTextEdit:focus { border-color: #007AFF; }
"""

_BTN_STYLE = """
    QPushButton {
        background-color: #007AFF; color: white; border: none;
        border-radius: 6px; padding: 8px 16px; font-size: 12px;
    }
    QPushButton:hover { background-color: #0066D6; }
    QPushButton:disabled { background-color: #ADB5BD; }
"""


class _SearchWorker(QThread):
    """后台 Steam 搜索线程"""
    result = pyqtSignal(list, str)   # (items, err)

    def __init__(self, term: str, parent=None):
        super().__init__(parent)
        self._term = term

    def run(self):
        try:
            items, err = steam_client.search_steam(self._term)
        except Exception as e:
            logger.warning(f"Steam 搜索异常: {e}")
            items, err = [], str(e)
        self.result.emit(items, err)


class SteamSearchDialog(QDialog):
    """手动搜索 Steam 并选择匹配项。

    用法：
        dlg = SteamSearchDialog(parent, game)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_appid:
            ...  # dlg.selected_appid / dlg.selected_name
    """

    def __init__(self, parent=None, game=None):
        super().__init__(parent)
        self.selected_appid = 0
        self.selected_name = ""
        self._worker = None

        self.setWindowTitle("搜索匹配 Steam")
        self.setMinimumSize(480, 420)
        self.setStyleSheet("QDialog { background-color: #FFFFFF; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("输入游戏名搜索 Steam，从候选中双击选择正确的匹配：")
        title.setStyleSheet("color: #333333;")
        title.setWordWrap(True)
        layout.addWidget(title)

        search_row = QHBoxLayout()
        self.term_edit = QLineEdit()
        default_term = ""
        if game is not None:
            default_term = game.title_cn or game.title_en or game.raw_name
        self.term_edit.setText(default_term)
        self.term_edit.setStyleSheet(_INPUT_STYLE)
        self.term_edit.returnPressed.connect(self._do_search)
        search_row.addWidget(self.term_edit, 1)

        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.search_btn.setStyleSheet(_BTN_STYLE)
        self.search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.result_list = QListWidget()
        self.result_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #CED4DA; border-radius: 6px; font-size: 12px;
            }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background-color: #E3F0FF; color: #007AFF; }
        """)
        self.result_list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self.result_list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if default_term:
            self._do_search()

    def _do_search(self):
        term = self.term_edit.text().strip()
        if not term:
            self.status_label.setText("请输入搜索词")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"正在搜索「{term}」…")
        self.result_list.clear()
        worker = _SearchWorker(term, parent=self)
        worker.result.connect(self._on_result)
        worker.finished.connect(lambda: self.search_btn.setEnabled(True))
        self._worker = worker
        worker.start()

    def _on_result(self, items, err):
        if not items:
            self.status_label.setText(f"未找到候选{f'：{err}' if err else ''}")
            return
        self.status_label.setText(f"找到 {len(items)} 个候选，双击选择：")
        for it in items:
            entry = QListWidgetItem(f"{it['name']}  (appid: {it['appid']})")
            entry.setData(Qt.ItemDataRole.UserRole, it)
            self.result_list.addItem(entry)

    def _accept_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.selected_appid = data["appid"]
            self.selected_name = data["name"]
            self.accept()

    def _on_accept(self):
        item = self.result_list.currentItem()
        if item is not None:
            self._accept_item(item)
        else:
            QMessageBox.information(self, "未选择", "请先从候选列表中选择一个匹配项")


class _FetchWorker(QThread):
    """后台拉取 Steam 详情+评价线程"""
    result = pyqtSignal(dict, str)   # (fields, err)

    def __init__(self, appid: int, parent=None):
        super().__init__(parent)
        self._appid = appid

    def run(self):
        fields = {}
        try:
            details, err = steam_client.fetch_appdetails(self._appid)
            if err:
                self.result.emit({}, f"详情拉取失败：{err}")
                return
            fields.update(details or {})
            reviews, err = steam_client.fetch_appreviews(self._appid)
            if err:
                self.result.emit(fields, f"评价拉取失败：{err}")
                return
            fields.update(reviews or {})
            self.result.emit(fields, "")
        except Exception as e:
            logger.warning(f"Steam 拉取异常: {e}")
            self.result.emit(fields, str(e))


class GameInfoEditDialog(QDialog):
    """手动编辑游戏简介与海报 URL；也可一键从 Steam 重新拉取全部资料。

    用法：
        dlg = GameInfoEditDialog(parent, game)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            desc, header = dlg.result_values()
            if dlg.steam_fields:   # 用户点了「从 Steam 重新拉取」
                fields = dlg.steam_fields
    """

    def __init__(self, parent=None, game=None):
        super().__init__(parent)
        self.game = game
        self.steam_fields = None   # 「从 Steam 重新拉取」成功后的完整字段
        self._worker = None

        self.setWindowTitle("编辑游戏资料")
        self.setMinimumSize(560, 480)
        self.setStyleSheet("QDialog { background-color: #FFFFFF; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        name_label = QLabel(f"游戏：{game.display_title() if game else ''}")
        name_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        name_label.setStyleSheet("color: #212529;")
        layout.addWidget(name_label)

        layout.addWidget(self._label("游戏简介："))
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlainText(getattr(game, "description", "") if game else "")
        self.desc_edit.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self.desc_edit, 1)

        layout.addWidget(self._label("海报/头图 URL："))
        self.header_edit = QLineEdit()
        self.header_edit.setText(getattr(game, "header_image", "") if game else "")
        self.header_edit.setPlaceholderText("https://…（留空则仅使用 appid 竖版海报）")
        self.header_edit.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self.header_edit)

        appid = getattr(game, "steam_appid", 0) if game else 0
        self.fetch_btn = QPushButton(f"🔄 从 Steam 重新拉取全部资料（appid: {appid}）")
        self.fetch_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.fetch_btn.setStyleSheet(_BTN_STYLE)
        self.fetch_btn.setEnabled(appid > 0)
        self.fetch_btn.clicked.connect(self._fetch_from_steam)
        layout.addWidget(self.fetch_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6C757D; font-size: 11px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #333333; font-size: 12px;")
        return lbl

    def _fetch_from_steam(self):
        appid = getattr(self.game, "steam_appid", 0) if self.game else 0
        if not appid:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.fetch_btn.setEnabled(False)
        self.status_label.setText(f"正在从 Steam 拉取 appid {appid} 的资料…")
        worker = _FetchWorker(appid, parent=self)
        worker.result.connect(self._on_fetched)
        worker.finished.connect(lambda: self.fetch_btn.setEnabled(True))
        self._worker = worker
        worker.start()

    def _on_fetched(self, fields, err):
        if not fields:
            self.status_label.setText(f"拉取失败：{err}")
            return
        self.steam_fields = fields
        if fields.get("description"):
            self.desc_edit.setPlainText(fields["description"])
        if fields.get("header_image"):
            self.header_edit.setText(fields["header_image"])
        note = "已拉取最新资料，保存后生效"
        if err:
            note += f"（部分失败：{err}）"
        self.status_label.setText(note)

    def result_values(self):
        return (self.desc_edit.toPlainText().strip(), self.header_edit.text().strip())

    def _on_save(self):
        self.accept()
