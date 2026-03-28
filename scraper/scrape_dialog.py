"""
刮削工作流对话框 - 独立 UI 组件

提供一个独立的弹窗界面，显示刮削工作流进度和日志。
完全不修改现有 main_window.py 的任何代码逻辑。
"""
import os
import logging
from typing import List, Optional, Callable

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QProgressBar, QGroupBox, QCheckBox, QLineEdit,
    QFrame, QWidget, QSizePolicy, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor, QTextCursor, QIcon

from .scrape_workflow import ScrapeConfig, ScrapeWorker, WorkflowResult, StepStatus
from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class ScrapeDialog(QDialog):
    """
    刮削工作流对话框

    使用方式:
        dialog = ScrapeDialog(movie_paths=["path1", "path2"],
                              on_complete=main_window.start_scan)
        dialog.exec()
    """

    def __init__(self, movie_paths: List[str],
                 on_complete: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.movie_paths = movie_paths
        self.on_complete = on_complete
        self.worker: Optional[ScrapeWorker] = None
        self.config = ScrapeConfig()
        self._is_closing = False  # 关闭标志，防止回调崩溃

        self._init_ui()
        self._load_saved_config()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("🎬 刮削工作流")
        self.setMinimumSize(780, 620)
        self.resize(850, 680)
        self.setStyleSheet(self._get_stylesheet())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ===== 标题区域 =====
        title_label = QLabel("电影刮削工作流")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1a1a1a; margin-bottom: 4px;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "一键完成：TMM 元数据刮削 → 豆瓣评分注入 → 刷新媒体库"
        )
        desc_label.setStyleSheet("color: #6C757D; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(desc_label)

        # ===== 步骤状态指示器 =====
        self.step_indicators = {}
        steps_widget = QWidget()
        steps_layout = QHBoxLayout(steps_widget)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(8)

        step_configs = [
            ("step_tmm", "① TMM 刮削", "🎬"),
            ("step_douban", "② 豆瓣注入", "🟢"),
            ("step_refresh", "③ 刷新媒体库", "🔄"),
        ]

        for key, text, icon in step_configs:
            indicator = self._create_step_indicator(text, icon)
            self.step_indicators[key] = indicator
            steps_layout.addWidget(indicator)

        layout.addWidget(steps_widget)

        # ===== 选项配置区 =====
        options_group = self._create_options_group()
        layout.addWidget(options_group)

        # ===== 日志区域 =====
        log_label = QLabel("📋 执行日志")
        log_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        log_label.setStyleSheet("color: #495057;")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMinimumHeight(200)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_text, stretch=1)

        # ===== 进度条 =====
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #E9ECEF;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #007AFF;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.start_btn = QPushButton("▶ 开始刮削")
        self.start_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.start_btn.setFixedHeight(38)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 24px;
            }
            QPushButton:hover { background-color: #0056CC; }
            QPushButton:pressed { background-color: #004099; }
            QPushButton:disabled { background-color: #ADB5BD; }
        """)
        self.start_btn.clicked.connect(self._start_workflow)

        self.cancel_btn = QPushButton("⏹ 取消")
        self.cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        self.cancel_btn.setFixedHeight(38)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 18px;
            }
            QPushButton:hover { background-color: #C82333; }
            QPushButton:disabled { background-color: #ADB5BD; }
        """)
        self.cancel_btn.clicked.connect(self._cancel_workflow)

        self.close_btn = QPushButton("关闭")
        self.close_btn.setFont(QFont("Microsoft YaHei", 10))
        self.close_btn.setFixedHeight(38)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 18px;
            }
            QPushButton:hover { background-color: #5A6268; }
        """)
        self.close_btn.clicked.connect(self.close)

        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _create_step_indicator(self, text: str, icon: str) -> QFrame:
        """创建步骤指示器"""
        frame = QFrame()
        frame.setObjectName("stepIndicator")
        frame.setStyleSheet("""
            QFrame#stepIndicator {
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 8px;
                padding: 8px 12px;
            }
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(icon_label)

        text_label = QLabel(text)
        text_label.setFont(QFont("Microsoft YaHei", 10))
        text_label.setStyleSheet("color: #6C757D;")
        layout.addWidget(text_label)

        # 存储子控件引用
        frame.icon_label = icon_label
        frame.text_label = text_label
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        return frame

    def _update_step_status(self, key: str, status: str):
        """
        更新步骤指示器状态
        status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'
        """
        if self._is_closing:
            return
        
        frame = self.step_indicators.get(key)
        if not frame:
            return

        styles = {
            'pending': {
                'border': '#DEE2E6', 'bg': '#F8F9FA', 'color': '#6C757D'
            },
            'running': {
                'border': '#007AFF', 'bg': '#E8F0FE', 'color': '#007AFF'
            },
            'success': {
                'border': '#28A745', 'bg': '#E8F5E9', 'color': '#28A745'
            },
            'failed': {
                'border': '#DC3545', 'bg': '#FDE8EA', 'color': '#DC3545'
            },
            'skipped': {
                'border': '#ADB5BD', 'bg': '#F1F3F5', 'color': '#868E96'
            },
        }

        s = styles.get(status, styles['pending'])
        frame.setStyleSheet(f"""
            QFrame#stepIndicator {{
                background-color: {s['bg']};
                border: 2px solid {s['border']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
        """)
        frame.text_label.setStyleSheet(f"color: {s['color']}; font-weight: bold;")

    def _create_options_group(self) -> QGroupBox:
        """创建选项配置区"""
        group = QGroupBox("⚙️ 刮削选项")
        group.setFont(QFont("Microsoft YaHei", 10))
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)
        group_layout.setContentsMargins(12, 16, 12, 10)

        # 统一的行标签宽度
        LABEL_W = 55

        # ===== 步骤选择行 =====
        step_row = QHBoxLayout()
        step_row.setSpacing(12)
        step_label = QLabel("步骤:")
        step_label.setFixedWidth(LABEL_W)
        step_row.addWidget(step_label)

        self.chk_enable_tmm = QCheckBox("TMM 刮削")
        self.chk_enable_tmm.setChecked(True)
        self.chk_enable_tmm.setToolTip("启用/禁用 TinyMediaManager 元数据刮削步骤")
        self.chk_enable_tmm.toggled.connect(self._on_step_toggle)
        step_row.addWidget(self.chk_enable_tmm)

        self.chk_enable_douban = QCheckBox("豆瓣注入")
        self.chk_enable_douban.setChecked(True)
        self.chk_enable_douban.setToolTip("启用/禁用豆瓣评分注入步骤")
        self.chk_enable_douban.toggled.connect(self._on_step_toggle)
        step_row.addWidget(self.chk_enable_douban)

        step_row.addStretch()
        group_layout.addLayout(step_row)

        # ===== TMM 选项行 =====
        tmm_row = QHBoxLayout()
        tmm_row.setSpacing(12)
        tmm_label = QLabel("TMM:")
        tmm_label.setFixedWidth(LABEL_W)
        tmm_row.addWidget(tmm_label)

        self.chk_tmm_update = QCheckBox("扫描数据源 (-u)")
        self.chk_tmm_update.setChecked(True)
        tmm_row.addWidget(self.chk_tmm_update)

        self.chk_tmm_scrape_new = QCheckBox("刮削新电影 (-n)")
        self.chk_tmm_scrape_new.setChecked(True)
        tmm_row.addWidget(self.chk_tmm_scrape_new)

        self.chk_tmm_scrape_all = QCheckBox("刮削所有未刮削")
        self.chk_tmm_scrape_all.setChecked(False)
        tmm_row.addWidget(self.chk_tmm_scrape_all)

        self.chk_tmm_rename = QCheckBox("重命名 (-r)")
        self.chk_tmm_rename.setChecked(False)
        tmm_row.addWidget(self.chk_tmm_rename)

        tmm_row.addStretch()
        group_layout.addLayout(tmm_row)

        # ===== 豆瓣引擎选择行 =====
        engine_row = QHBoxLayout()
        engine_row.setSpacing(12)
        engine_label = QLabel("引擎:")
        engine_label.setFixedWidth(LABEL_W)
        engine_row.addWidget(engine_label)

        self.engine_group = QButtonGroup(self)

        self.radio_normal = QRadioButton("普通模式 (requests)")
        self.radio_normal.setChecked(True)
        self.radio_normal.setToolTip("使用 HTTP 请求抓取，速度快但可能触发反爬")
        self.engine_group.addButton(self.radio_normal, 0)
        engine_row.addWidget(self.radio_normal)

        self.radio_selenium = QRadioButton("Selenium 增强模式")
        self.radio_selenium.setToolTip("使用真实浏览器访问，成功率高，支持登录")
        self.engine_group.addButton(self.radio_selenium, 1)
        engine_row.addWidget(self.radio_selenium)

        self.radio_normal.toggled.connect(self._on_engine_changed)

        engine_row.addStretch()
        group_layout.addLayout(engine_row)

        # ===== Selenium 选项行 =====
        selenium_row = QHBoxLayout()
        selenium_row.setSpacing(12)
        selenium_spacer = QLabel("")
        selenium_spacer.setFixedWidth(LABEL_W)
        selenium_row.addWidget(selenium_spacer)

        self.chk_selenium_login = QCheckBox("🔐 启用豆瓣登录")
        self.chk_selenium_login.setChecked(False)
        self.chk_selenium_login.setEnabled(False)
        self.chk_selenium_login.setToolTip("打开浏览器手动登录豆瓣账号（提升抓取成功率）")
        self.chk_selenium_login.toggled.connect(self._on_login_toggle)
        selenium_row.addWidget(self.chk_selenium_login)

        self.chk_selenium_headless = QCheckBox("无头模式 (后台运行)")
        self.chk_selenium_headless.setChecked(True)
        self.chk_selenium_headless.setEnabled(False)
        self.chk_selenium_headless.setToolTip("不显示浏览器窗口，后台运行")
        selenium_row.addWidget(self.chk_selenium_headless)

        selenium_row.addStretch()
        group_layout.addLayout(selenium_row)

        # ===== 豆瓣选项行 1 =====
        douban_row1 = QHBoxLayout()
        douban_row1.setSpacing(12)
        douban_label = QLabel("豆瓣:")
        douban_label.setFixedWidth(LABEL_W)
        douban_row1.addWidget(douban_label)

        self.chk_douban_skip = QCheckBox("跳过已有评分")
        self.chk_douban_skip.setChecked(True)
        douban_row1.addWidget(self.chk_douban_skip)

        self.chk_douban_recursive = QCheckBox("递归扫描")
        self.chk_douban_recursive.setChecked(True)
        douban_row1.addWidget(self.chk_douban_recursive)

        self.chk_douban_skip_failed = QCheckBox("跳过已失败")
        self.chk_douban_skip_failed.setChecked(True)
        self.chk_douban_skip_failed.setToolTip("自动跳过之前匹配失败的电影，避免重复尝试")
        douban_row1.addWidget(self.chk_douban_skip_failed)

        delay_label = QLabel("延迟(秒):")
        douban_row1.addWidget(delay_label)

        self.delay_input = QLineEdit("2.5")
        self.delay_input.setFixedWidth(60)
        self.delay_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        douban_row1.addWidget(self.delay_input)

        douban_row1.addStretch()
        group_layout.addLayout(douban_row1)

        # ===== 豆瓣选项行 2（增量注入） =====
        douban_row2 = QHBoxLayout()
        douban_row2.setSpacing(12)
        douban_spacer = QLabel("")
        douban_spacer.setFixedWidth(LABEL_W)
        douban_row2.addWidget(douban_spacer)

        self.chk_douban_new_only = QCheckBox("仅注入新电影")
        self.chk_douban_new_only.setChecked(False)
        self.chk_douban_new_only.setToolTip("只处理最近修改的 NFO 文件，适合增量更新")
        douban_row2.addWidget(self.chk_douban_new_only)

        self.new_days_label = QLabel("天数:")
        douban_row2.addWidget(self.new_days_label)

        self.new_days_input = QLineEdit("7")
        self.new_days_input.setFixedWidth(60)
        self.new_days_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.new_days_input.setToolTip("只处理最近 N 天修改的 NFO 文件")
        douban_row2.addWidget(self.new_days_input)

        douban_row2.addStretch()
        group_layout.addLayout(douban_row2)

        # 连接信号
        self.chk_douban_new_only.toggled.connect(self._on_new_only_toggle)

        # ===== Cookie 行 =====
        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(12)
        self.cookie_label = QLabel("Cookie:")
        self.cookie_label.setFixedWidth(LABEL_W)
        cookie_row.addWidget(self.cookie_label)

        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("可选：粘贴豆瓣 Cookie 提升成功率（仅普通模式）")
        cookie_row.addWidget(self.cookie_input)

        group_layout.addLayout(cookie_row)

        return group

    def _on_step_toggle(self, checked: bool):
        """步骤启用/禁用时更新相关选项的可用性"""
        tmm_enabled = self.chk_enable_tmm.isChecked()
        douban_enabled = self.chk_enable_douban.isChecked()

        # TMM 相关选项
        self.chk_tmm_update.setEnabled(tmm_enabled)
        self.chk_tmm_scrape_new.setEnabled(tmm_enabled)
        self.chk_tmm_scrape_all.setEnabled(tmm_enabled)
        self.chk_tmm_rename.setEnabled(tmm_enabled)

        # 豆瓣相关选项
        self.radio_normal.setEnabled(douban_enabled)
        self.radio_selenium.setEnabled(douban_enabled)
        self.chk_douban_skip.setEnabled(douban_enabled)
        self.chk_douban_recursive.setEnabled(douban_enabled)
        self.chk_douban_new_only.setEnabled(douban_enabled)
        self.chk_douban_skip_failed.setEnabled(douban_enabled)
        self.delay_input.setEnabled(douban_enabled)
        self.cookie_input.setEnabled(douban_enabled)
        
        # 天数输入框仅在启用“仅注入新电影”时可用
        self.new_days_label.setEnabled(douban_enabled and self.chk_douban_new_only.isChecked())
        self.new_days_input.setEnabled(douban_enabled and self.chk_douban_new_only.isChecked())
        
        # Selenium 选项根据引擎和豆瓣步骤启用状态
        is_selenium = self.radio_selenium.isChecked()
        self.chk_selenium_login.setEnabled(douban_enabled and is_selenium)
        self.chk_selenium_headless.setEnabled(douban_enabled and is_selenium)

    def _on_engine_changed(self, checked: bool):
        """引擎切换时更新 UI 状态"""
        is_selenium = self.radio_selenium.isChecked()
        douban_enabled = self.chk_enable_douban.isChecked()
        
        # Selenium 选项仅在 Selenium 模式且豆瓣步骤启用时可用
        self.chk_selenium_login.setEnabled(douban_enabled and is_selenium)
        self.chk_selenium_headless.setEnabled(douban_enabled and is_selenium)
        
        # Cookie 输入仅在普通模式有意义
        self.cookie_input.setEnabled(not is_selenium)
        
        # 更新提示文本
        if is_selenium:
            self.cookie_input.setPlaceholderText("Selenium 模式使用浏览器 Cookie，无需手动填写")
        else:
            self.cookie_input.setPlaceholderText("可选：粘贴豆瓣 Cookie 提升成功率（仅普通模式）")

    def _on_login_toggle(self, checked: bool):
        """启用登录时自动关闭无头模式（否则用户看不到浏览器窗口）"""
        if checked:
            # 启用登录时，必须关闭无头模式
            self.chk_selenium_headless.setChecked(False)
            # 暂时禁用无头模式复选框，防止用户误操作
            # self.chk_selenium_headless.setEnabled(False)
    
    def _on_new_only_toggle(self, checked: bool):
        """仅注入新电影选项切换时更新天数输入框状态"""
        douban_enabled = self.chk_enable_douban.isChecked()
        self.new_days_label.setEnabled(douban_enabled and checked)
        self.new_days_input.setEnabled(douban_enabled and checked)

    def _load_saved_config(self):
        """加载之前保存的配置（如有）"""
        import json
        config_path = str(resolve_data_file('scrape_config.json'))
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                
                # 步骤启用状态
                if 'enable_tmm_step' in saved:
                    self.chk_enable_tmm.setChecked(saved['enable_tmm_step'])
                if 'enable_douban_step' in saved:
                    self.chk_enable_douban.setChecked(saved['enable_douban_step'])
                
                # 抓取引擎
                if saved.get('douban_mode') == 'selenium':
                    self.radio_selenium.setChecked(True)
                else:
                    self.radio_normal.setChecked(True)
                
                # Selenium 选项
                if 'selenium_headless' in saved:
                    self.chk_selenium_headless.setChecked(saved['selenium_headless'])
                if 'selenium_enable_login' in saved:
                    self.chk_selenium_login.setChecked(saved['selenium_enable_login'])
                
                # Cookie 和延迟
                if saved.get('douban_cookie'):
                    self.cookie_input.setText(saved['douban_cookie'])
                if saved.get('douban_delay'):
                    self.delay_input.setText(str(saved['douban_delay']))
                
                # 新增选项
                if 'douban_inject_new_only' in saved:
                    self.chk_douban_new_only.setChecked(saved['douban_inject_new_only'])
                if 'douban_new_days' in saved:
                    self.new_days_input.setText(str(saved['douban_new_days']))
                if 'douban_skip_failed' in saved:
                    self.chk_douban_skip_failed.setChecked(saved['douban_skip_failed'])
                
                # 路径
                if 'tmm_path' in saved:
                    self.config.tmm_path = saved['tmm_path']
                if 'douban_tool_path' in saved:
                    self.config.douban_tool_path = saved['douban_tool_path']
            except Exception:
                pass
        
        # 加载完配置后，手动触发一次状态同步，确保所有控件的启用/禁用状态正确
        self._on_step_toggle(True)
        self._on_engine_changed(True)
        self._on_new_only_toggle(self.chk_douban_new_only.isChecked())

    def _save_config(self):
        """保存配置"""
        import json
        config_path = str(resolve_data_file('scrape_config.json'))
        try:
            saved = {
                'enable_tmm_step': self.chk_enable_tmm.isChecked(),
                'enable_douban_step': self.chk_enable_douban.isChecked(),
                'douban_mode': 'selenium' if self.radio_selenium.isChecked() else 'normal',
                'douban_cookie': self.cookie_input.text().strip(),
                'douban_delay': float(self.delay_input.text() or 2.5),
                'douban_inject_new_only': self.chk_douban_new_only.isChecked(),
                'douban_new_days': int(self.new_days_input.text() or 7),
                'douban_skip_failed': self.chk_douban_skip_failed.isChecked(),
                'selenium_headless': self.chk_selenium_headless.isChecked(),
                'selenium_enable_login': self.chk_selenium_login.isChecked(),
                'tmm_path': self.config.tmm_path,
                'douban_tool_path': self.config.douban_tool_path,
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(saved, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ─────────────── 工作流控制 ───────────────

    def _start_workflow(self):
        """开始执行刮削工作流"""
        self._save_config()

        # 从 UI 读取步骤启用状态
        self.config.enable_tmm_step = self.chk_enable_tmm.isChecked()
        self.config.enable_douban_step = self.chk_enable_douban.isChecked()

        # 从 UI 读取配置
        self.config.tmm_update_all = self.chk_tmm_update.isChecked()
        self.config.tmm_scrape_new = self.chk_tmm_scrape_new.isChecked()
        self.config.tmm_scrape_unscraped = self.chk_tmm_scrape_all.isChecked()
        self.config.tmm_rename = self.chk_tmm_rename.isChecked()
        
        # 读取抓取引擎模式
        self.config.douban_mode = "selenium" if self.radio_selenium.isChecked() else "normal"
        
        self.config.douban_skip_existing = self.chk_douban_skip.isChecked()
        self.config.douban_inject_new_only = self.chk_douban_new_only.isChecked()
        self.config.douban_skip_failed = self.chk_douban_skip_failed.isChecked()
        self.config.douban_recursive = self.chk_douban_recursive.isChecked()
        self.config.douban_cookie = self.cookie_input.text().strip()
        
        # Selenium 选项
        self.config.selenium_headless = self.chk_selenium_headless.isChecked()
        self.config.selenium_enable_login = self.chk_selenium_login.isChecked()

        try:
            self.config.douban_delay = float(self.delay_input.text() or 2.5)
        except ValueError:
            self.config.douban_delay = 2.5
        
        try:
            self.config.douban_new_days = int(self.new_days_input.text() or 7)
        except ValueError:
            self.config.douban_new_days = 7

        # UI 状态切换
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.log_text.clear()

        # 重置步骤指示器
        for key in self.step_indicators:
            self._update_step_status(key, 'pending')

        self._log("=" * 60)
        self._log("🎬 刮削工作流开始")
        self._log(f"电影目录: {', '.join(self.movie_paths)}")
        self._log(f"抓取引擎: {'Selenium 增强模式' if self.config.douban_mode == 'selenium' else '普通模式 (requests)'}")
        if self.config.douban_mode == "selenium":
            self._log(f"  - 无头模式: {'是' if self.config.selenium_headless else '否'}")
            self._log(f"  - 豆瓣登录: {'是' if self.config.selenium_enable_login else '否'}")
        self._log("=" * 60)

        # 启动工作线程
        self.worker = ScrapeWorker(self.config, self.movie_paths, self)
        self.worker.step_started.connect(self._on_step_started)
        self.worker.step_progress.connect(self._on_step_progress)
        self.worker.step_finished.connect(self._on_step_finished)
        self.worker.workflow_finished.connect(self._on_workflow_finished)
        self.worker.start()

    def _cancel_workflow(self):
        """取消工作流"""
        if self._is_closing:
            return
        
        if self.worker:
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self._log("⚠️ 正在取消...")

    # ─────────────── 信号回调 ───────────────

    def _on_step_started(self, desc: str):
        """步骤开始"""
        if self._is_closing:
            return
        
        self._log(f"\n{'─' * 50}")
        self._log(desc)
        self._log(f"{'─' * 50}")

        # 更新指示器
        if "TMM" in desc:
            self._update_step_status("step_tmm", "running")
        elif "豆瓣" in desc:
            self._update_step_status("step_douban", "running")
        elif "刷新" in desc:
            self._update_step_status("step_refresh", "running")

    def _on_step_progress(self, msg: str):
        """步骤进度日志"""
        if self._is_closing:
            return
        self._log(msg)
        
        # 检测跳过消息，更新步骤状态为 skipped
        if "⏭️ 已跳过 TMM" in msg:
            self._update_step_status("step_tmm", "skipped")
        elif "⏭️ 已跳过豆瓣" in msg:
            self._update_step_status("step_douban", "skipped")

    def _on_step_finished(self, desc: str, success: bool):
        """步骤完成"""
        if self._is_closing:
            return
        
        status = "success" if success else "failed"
        if "TMM" in desc:
            self._update_step_status("step_tmm", status)
        elif "豆瓣" in desc:
            self._update_step_status("step_douban", status)
        elif "刷新" in desc:
            self._update_step_status("step_refresh", status)

    def _on_workflow_finished(self, result: WorkflowResult):
        """工作流完成"""
        # 如果对话框正在关闭，直接返回避免崩溃
        if self._is_closing:
            return
        
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        # 更新刷新步骤状态
        self._update_step_status("step_refresh", "success")

        self._log(f"\n{'=' * 60}")
        if result.success:
            self._log(f"✅ 工作流全部完成！总耗时 {result.total_elapsed:.1f} 秒")
        else:
            self._log(f"⚠️ 工作流完成（部分步骤失败），总耗时 {result.total_elapsed:.1f} 秒")
        self._log(f"{'=' * 60}")

        # 清理工作线程
        self.worker = None
        
        # 如果有匹配失败的电影，询问是否手动匹配
        if result.failed_movies:
            self._log(f"\n📝 发现 {len(result.failed_movies)} 部电影无法自动匹配")
            self._log("可以手动输入豆瓣ID进行匹配...")
            self._handle_failed_movies(result.failed_movies)

        # 触发媒体库刷新（步骤3）
        if self.on_complete and not self._is_closing:
            try:
                self.on_complete(force_rescan=True)
                self._log("🔄 已触发媒体库强制重新扫描")
            except Exception as e:
                self._log(f"⚠️ 刷新媒体库失败: {e}")

    def _handle_failed_movies(self, failed_movies):
        """处理匹配失败的电影，弹出手动匹配对话框"""
        from .manual_match_dialog import ManualMatchDialog
        from .scrape_workflow import FailedMovie
        import importlib.util
        import random
        import time
        
        if not failed_movies:
            return
        
        # 导入 TMM_DOUBAN 模块
        douban_script = os.path.join(
            self.config.douban_tool_path, self.config.douban_script
        )
        
        try:
            spec = importlib.util.spec_from_file_location(
                "douban_injector", douban_script
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            NFOHandler = module.NFOHandler
            nfo_handler = NFOHandler()
            
            # 选择API模式
            if self.config.douban_mode == "selenium":
                DoubanAPISelenium = module.DoubanAPISelenium
                api = DoubanAPISelenium(
                    headless=self.config.selenium_headless,
                    enable_login=self.config.selenium_enable_login,
                    cookie_file=self.config.selenium_cookie_file
                )
            else:
                DoubanAPI = module.DoubanAPI
                cookie = self.config.douban_cookie or None
                api = DoubanAPI(cookie=cookie)
            
            # 初始化失败记录管理器
            from utils.failed_movies_manager import FailedMoviesManager
            failed_manager = FailedMoviesManager()
            
            manual_matched = 0
            manual_skipped = 0
            
            for idx, failed_movie in enumerate(failed_movies, 1):
                # 弹出手动匹配对话框
                dialog = ManualMatchDialog(
                    movie_title=failed_movie.title,
                    year=failed_movie.year,
                    nfo_path=failed_movie.nfo_file,
                    parent=self
                )
                
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    douban_id = dialog.get_douban_id()
                    if douban_id:
                        try:
                            self._log(f"\n[{idx}/{len(failed_movies)}] 手动匹配: {failed_movie.title}")
                            self._log(f"  豆瓣ID: {douban_id}")
                            
                            # 获取评分
                            rating_info = api.get_movie_rating(douban_id)
                            if rating_info:
                                rating = rating_info['rating']
                                votes = rating_info['votes']
                                
                                # 注入
                                if nfo_handler.inject_douban_data(
                                    failed_movie.nfo_file, douban_id, rating, votes
                                ):
                                    self._log(f"  ✓ 成功注入: {rating}/10 ({votes}票)")
                                    manual_matched += 1
                                    
                                    # 从失败记录中移除
                                    if failed_manager.is_failed(failed_movie.nfo_file):
                                        failed_manager.remove_failed(failed_movie.nfo_file)
                                        self._log(f"  ✓ 已从失败记录中移除")
                                else:
                                    self._log(f"  ✗ 注入失败")
                            else:
                                self._log(f"  ✗ 获取评分失败")
                            
                            # 延迟
                            time.sleep(self.config.douban_delay + random.uniform(-0.5, 1.0))
                        except Exception as e:
                            self._log(f"  ✗ 异常: {e}")
                else:
                    manual_skipped += 1
                    self._log(f"\n[{idx}/{len(failed_movies)}] 跳过: {failed_movie.title}")
            
            api.close()
            
            self._log(f"\n{'=' * 60}")
            self._log(f"📊 手动匹配完成: 成功 {manual_matched} | 跳过 {manual_skipped}")
            self._log(f"{'=' * 60}")
            
        except Exception as e:
            self._log(f"\n❌ 手动匹配过程出错: {e}")

    # ─────────────── 工具方法 ───────────────

    def _log(self, message: str):
        """写入日志"""
        if self._is_closing:
            return
        
        try:
            self.log_text.append(message)
            # 自动滚动到底部
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_text.setTextCursor(cursor)
        except RuntimeError:
            # 如果UI已经被销毁，忽略错误
            pass

    def _get_stylesheet(self) -> str:
        return """
            QDialog {
                background-color: #FFFFFF;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
                border: 1px solid #DEE2E6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                padding-bottom: 8px;
                background-color: #FAFBFC;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #495057;
                font-weight: bold;
            }
            QLabel {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
                color: #495057;
            }
            QCheckBox {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
                color: #343A40;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border: 1.5px solid #ADB5BD;
                border-radius: 3px;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #007AFF;
                border-color: #007AFF;
                image: none;
            }
            QCheckBox::indicator:disabled {
                background-color: #E9ECEF;
                border-color: #CED4DA;
            }
            QRadioButton {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
                color: #343A40;
                spacing: 6px;
            }
            QRadioButton::indicator {
                width: 15px;
                height: 15px;
                border: 1.5px solid #ADB5BD;
                border-radius: 8px;
                background-color: #FFFFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #007AFF;
                border-color: #007AFF;
            }
            QRadioButton::indicator:disabled {
                background-color: #E9ECEF;
                border-color: #CED4DA;
            }
            QLineEdit {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
                border: 1px solid #CED4DA;
                border-radius: 4px;
                padding: 3px 8px;
                min-height: 22px;
                background-color: #FFFFFF;
                color: #343A40;
            }
            QLineEdit:focus {
                border-color: #007AFF;
                background-color: #FFFFFF;
            }
            QLineEdit:disabled {
                background-color: #F1F3F5;
                color: #ADB5BD;
            }
        """

    def closeEvent(self, event):
        """关闭时清理"""
        # 设置关闭标志，防止信号回调访问已关闭的对话框
        self._is_closing = True
        
        if self.worker and self.worker.isRunning():
            # 断开所有信号连接，避免线程继续emit到已关闭的对话框
            try:
                self.worker.step_started.disconnect()
                self.worker.step_progress.disconnect()
                self.worker.step_finished.disconnect()
                self.worker.workflow_finished.disconnect()
            except Exception:
                pass  # 如果信号已经断开，忽略错误
            
            # 取消工作线程
            self.worker.cancel()
            
            # 非阻塞等待，避免主线程冻结
            if not self.worker.wait(1000):  # 等待1秒
                # 如果1秒内没有结束，强制终止
                self.worker.terminate()
                self.worker.wait(500)  # 再等0.5秒
        
        super().closeEvent(event)
