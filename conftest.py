"""pytest 根配置：把仓库根与网页版后端目录加入 sys.path。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _p in (ROOT, ROOT / "webapp" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
