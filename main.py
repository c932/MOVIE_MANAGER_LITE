"""
Local Movie Wall - 本地电影海报墙
应用程序主入口

这是一个纯本地、零网络请求的电影管理软件
基于 PyQt6 构建，使用明亮鲜艳的现代化主题
"""
import sys
import logging
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QLockFile
from PyQt6.QtGui import QFont

from ui.main_window import MainWindow

# === 配置日志系统 ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 进程级单实例锁，需保持全局引用避免被提前释放
_app_lock = None


def load_stylesheet(app: QApplication):
    """
    加载全局 QSS 样式表
    
    Args:
        app: QApplication 实例
    """
    # 获取资源目录路径（支持打包后的环境）
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后，资源在_MEIPASS临时目录
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).parent
    
    qss_path = base_dir / "styles" / "style.qss"
    
    if qss_path.exists():
        try:
            with open(qss_path, 'r', encoding='utf-8') as f:
                stylesheet = f.read()
                app.setStyleSheet(stylesheet)
            logger.info(f"样式表加载成功: {qss_path}")
        except Exception as e:
            logger.error(f"样式表加载失败: {e}")
    else:
        logger.warning(f"样式表文件不存在: {qss_path}")


def main():
    """应用程序主入口"""
    global _app_lock

    # 单实例保护：避免重复启动导致资源竞争和体验混乱
    lock_path = Path(tempfile.gettempdir()) / "movie_manager_lite.lock"
    _app_lock = QLockFile(str(lock_path))
    _app_lock.setStaleLockTime(0)
    if not _app_lock.tryLock(0):
        app = QApplication(sys.argv)
        QMessageBox.information(None, "提示", "程序已经在运行中。")
        return

    logger.info("=" * 60)
    logger.info("Local Movie Wall - 本地电影海报墙")
    logger.info("版本: 1.0.0")
    logger.info("=" * 60)
    
    # 启用高 DPI 支持（Windows 10/11） - 必须在创建 QApplication 之前设置
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # 创建应用实例
    app = QApplication(sys.argv)
    
    # 设置应用信息
    app.setApplicationName("Local Movie Wall")
    app.setOrganizationName("LocalMovieWall")
    app.setApplicationVersion("1.0.0")
    
    # 设置全局默认字体
    app.setFont(QFont("Microsoft YaHei", 10))
    
    # 加载样式表
    load_stylesheet(app)
    
    # 创建并显示主窗口
    logger.info("正在初始化主窗口...")
    main_window = MainWindow()
    main_window.show()
    
    logger.info("应用程序启动完成")
    logger.info("=" * 60)
    
    # 进入事件循环
    try:
        sys.exit(app.exec())
    finally:
        if _app_lock is not None:
            _app_lock.unlock()


if __name__ == "__main__":
    main()
