"""
NFO 属性编辑对话框
用于编辑电影的 NFO 文件属性
"""
import os
import logging
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QLineEdit, QTextEdit, QPushButton, QWidget,
    QGridLayout, QMessageBox, QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
    QFileDialog, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap

from models.movie import Movie
from utils.poster_cache_manager import PosterCacheManager
from pathlib import Path

logger = logging.getLogger(__name__)


class NFOEditorDialog(QDialog):
    """NFO 文件编辑器对话框"""
    
    def __init__(self, movie: Movie, parent=None):
        super().__init__(parent)
        self.movie = movie
        self.nfo_path = movie.nfo_path
        self.fields = {}  # 存储所有输入字段
        
        self.setWindowTitle(f"属性 - {movie.title}")
        self.setModal(True)
        self.resize(800, 600)
        
        self.init_ui()
        self.load_data()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #DEE2E6;
            }
            QTabBar::tab {
                padding: 10px 20px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #007BFF;
                color: white;
            }
        """)
        
        # 创建各个标签页
        self.tab_widget.addTab(self._create_basic_tab(), "视频信息")
        self.tab_widget.addTab(self._create_poster_tab(), "海报")
        self.tab_widget.addTab(self._create_custom_tab(), "自定义分类")
        self.tab_widget.addTab(self._create_metadata_tab(), "编码信息")
        self.tab_widget.addTab(self._create_other_tab(), "其它")
        
        layout.addWidget(self.tab_widget)
        
        # 底部按钮栏
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(15, 10, 15, 10)
        button_layout.setSpacing(10)
        
        delete_btn = QPushButton("删除")
        delete_btn.setFixedSize(80, 36)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        delete_btn.clicked.connect(self._on_delete)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        confirm_btn = QPushButton("确定")
        confirm_btn.setFixedSize(80, 36)
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        confirm_btn.clicked.connect(self._on_save)
        button_layout.addWidget(confirm_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 36)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #5A6268;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _create_basic_tab(self):
        """创建基础信息标签页"""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setColumnStretch(1, 1)
        
        row = 0
        
        # 位置
        layout.addWidget(QLabel("位置:"), row, 0)
        self.fields['location'] = QLineEdit()
        self.fields['location'].setReadOnly(True)
        self.fields['location'].setStyleSheet("background-color: #F8F9FA;")
        layout.addWidget(self.fields['location'], row, 1)
        row += 1
        
        # 标题
        layout.addWidget(QLabel("标题:"), row, 0)
        self.fields['title'] = QLineEdit()
        layout.addWidget(self.fields['title'], row, 1)
        row += 1
        
        # 又名
        layout.addWidget(QLabel("又名:"), row, 0)
        self.fields['originaltitle'] = QLineEdit()
        layout.addWidget(self.fields['originaltitle'], row, 1)
        row += 1
        
        # 年份
        layout.addWidget(QLabel("年份:"), row, 0)
        self.fields['year'] = QLineEdit()
        layout.addWidget(self.fields['year'], row, 1)
        row += 1
        
        # 国家
        layout.addWidget(QLabel("国家:"), row, 0)
        self.fields['country'] = QLineEdit()
        layout.addWidget(self.fields['country'], row, 1)
        row += 1
        
        # 类型
        layout.addWidget(QLabel("类型:"), row, 0)
        self.fields['genre'] = QLineEdit()
        self.fields['genre'].setPlaceholderText("多个类型用 / 分隔")
        layout.addWidget(self.fields['genre'], row, 1)
        row += 1
        
        # 主演
        layout.addWidget(QLabel("主演:"), row, 0)
        self.fields['actor'] = QTextEdit()
        self.fields['actor'].setFixedHeight(80)
        self.fields['actor'].setPlaceholderText("每行一个演员,格式: 姓名 饰 角色")
        layout.addWidget(self.fields['actor'], row, 1)
        row += 1
        
        # 导演
        layout.addWidget(QLabel("导演:"), row, 0)
        self.fields['director'] = QLineEdit()
        self.fields['director'].setPlaceholderText("多个导演用 / 分隔")
        layout.addWidget(self.fields['director'], row, 1)
        row += 1
        
        # 摘要
        layout.addWidget(QLabel("摘要:"), row, 0, Qt.AlignmentFlag.AlignTop)
        self.fields['plot'] = QTextEdit()
        self.fields['plot'].setFixedHeight(120)
        layout.addWidget(self.fields['plot'], row, 1)
        row += 1
        
        layout.setRowStretch(row, 1)
        
        scroll.setWidget(container)
        
        scroll_layout = QVBoxLayout(widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(scroll)
        
        return widget
    
    def _create_poster_tab(self):
        """创建海报标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 海报预览
        poster_label = QLabel("当前图像:")
        poster_label.setStyleSheet("font-size: 13px; color: #495057;")
        layout.addWidget(poster_label)
        
        # 海报显示区域
        self.poster_display = QLabel()
        self.poster_display.setFixedSize(300, 450)
        self.poster_display.setScaledContents(True)
        self.poster_display.setStyleSheet("""
            QLabel {
                border: 1px solid #DEE2E6;
                background-color: #F8F9FA;
            }
        """)
        layout.addWidget(self.poster_display)
        
        # 海报路径
        path_layout = QHBoxLayout()
        path_label = QLabel("从文件夹中选择:")
        path_label.setStyleSheet("font-size: 13px; color: #495057;")
        path_layout.addWidget(path_label)
        
        self.poster_path_field = QLineEdit()
        self.poster_path_field.setReadOnly(True)
        self.poster_path_field.setStyleSheet("background-color: #F8F9FA;")
        path_layout.addWidget(self.poster_path_field)
        
        layout.addLayout(path_layout)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        browse_btn = QPushButton("浏览")
        browse_btn.setFixedSize(100, 32)
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #007BFF;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0056B3;
            }
        """)
        browse_btn.clicked.connect(self._browse_poster)
        button_layout.addWidget(browse_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        layout.addStretch()
        
        return widget
    
    def _create_custom_tab(self):
        """创建自定义分类标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        note = QLabel("自定义标签可用于分类筛选，多个标签用回车分隔")
        note.setStyleSheet("color: #6C757D; font-size: 12px;")
        layout.addWidget(note)
        
        # 标签列表
        tag_label = QLabel("自定义标签:")
        tag_label.setStyleSheet("font-size: 13px; color: #495057; margin-top: 10px;")
        layout.addWidget(tag_label)
        
        self.tag_list = QListWidget()
        self.tag_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #DEE2E6;
                border-radius: 4px;
                padding: 5px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #F8F9FA;
            }
            QListWidget::item:selected {
                background-color: #007BFF;
                color: white;
            }
        """)
        layout.addWidget(self.tag_list)
        
        # 添加/删除按钮
        button_layout = QHBoxLayout()
        
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("输入新标签名称...")
        self.tag_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                font-size: 13px;
                border: 1px solid #DEE2E6;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(self.tag_input)
        
        add_btn = QPushButton("添加")
        add_btn.setFixedSize(80, 32)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        add_btn.clicked.connect(self._add_tag)
        button_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("删除")
        remove_btn.setFixedSize(80, 32)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        remove_btn.clicked.connect(self._remove_tag)
        button_layout.addWidget(remove_btn)
        
        layout.addLayout(button_layout)
        
        return widget
    
    def _create_metadata_tab(self):
        """创建编码信息标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 提示信息
        note = QLabel("编码信息从NFO文件中读取（只读）")
        note.setStyleSheet("color: #6C757D; font-size: 12px;")
        layout.addWidget(note)
        
        # 树形显示编码信息
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["字段名", "值"])
        self.metadata_tree.setColumnWidth(0, 200)
        self.metadata_tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #DEE2E6;
                border-radius: 4px;
                font-size: 13px;
                background-color: #F8F9FA;
            }
            QTreeWidget::item {
                padding: 5px;
            }
        """)
        layout.addWidget(self.metadata_tree)
        
        return widget
    
    def _create_other_tab(self):
        """创建其它标签页"""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setColumnStretch(1, 1)
        
        row = 0
        
        # 豆瓣评分
        layout.addWidget(QLabel("豆瓣评分:"), row, 0)
        rating_layout = QHBoxLayout()
        self.fields['rating'] = QDoubleSpinBox()
        self.fields['rating'].setRange(0, 10)
        self.fields['rating'].setSingleStep(0.1)
        self.fields['rating'].setDecimals(1)
        rating_layout.addWidget(self.fields['rating'])
        rating_layout.addWidget(QLabel("/ 10"))
        rating_layout.addStretch()
        layout.addLayout(rating_layout, row, 1)
        row += 1
        
        # 影片片长
        layout.addWidget(QLabel("影片片长 (分钟):"), row, 0)
        self.fields['runtime'] = QSpinBox()
        self.fields['runtime'].setRange(0, 999)
        layout.addWidget(self.fields['runtime'], row, 1)
        row += 1
        
        # 链接地址
        layout.addWidget(QLabel("链接地址:"), row, 0)
        self.fields['url'] = QLineEdit()
        self.fields['url'].setPlaceholderText("例如: https://movie.douban.com/subject/xxxxx/")
        layout.addWidget(self.fields['url'], row, 1)
        row += 1
        
        # 备注
        layout.addWidget(QLabel("备注:"), row, 0, Qt.AlignmentFlag.AlignTop)
        self.fields['notes'] = QTextEdit()
        self.fields['notes'].setFixedHeight(120)
        layout.addWidget(self.fields['notes'], row, 1)
        row += 1
        
        layout.setRowStretch(row, 1)
        
        scroll.setWidget(container)
        
        scroll_layout = QVBoxLayout(widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(scroll)
        
        return widget
    
    def load_data(self):
        """从Movie对象加载数据到表单"""
        # 位置
        if self.movie.nfo_path:
            video_dir = os.path.dirname(self.movie.nfo_path)
            self.fields['location'].setText(video_dir)
        
        # 基础信息
        self.fields['title'].setText(self.movie.title or "")
        self.fields['originaltitle'].setText(getattr(self.movie, 'original_title', '') or "")
        self.fields['year'].setText(self.movie.year or "")
        
        # 国家
        if self.movie.countries:
            self.fields['country'].setText(" / ".join(self.movie.countries))
        
        # 类型
        if self.movie.genres:
            self.fields['genre'].setText(" / ".join(self.movie.genres))
        
        # 导演
        if self.movie.directors:
            self.fields['director'].setText(" / ".join(self.movie.directors))
        
        # 演员
        if self.movie.actors:
            actor_lines = []
            for actor in self.movie.actors:
                if actor.role:
                    actor_lines.append(f"{actor.name} 饰 {actor.role}")
                else:
                    actor_lines.append(actor.name)
            self.fields['actor'].setPlainText("\n".join(actor_lines))
        
        # 剧情
        self.fields['plot'].setPlainText(self.movie.plot or "")
        
        # 评分（优先取豆瓣评分）
        douban_rating = (self.movie.ratings or {}).get('douban', 0)
        if douban_rating:
            self.fields['rating'].setValue(douban_rating)
        elif self.movie.rating:
            self.fields['rating'].setValue(self.movie.rating)
        
        # 时长
        runtime = getattr(self.movie, 'runtime', '')
        if runtime:
            try:
                self.fields['runtime'].setValue(int(runtime))
            except:
                pass
        
        # URL
        if hasattr(self.movie, 'douban_url') and self.movie.douban_url:
            self.fields['url'].setText(self.movie.douban_url)
        elif hasattr(self.movie, 'imdb_id') and self.movie.imdb_id:
            self.fields['url'].setText(f"https://www.imdb.com/title/{self.movie.imdb_id}/")
        elif hasattr(self.movie, 'tmdb_id') and self.movie.tmdb_id:
            self.fields['url'].setText(f"https://www.themoviedb.org/movie/{self.movie.tmdb_id}")
        
        # 加载海报
        self._load_poster()
        
        # 加载标签
        self._load_tags()
        
        # 加载编码信息
        self._load_metadata()
    
    def _on_save(self):
        """保存修改到NFO文件"""
        try:
            # 读取现有NFO文件
            tree = ET.parse(self.nfo_path)
            root = tree.getroot()
            
            # 更新字段
            self._update_element(root, 'title', self.fields['title'].text())
            self._update_element(root, 'originaltitle', self.fields['originaltitle'].text())
            self._update_element(root, 'year', self.fields['year'].text())
            self._update_element(root, 'plot', self.fields['plot'].toPlainText())
            
            # 更新国家
            country_text = self.fields['country'].text()
            if country_text:
                # 先删除所有旧的country元素
                for elem in root.findall('country'):
                    root.remove(elem)
                # 添加新的country元素
                for country in country_text.split('/'):
                    country = country.strip()
                    if country:
                        elem = ET.SubElement(root, 'country')
                        elem.text = country
            
            # 更新类型
            genre_text = self.fields['genre'].text()
            if genre_text:
                # 先删除所有旧的genre元素
                for elem in root.findall('genre'):
                    root.remove(elem)
                # 添加新的genre元素
                for genre in genre_text.split('/'):
                    genre = genre.strip()
                    if genre:
                        elem = ET.SubElement(root, 'genre')
                        elem.text = genre
            
            # 更新导演
            director_text = self.fields['director'].text()
            if director_text:
                # 先删除所有旧的director元素
                for elem in root.findall('director'):
                    root.remove(elem)
                # 添加新的director元素
                for director in director_text.split('/'):
                    director = director.strip()
                    if director:
                        elem = ET.SubElement(root, 'director')
                        elem.text = director
            
            # 更新演员
            actor_text = self.fields['actor'].toPlainText()
            if actor_text:
                # 先删除所有旧的actor元素
                for elem in root.findall('actor'):
                    root.remove(elem)
                # 添加新的actor元素
                for line in actor_text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    actor_elem = ET.SubElement(root, 'actor')
                    if ' 饰 ' in line:
                        name, role = line.split(' 饰 ', 1)
                        name_elem = ET.SubElement(actor_elem, 'name')
                        name_elem.text = name.strip()
                        role_elem = ET.SubElement(actor_elem, 'role')
                        role_elem.text = role.strip()
                    else:
                        name_elem = ET.SubElement(actor_elem, 'name')
                        name_elem.text = line
            
            # 更新豆瓣评分
            rating_value = self.fields['rating'].value()
            if rating_value > 0:
                # 查找或创建ratings元素
                ratings_elem = root.find('ratings')
                if ratings_elem is None:
                    ratings_elem = ET.SubElement(root, 'ratings')
                
                # 查找或创建douban评分元素
                rating_elem = ratings_elem.find("rating[@name='douban']")
                if rating_elem is None:
                    rating_elem = ET.SubElement(ratings_elem, 'rating')
                    rating_elem.set('name', 'douban')
                    rating_elem.set('max', '10')
                
                # 更新value
                value_elem = rating_elem.find('value')
                if value_elem is None:
                    value_elem = ET.SubElement(rating_elem, 'value')
                value_elem.text = str(rating_value)
            
            # 更新URL
            url_text = self.fields['url'].text()
            if url_text:
                if 'douban.com' in url_text:
                    self._update_element(root, 'doubanurl', url_text)
                elif 'imdb.com' in url_text:
                    # 从URL提取IMDB ID
                    if '/title/' in url_text:
                        imdb_id = url_text.split('/title/')[1].split('/')[0]
                        self._update_element(root, 'id', imdb_id)
                        # 设置uniqueid
                        uniqueid = root.find("uniqueid[@type='imdb']")
                        if uniqueid is None:
                            uniqueid = ET.SubElement(root, 'uniqueid')
                            uniqueid.set('type', 'imdb')
                            uniqueid.set('default', 'true')
                        uniqueid.text = imdb_id
            
            # 保存自定义标签
            self._save_tags(root)
            
            # 格式化XML并保存
            self._save_formatted_xml(tree, self.nfo_path)
            
            QMessageBox.information(self, "成功", "NFO文件已保存")
            self.accept()
            
        except Exception as e:
            logger.error(f"保存NFO文件失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
    
    def _update_element(self, root, tag, value):
        """更新或创建XML元素"""
        if not value:
            return
        
        elem = root.find(tag)
        if elem is None:
            elem = ET.SubElement(root, tag)
        elem.text = value
    
    def _save_formatted_xml(self, tree, file_path):
        """保存格式化的XML文件"""
        # 转换为字符串
        xml_str = ET.tostring(tree.getroot(), encoding='utf-8')
        
        # 使用minidom格式化
        dom = minidom.parseString(xml_str)
        formatted_xml = dom.toprettyxml(indent="  ", encoding='utf-8')
        
        # 移除多余的空行
        lines = formatted_xml.decode('utf-8').split('\n')
        lines = [line for line in lines if line.strip()]
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def _on_delete(self):
        """删除NFO文件和相关资源"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            "是否删除此视频的相关文件?\n\n这将删除NFO文件,但不会删除视频文件本身。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(self.nfo_path):
                    os.remove(self.nfo_path)
                    logger.info(f"已删除NFO文件: {self.nfo_path}")
                
                QMessageBox.information(self, "成功", "NFO文件已删除")
                self.accept()
            except Exception as e:
                logger.error(f"删除NFO文件失败: {e}")
                QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")
    
    def _load_poster(self):
        """加载海报图片（支持离线模式）"""
        if hasattr(self.movie, 'poster_path') and self.movie.poster_path:
            poster_path = self.movie.poster_path
            cache_manager = PosterCacheManager()
            
            # 1. 先尝试从缓存加载（仅精确尺寸）
            cached_pixmap = cache_manager.get_cached_pixmap(poster_path, 300, 450, allow_cross_size_reuse=False)
            if cached_pixmap is not None:
                self.poster_display.setPixmap(cached_pixmap)
                self.poster_path_field.setText(poster_path)
                return
            
            # 2. 精确缓存未命中，检查原图是否可访问
            file_accessible = False
            try:
                if os.path.exists(poster_path):
                    file_accessible = True
            except OSError:
                # 网络路径不可访问（离线模式）
                file_accessible = False
            
            if file_accessible:
                # 3. 加载原图并缓存（在线模式，优先高清）
                pixmap = QPixmap(poster_path)
                if not pixmap.isNull():
                    # 缩放并缓存
                    scaled = pixmap.scaled(
                        300, 450,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    cache_manager.save_to_cache(poster_path, 300, 450, scaled)
                    self.poster_display.setPixmap(scaled)
                    self.poster_path_field.setText(poster_path)
            else:
                # 4. 离线模式，尝试跨尺寸缓存复用
                cached_pixmap = cache_manager.get_cached_pixmap(poster_path, 300, 450, allow_cross_size_reuse=True)
                if cached_pixmap is not None:
                    self.poster_display.setPixmap(cached_pixmap)
                    self.poster_path_field.setText(poster_path)
            # 离线模式且无缓存时，不加载海报
    
    def _browse_poster(self):
        """浏览并选择新的海报图片"""
        video_dir = os.path.dirname(self.nfo_path)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择海报图片",
            video_dir,
            "图片文件 (*.jpg *.jpeg *.png)"
        )
        
        if file_path:
            # 显示新海报
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self.poster_display.setPixmap(pixmap)
                self.poster_path_field.setText(file_path)
                
                # 如果选择的不是poster.jpg，复制过去
                target_path = os.path.join(video_dir, "poster.jpg")
                if file_path != target_path:
                    try:
                        shutil.copy2(file_path, target_path)
                        self.poster_path_field.setText(target_path)
                        QMessageBox.information(self, "成功", f"海报已保存为: {target_path}")
                    except Exception as e:
                        logger.error(f"复制海报失败: {e}")
                        QMessageBox.warning(self, "警告", f"复制海报失败: {str(e)}")
    
    def _load_tags(self):
        """从DFO加载自定义标签（使用<custom>元素，与电影关键词<tag>区分）"""
        try:
            if os.path.exists(self.nfo_path):
                tree = ET.parse(self.nfo_path)
                root = tree.getroot()
                
                # 读取所有custom元素（用户自定义标签）
                # 注意：不读取<tag>，因为那是媒体服务器从 TMDB 获取的电影关键词
                custom_tags = root.findall('custom')
                for tag_elem in custom_tags:
                    if tag_elem.text:
                        item = QListWidgetItem(tag_elem.text)
                        self.tag_list.addItem(item)
        except Exception as e:
            logger.error(f"加载标签失败: {e}")
    
    def _add_tag(self):
        """添加新标签"""
        tag_text = self.tag_input.text().strip()
        if tag_text:
            # 检查是否已存在
            existing_tags = [self.tag_list.item(i).text() for i in range(self.tag_list.count())]
            if tag_text not in existing_tags:
                item = QListWidgetItem(tag_text)
                self.tag_list.addItem(item)
                self.tag_input.clear()
            else:
                QMessageBox.information(self, "提示", "该标签已存在")
    
    def _remove_tag(self):
        """删除选中的标签"""
        current_item = self.tag_list.currentItem()
        if current_item:
            row = self.tag_list.row(current_item)
            self.tag_list.takeItem(row)
    
    def _load_metadata(self):
        """从NFO加载编码信息"""
        try:
            if os.path.exists(self.nfo_path):
                tree = ET.parse(self.nfo_path)
                root = tree.getroot()
                
                # 查找fileinfo元素
                fileinfo = root.find('fileinfo')
                if fileinfo is not None:
                    streamdetails = fileinfo.find('streamdetails')
                    if streamdetails is not None:
                        # root节点
                        streams_root = QTreeWidgetItem(self.metadata_tree, ["streams", ""])
                        
                        # 视频信息
                        for idx, video in enumerate(streamdetails.findall('video')):
                            video_item = QTreeWidgetItem(streams_root, [str(idx), "video"])
                            self._add_stream_details(video_item, video)
                        
                        # 音频信息
                        for idx, audio in enumerate(streamdetails.findall('audio')):
                            audio_item = QTreeWidgetItem(streams_root, [str(idx), "audio"])
                            self._add_stream_details(audio_item, audio)
                        
                        # 字幕信息
                        subtitles = streamdetails.findall('subtitle')
                        if subtitles:
                            subtitle_count = {}
                            for subtitle in subtitles:
                                lang = subtitle.find('language')
                                lang_text = lang.text if lang is not None and lang.text else 'unknown'
                                subtitle_count[lang_text] = subtitle_count.get(lang_text, 0) + 1
                            
                            for lang, count in subtitle_count.items():
                                QTreeWidgetItem(streams_root, [f"subtitle ({lang})", f"{count} 轨"])
                        
                        self.metadata_tree.expandAll()
        except Exception as e:
            logger.error(f"加载编码信息失败: {e}")
    
    def _add_stream_details(self, parent_item, stream_elem):
        """添加流详细信息到树节点"""
        for child in stream_elem:
            if child.text:
                QTreeWidgetItem(parent_item, [child.tag, child.text])
    
    def _save_tags(self, root):
        """保存自定义标签到NFO（使用<custom>元素）"""
        # 先删除所有旧的custom元素
        for elem in root.findall('custom'):
            root.remove(elem)
        
        # 添加新的custom元素（用户自定义标签）
        # 注意：不修改<tag>元素，保留电影关键词
        for i in range(self.tag_list.count()):
            tag_text = self.tag_list.item(i).text()
            if tag_text:
                custom_elem = ET.SubElement(root, 'custom')
                custom_elem.text = tag_text

