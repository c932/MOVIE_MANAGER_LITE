"""
Local Game Wall - 本地游戏海报墙
应用程序主入口

与 LocalMovieWall（电影墙）同仓库的独立应用，复用同一套 QSS 主题，
数据目录独立于电影墙（%APPDATA%\\LocalGameWall\\data）
"""
import os

# 必须在导入任何项目模块之前设置：使 utils.app_paths 解析到游戏墙独立数据目录
os.environ.setdefault("APP_DIR_NAME_OVERRIDE", "LocalGameWall")

import sys
import logging
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QLockFile
from PyQt6.QtGui import QFont

from gamewall.game_main_window import GameMainWindow

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

_app_lock = None


def load_stylesheet(app: QApplication):
    """加载全局 QSS 样式表（与电影墙共用 styles/style.qss）"""
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).parent

    qss_path = base_dir / "styles" / "style.qss"

    if qss_path.exists():
        try:
            with open(qss_path, 'r', encoding='utf-8') as f:
                app.setStyleSheet(f.read())
            logger.info(f"样式表加载成功: {qss_path}")
        except Exception as e:
            logger.error(f"样式表加载失败: {e}")
    else:
        logger.warning(f"样式表文件不存在: {qss_path}")


def main():
    global _app_lock

    # 单实例保护（锁名与电影墙不同，两应用可并存）
    lock_path = Path(tempfile.gettempdir()) / "local_game_wall.lock"
    _app_lock = QLockFile(str(lock_path))
    _app_lock.setStaleLockTime(0)
    if not _app_lock.tryLock(0):
        app = QApplication(sys.argv)
        QMessageBox.information(None, "提示", "游戏库程序已经在运行中。")
        return

    logger.info("=" * 60)
    logger.info("Local Game Wall - 本地游戏海报墙")
    logger.info("版本: 1.0.0")
    logger.info("=" * 60)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Local Game Wall")
    app.setOrganizationName("LocalGameWall")
    app.setApplicationVersion("1.0.0")
    app.setFont(QFont("Microsoft YaHei", 10))

    load_stylesheet(app)

    logger.info("正在初始化主窗口...")
    main_window = GameMainWindow()
    main_window.show()

    logger.info("应用程序启动完成")

    try:
        sys.exit(app.exec())
    finally:
        if _app_lock is not None:
            _app_lock.unlock()


if __name__ == "__main__":
    main()
