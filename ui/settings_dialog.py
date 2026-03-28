"""
媒体库设置对话框
允许用户可视化地添加/删除电影目录
"""
import logging
from pathlib import Path
from typing import List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QWidget, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QCursor

from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    媒体库设置对话框
    提供可视化的路径管理界面
    """
    
    # 信号：配置已更新（需要重新扫描）
    settings_updated = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self.movie_paths = self.config.get_movie_paths().copy()  # 工作副本
        self.init_ui()
        self.load_current_paths()
    
    def init_ui(self):
        """初始化 UI"""
        self.setWindowTitle("⚙️ 媒体库设置")
        self.setMinimumSize(700, 500)
        self.setModal(True)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)
        
        # === 标题区域 ===
        title_label = QLabel("📁 电影目录管理")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1A1A1A;")
        main_layout.addWidget(title_label)
        
        # 说明文字
        desc_label = QLabel("添加本地硬盘或 NAS 上的电影文件夹，软件将自动扫描其中的 NFO 文件。")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 13px;
                padding: 10px;
                background-color: #F0F7FF;
                border-left: 4px solid #007AFF;
                border-radius: 6px;
            }
        """)
        main_layout.addWidget(desc_label)
        
        # === 路径列表区域 ===
        list_label = QLabel("当前电影目录：")
        list_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        list_label.setStyleSheet("color: #333333;")
        main_layout.addWidget(list_label)
        
        # 路径列表控件
        self.path_list = QListWidget()
        self.path_list.setMinimumHeight(200)
        self.path_list.setStyleSheet("""
            QListWidget {
                background-color: #FFFFFF;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                color: #333333;
            }
            QListWidget::item {
                padding: 12px;
                border-radius: 6px;
                margin-bottom: 5px;
            }
            QListWidget::item:selected {
                background-color: #E3F2FD;
                color: #007AFF;
                border: 2px solid #007AFF;
            }
            QListWidget::item:hover {
                background-color: #F5F5F5;
            }
        """)
        main_layout.addWidget(self.path_list)
        
        # === 操作按钮区域 ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # 添加目录按钮
        add_button = QPushButton("➕ 添加目录")
        add_button.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        add_button.setFixedHeight(45)
        add_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_button.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 0 25px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0051D5;
            }
            QPushButton:pressed {
                background-color: #003DA5;
            }
        """)
        add_button.clicked.connect(self.add_path)
        button_layout.addWidget(add_button)
        
        # 删除目录按钮
        remove_button = QPushButton("🗑️ 删除选中")
        remove_button.setFont(QFont("Microsoft YaHei", 11))
        remove_button.setFixedHeight(45)
        remove_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        remove_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #FF3B30;
                border: 2px solid #FF3B30;
                border-radius: 8px;
                padding: 0 25px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FF3B30;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: #D62D20;
            }
        """)
        remove_button.clicked.connect(self.remove_path)
        button_layout.addWidget(remove_button)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        # === 分隔线 ===
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #E0E0E0; margin: 10px 0;")
        main_layout.addWidget(separator)
        
        # === 底部确认按钮 ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(15)
        
        # 取消按钮
        cancel_button = QPushButton("取消")
        cancel_button.setFont(QFont("Microsoft YaHei", 12))
        cancel_button.setFixedHeight(50)
        cancel_button.setFixedWidth(120)
        cancel_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #F5F5F5;
                color: #666666;
                border: 2px solid #E0E0E0;
                border-radius: 10px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #E0E0E0;
                color: #333333;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        
        # 保存并扫描按钮
        save_button = QPushButton("💾 保存并重新扫描")
        save_button.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        save_button.setFixedHeight(50)
        save_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_button.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 0 30px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #0051D5;
            }
            QPushButton:pressed {
                background-color: #003DA5;
            }
        """)
        save_button.clicked.connect(self.save_settings)
        
        bottom_layout.addStretch()
        bottom_layout.addWidget(cancel_button)
        bottom_layout.addWidget(save_button)
        
        main_layout.addLayout(bottom_layout)
        
        # 设置对话框样式
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
            }
        """)
    
    def load_current_paths(self):
        """加载当前配置的路径到列表"""
        self.path_list.clear()
        
        if not self.movie_paths:
            # 空状态提示
            empty_item = QListWidgetItem("📂 暂无配置的电影目录，点击上方【➕ 添加目录】开始")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选中
            empty_item.setForeground(Qt.GlobalColor.gray)
            self.path_list.addItem(empty_item)
        else:
            for path in self.movie_paths:
                item = QListWidgetItem(f"📁 {path}")
                self.path_list.addItem(item)
    
    def add_path(self):
        """添加新的电影目录"""
        # 打开文件夹选择对话框
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择电影目录",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not folder:
            return
        
        # 检查是否已存在
        if folder in self.movie_paths:
            QMessageBox.warning(
                self,
                "路径已存在",
                f"该目录已在列表中：\n{folder}"
            )
            return
        
        # 验证路径是否存在
        if not Path(folder).exists():
            QMessageBox.critical(
                self,
                "路径无效",
                f"该目录不存在或无法访问：\n{folder}"
            )
            return
        
        # 添加到列表
        self.movie_paths.append(folder)
        logger.info(f"添加电影目录: {folder}")
        
        # 刷新列表显示
        self.load_current_paths()
    
    def remove_path(self):
        """删除选中的电影目录"""
        current_item = self.path_list.currentItem()
        
        if not current_item:
            QMessageBox.warning(
                self,
                "未选择目录",
                "请先选择要删除的电影目录。"
            )
            return
        
        # 提取路径（去掉前面的图标）
        path_text = current_item.text()
        if path_text.startswith("📁 "):
            path = path_text[2:].strip()
        else:
            return
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要移除此目录吗？\n{path}\n\n（不会删除实际文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if path in self.movie_paths:
                self.movie_paths.remove(path)
                logger.info(f"删除电影目录: {path}")
                self.load_current_paths()
    
    def save_settings(self):
        """保存设置并通知主窗口重新扫描"""
        try:
            # 更新配置管理器
            self.config.set_movie_paths(self.movie_paths)
            
            # 保存到 config.json
            self.config.save_config()
            
            logger.info(f"媒体库设置已保存，共 {len(self.movie_paths)} 个目录")
            
            # 发射信号通知主窗口
            self.settings_updated.emit()
            
            # 关闭对话框
            self.accept()
            
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            QMessageBox.critical(
                self,
                "保存失败",
                f"无法保存设置：{str(e)}"
            )
