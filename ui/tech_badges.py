"""从共享资源绘制技术图标，保持比例并适配高 DPI。"""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from utils.media_badges import asset_root, media_badges


class TechBadges(QWidget):
    def __init__(self, resolution: str = '', hdr_type: str = '', *, height: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('techBadges')
        self.icon_height = height
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.set_values(resolution, hdr_type)

    def set_values(self, resolution: str, hdr_type: str) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for badge in media_badges(resolution, hdr_type):
            label = QLabel(self)
            label.setObjectName('mediaBadge')
            label.setProperty('badgeKey', badge.key)
            label.setToolTip(badge.title)
            label.setAccessibleName(badge.title)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if badge.file:
                width = round(self.icon_height * {'hdr': 800 / 379, 'dolbyvision': 1}.get(badge.key, 220 / 170))
                pixmap = QIcon(str(asset_root() / badge.file)).pixmap(QSize(width, self.icon_height), self.devicePixelRatioF())
                if not pixmap.isNull():
                    label.setPixmap(pixmap)
                    label.setFixedSize(width, self.icon_height)
                else:
                    label.setText(badge.title)
            else:
                label.setText(badge.title)
            self.row.addWidget(label)
        self.row.addStretch()
        # 可见性由父布局管理。详情页创建时尚无父窗口，提前 show 会闪现顶层小窗。
