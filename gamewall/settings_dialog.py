"""
游戏库设置对话框
数据源（Excel）、本地游戏目录、联网/刮削开关与海报缩放的可视化管理
"""
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QFrame, QCheckBox, QLineEdit,
    QSpinBox, QWidget,
)

from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

_TITLE_STYLE = "color: #333333;"
_DESC_STYLE = """
    QLabel {
        color: #666666;
        font-size: 13px;
        padding: 10px;
        background-color: #F0F7FF;
        border-left: 4px solid #007AFF;
        border-radius: 6px;
    }
"""
_LIST_STYLE = """
    QListWidget {
        background-color: #FFFFFF;
        border: 2px solid #E0E0E0;
        border-radius: 8px;
        padding: 8px;
        font-size: 13px;
        color: #333333;
    }
    QListWidget::item {
        padding: 10px;
        border-radius: 6px;
        margin-bottom: 4px;
    }
    QListWidget::item:selected {
        background-color: #E3F2FD;
        color: #007AFF;
        border: 2px solid #007AFF;
    }
"""
_BLUE_BTN = """
    QPushButton {
        background-color: #007AFF;
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 0 25px;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #0051D5; }
    QPushButton:pressed { background-color: #003DA5; }
"""
_GREEN_BTN = """
    QPushButton {
        background-color: #34C759;
        color: #FFFFFF;
        border: none;
        border-radius: 10px;
        padding: 0 28px;
        font-size: 14px;
    }
    QPushButton:hover { background-color: #2DA94C; }
    QPushButton:pressed { background-color: #268E40; }
"""
_RED_BTN = """
    QPushButton {
        background-color: #FFFFFF;
        color: #FF3B30;
        border: 2px solid #FF3B30;
        border-radius: 8px;
        padding: 0 25px;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #FF3B30; color: #FFFFFF; }
    QPushButton:pressed { background-color: #D62D20; }
"""
_GRAY_BTN = """
    QPushButton {
        background-color: #F5F5F5;
        color: #666666;
        border: 2px solid #E0E0E0;
        border-radius: 10px;
        padding: 0 28px;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #E0E0E0; color: #333333; }
"""


def _btn(text: str, style: str, height: int = 44,
         weight: QFont.Weight = QFont.Weight.Bold) -> QPushButton:
    b = QPushButton(text)
    b.setFont(QFont("Microsoft YaHei", 11, weight))
    b.setFixedHeight(height)
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    b.setStyleSheet(style)
    return b


class GameSettingsDialog(QDialog):
    """游戏库设置；三个底部按钮均先保存配置，再触发对应动作"""

    settings_saved = pyqtSignal()      # 仅保存（主窗口判断是否重载 Excel）
    enrich_requested = pyqtSignal()    # 保存后立即联网补全
    rescan_requested = pyqtSignal()    # 保存后重新扫描本地游戏

    def __init__(self, parent=None, config: ConfigManager = None):
        super().__init__(parent)
        self.config = config or ConfigManager()
        self.game_dirs = list(self.config.get_value("game_dirs", []) or [])
        self._init_ui()
        self._load_values()

    # ── UI ──
    def _init_ui(self):
        self.setWindowTitle("⚙️ 游戏库设置")
        self.setMinimumSize(680, 730)
        self.setModal(True)
        self.setStyleSheet("QDialog { background-color: #FFFFFF; }")

        main = QVBoxLayout(self)
        main.setContentsMargins(30, 22, 30, 22)
        main.setSpacing(10)

        main.addWidget(self._section_label("📊 数据源（游戏 Excel）"))
        excel_row = QHBoxLayout()
        self.excel_edit = QLineEdit()
        self.excel_edit.setReadOnly(True)
        self.excel_edit.setPlaceholderText("未选择，点击右侧按钮选择游戏资源库 Excel 文件")
        self.excel_edit.setStyleSheet("""
            QLineEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
            }
        """)
        excel_row.addWidget(self.excel_edit, 1)
        browse_btn = _btn("📂 选择 Excel", _BLUE_BTN)
        browse_btn.clicked.connect(self._choose_excel)
        excel_row.addWidget(browse_btn)
        main.addLayout(excel_row)

        main.addWidget(self._separator())
        main.addWidget(self._section_label("💾 本地游戏目录（扫描已安装游戏）"))
        main.addWidget(self._dirs_widget())

        main.addWidget(self._separator())
        main.addWidget(self._section_label("🌐 联网与刮削"))
        desc = QLabel("Steam 数据用于封面/简介/评分；游民星空与 IGN 为尽力而为，"
                      "失败时评分留空。")
        desc.setWordWrap(True)
        desc.setStyleSheet(_DESC_STYLE)
        main.addWidget(desc)
        self.network_check = QCheckBox("启用联网功能（总开关）")
        self.enrich_check = QCheckBox("Steam 数据自动补全（封面/简介/好评率）")
        self.gamersky_check = QCheckBox("游民星空评分刮削（尽力而为）")
        self.ign_check = QCheckBox("IGN 评分刮削（海外源，国内网络通常不可达）")
        for i, check in enumerate((self.network_check, self.enrich_check,
                                   self.gamersky_check, self.ign_check)):
            check.setFont(QFont("Microsoft YaHei", 11))
            main.addWidget(check)
            if i == 0:
                check.toggled.connect(self._on_network_toggled)

        main.addWidget(self._separator())
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._section_label("🖼️ 海报缩放"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 200)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setFixedWidth(110)
        self.scale_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
            }
        """)
        scale_row.addWidget(self.scale_spin)
        scale_row.addStretch(1)
        main.addLayout(scale_row)

        main.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        enrich_btn = _btn("⚡ 立即补全", _GREEN_BTN)
        enrich_btn.clicked.connect(lambda: self._apply_and_close(self.enrich_requested))
        rescan_btn = _btn("🔄 重新扫描", _BLUE_BTN)
        rescan_btn.clicked.connect(lambda: self._apply_and_close(self.rescan_requested))
        cancel_btn = _btn("取消", _GRAY_BTN)
        cancel_btn.clicked.connect(self.reject)
        save_btn = _btn("💾 保存并关闭", _GREEN_BTN)
        save_btn.clicked.connect(lambda: self._apply_and_close(self.settings_saved))
        bottom.addWidget(enrich_btn)
        bottom.addWidget(rescan_btn)
        bottom.addStretch(1)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(save_btn)
        main.addLayout(bottom)

    def _dirs_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.dir_list = QListWidget()
        self.dir_list.setMinimumHeight(110)
        self.dir_list.setStyleSheet(_LIST_STYLE)
        v.addWidget(self.dir_list)
        row = QHBoxLayout()
        add_btn = _btn("➕ 添加目录", _BLUE_BTN, height=38)
        add_btn.clicked.connect(self._add_dir)
        del_btn = _btn("🗑️ 删除选中", _RED_BTN, height=38)
        del_btn.clicked.connect(self._remove_dir)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        v.addLayout(row)
        return w

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        label.setStyleSheet(_TITLE_STYLE)
        return label

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #E0E0E0; margin: 4px 0;")
        return line

    # ── 数据加载 / 保存 ──
    def _load_values(self):
        self.excel_edit.setText(self.config.get_value("excel_path", "") or "")
        self._refresh_dirs()
        self.network_check.setChecked(self.config.get_value("network_enabled", True))
        self.enrich_check.setChecked(self.config.get_value("enable_enrichment", True))
        self.gamersky_check.setChecked(self.config.get_value("enable_gamersky_scraper", True))
        self.ign_check.setChecked(self.config.get_value("enable_ign_scraper", False))
        self.scale_spin.setValue(int(self.config.get_value("poster_scale", 100)))
        self._on_network_toggled(self.network_check.isChecked())

    def _save_values(self):
        self.config.set_value("excel_path", self.excel_edit.text().strip())
        self.config.set_value("game_dirs", self.game_dirs)
        self.config.set_value("network_enabled", self.network_check.isChecked())
        self.config.set_value("enable_enrichment", self.enrich_check.isChecked())
        self.config.set_value("enable_gamersky_scraper", self.gamersky_check.isChecked())
        self.config.set_value("enable_ign_scraper", self.ign_check.isChecked())
        self.config.set_value("poster_scale", self.scale_spin.value())
        self.config.save_config()
        logger.info("游戏库设置已保存")

    def _apply_and_close(self, signal):
        try:
            self._save_values()
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"无法保存设置：{e}")
            return
        signal.emit()
        self.accept()

    # ── 交互 ──
    def _on_network_toggled(self, on: bool):
        for check in (self.enrich_check, self.gamersky_check, self.ign_check):
            check.setEnabled(on)
            if not on:
                check.setChecked(False)

    def _choose_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择游戏资源库 Excel", "", "Excel 文件 (*.xlsx *.xlsm)")
        if path:
            self.excel_edit.setText(path)

    def _refresh_dirs(self):
        self.dir_list.clear()
        if not self.game_dirs:
            item = QListWidgetItem("📂 暂无本地游戏目录，点击【➕ 添加目录】开始扫描")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(Qt.GlobalColor.gray)
            self.dir_list.addItem(item)
        else:
            for path in self.game_dirs:
                self.dir_list.addItem(QListWidgetItem(f"📁 {path}"))

    def _add_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择本地游戏目录", "", QFileDialog.Option.ShowDirsOnly)
        if not folder:
            return
        if folder in self.game_dirs:
            QMessageBox.warning(self, "路径已存在", f"该目录已在列表中：\n{folder}")
            return
        if not Path(folder).exists():
            QMessageBox.critical(self, "路径无效", f"该目录不存在或无法访问：\n{folder}")
            return
        self.game_dirs.append(folder)
        self._refresh_dirs()

    def _remove_dir(self):
        row = self.dir_list.currentRow()
        if row < 0 or row >= len(self.game_dirs):
            QMessageBox.warning(self, "未选择目录", "请先选择要删除的游戏目录。")
            return
        path = self.game_dirs.pop(row)
        logger.info(f"删除游戏目录: {path}")
        self._refresh_dirs()
