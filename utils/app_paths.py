"""
应用路径工具
统一管理项目根目录与 data 目录中的运行数据文件。
"""
from pathlib import Path
import logging
import shutil

logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def ensure_data_dir() -> Path:
    """确保 data 目录存在并返回该路径。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def resolve_data_file(filename: str) -> Path:
    """
    获取 data 目录中的目标文件路径。
    若检测到旧版根目录文件且 data 目录中不存在同名文件，则自动迁移。
    """
    ensure_data_dir()

    target = DATA_DIR / filename
    legacy = PROJECT_ROOT / filename

    if not target.exists() and legacy.exists():
        try:
            shutil.move(str(legacy), str(target))
            logger.info(f"已迁移旧数据文件: {legacy} -> {target}")
        except Exception as e:
            logger.warning(f"迁移旧数据文件失败，继续使用新路径: {e}")

    return target
