"""
手动匹配对话框 - 用于手动输入豆瓣ID或URL
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ManualMatchDialog(QDialog):
    """
    手动匹配对话框
    
    用于让用户手动输入豆瓣电影ID或URL
    """
    
    def __init__(self, movie_title: str, year: str, nfo_path: str, parent=None):
        super().__init__(parent)
        self.movie_title = movie_title
        self.year = year
        self.nfo_path = nfo_path
        self.douban_id = None
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("手动匹配豆瓣电影")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("🔍 无法自动匹配，需要手动输入")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #DC3545; margin-bottom: 8px;")
        layout.addWidget(title_label)
        
        # 电影信息
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(6)
        
        movie_label = QLabel(f"<b>电影标题：</b>{self.movie_title}")
        movie_label.setWordWrap(True)
        info_layout.addWidget(movie_label)
        
        year_label = QLabel(f"<b>年份：</b>{self.year or '未知'}")
        info_layout.addWidget(year_label)
        
        path_label = QLabel(f"<b>NFO路径：</b>{self.nfo_path}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color: #6C757D; font-size: 10px;")
        info_layout.addWidget(path_label)
        
        layout.addWidget(info_frame)
        
        # 说明文字
        instruction_label = QLabel(
            "请在豆瓣网站搜索该电影，然后粘贴完整网址或电影ID："
        )
        instruction_label.setWordWrap(True)
        instruction_label.setStyleSheet("margin-top: 8px; color: #495057;")
        layout.addWidget(instruction_label)
        
        # 示例
        example_label = QLabel(
            "• 完整网址示例：https://movie.douban.com/subject/1292052/\n"
            "• 电影ID示例：1292052"
        )
        example_label.setStyleSheet("color: #6C757D; font-size: 10px; margin-bottom: 8px;")
        layout.addWidget(example_label)
        
        # 输入框
        input_label = QLabel("豆瓣网址或ID：")
        input_label.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        layout.addWidget(input_label)
        
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("粘贴豆瓣网址或输入纯数字ID...")
        self.input_edit.setFont(QFont("Microsoft YaHei", 10))
        self.input_edit.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 2px solid #CED4DA;
                border-radius: 6px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #007AFF;
            }
        """)
        layout.addWidget(self.input_edit)
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addStretch()
        
        skip_btn = QPushButton("⏭ 跳过此电影")
        skip_btn.setFixedHeight(36)
        skip_btn.setFont(QFont("Microsoft YaHei", 9))
        skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background-color: #5A6268;
            }
        """)
        skip_btn.clicked.connect(self.reject)
        button_layout.addWidget(skip_btn)
        
        confirm_btn = QPushButton("✓ 确认匹配")
        confirm_btn.setFixedHeight(36)
        confirm_btn.setFont(QFont("Microsoft YaHei", 9))
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        button_layout.addWidget(confirm_btn)
        
        layout.addLayout(button_layout)
        
        # 设置焦点
        self.input_edit.setFocus()
    
    def _on_confirm(self):
        """确认按钮点击"""
        text = self.input_edit.text().strip()
        if not text:
            self.input_edit.setStyleSheet("""
                QLineEdit {
                    padding: 8px;
                    border: 2px solid #DC3545;
                    border-radius: 6px;
                    font-size: 12px;
                }
            """)
            return
        
        # 从URL中提取ID或直接使用ID
        douban_id = self._extract_douban_id(text)
        if douban_id:
            self.douban_id = douban_id
            self.accept()
        else:
            self.input_edit.setStyleSheet("""
                QLineEdit {
                    padding: 8px;
                    border: 2px solid #DC3545;
                    border-radius: 6px;
                    font-size: 12px;
                }
            """)
    
    def _extract_douban_id(self, text: str) -> str:
        """从URL或纯文本中提取豆瓣ID"""
        import re
        
        # 尝试从URL中提取ID
        # 支持格式: https://movie.douban.com/subject/1292052/
        url_pattern = r'douban\.com/subject/(\d+)'
        match = re.search(url_pattern, text)
        if match:
            return match.group(1)
        
        # 检查是否是纯数字ID
        if text.isdigit():
            return text
        
        return None
    
    def get_douban_id(self) -> str:
        """获取豆瓣ID"""
        return self.douban_id
