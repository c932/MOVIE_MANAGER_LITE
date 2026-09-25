r"""
本地已安装游戏扫描器

两个来源：
1. 开始菜单快捷方式：%ProgramData% 与 %APPDATA% 的 Start Menu\Programs 下遍历 .lnk
2. 配置目录扫描：每个一级子目录视为一款游戏（深度≤2 找 exe，优先与目录同名的 exe，
   否则取最大的合格 exe）

输出条目 {name, exe_path, source}；与游戏库的名称匹配由主窗口完成。
"""
import logging
import os

from PyQt6.QtCore import QThread, pyqtSignal

from gamewall.lnk_parser import parse_lnk

logger = logging.getLogger(__name__)

# 排除明显非游戏主程序的 exe
_SKIP_EXE_KEYWORDS = ("uninstall", "uninst", "setup", "install", "redist",
                      "vcredist", "dxsetup", "crash", "unity", "config",
                      "settings", "update", "eac", "easyanticheat")

_START_MENU_ROOTS = (
    os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                 r"Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.environ.get("APPDATA", ""),
                 r"Microsoft\Windows\Start Menu\Programs"),
)


def _is_game_exe(name: str) -> bool:
    low = name.lower()
    if not low.endswith(".exe"):
        return False
    return not any(k in low for k in _SKIP_EXE_KEYWORDS)


def _is_uninstall_shortcut(name: str, exe_path: str) -> bool:
    """「卸载 XXX」「Uninstall XXX」类快捷方式，避免误匹配游戏本体"""
    low_name = name.lower()
    if low_name.startswith(("uninstall", "uninst")) or name.startswith("卸载"):
        return True
    return "uninst" in os.path.basename(exe_path).lower()


def _find_game_exe(game_dir: str):
    """
    在游戏目录内（深度≤2）挑选主程序 exe。
    优先级：根级同名 exe > 根级最大合格 exe > 深层同名 exe > 深层最大合格 exe。
    """
    folder_name = os.path.basename(os.path.normpath(game_dir))
    root_candidates = []
    deep_candidates = []
    try:
        for entry in os.scandir(game_dir):
            if entry.is_file() and _is_game_exe(entry.name):
                try:
                    root_candidates.append((entry.path, entry.stat().st_size))
                except OSError:
                    continue
            elif entry.is_dir():
                try:
                    for sub in os.scandir(entry.path):
                        if sub.is_file() and _is_game_exe(sub.name):
                            try:
                                deep_candidates.append((sub.path, sub.stat().st_size))
                            except OSError:
                                continue
                except OSError:
                    continue
    except OSError:
        return None

    for candidates in (root_candidates, deep_candidates):
        for path, _size in candidates:
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem.lower() == folder_name.lower():
                return path
    for candidates in (root_candidates, deep_candidates):
        if candidates:
            return max(candidates, key=lambda c: c[1])[0]
    return None


class InstalledGameScanner(QThread):
    finished_with = pyqtSignal(list)   # [{name, exe_path, source}]

    def __init__(self, game_dirs, parent=None):
        super().__init__(parent)
        self._game_dirs = [str(d) for d in (game_dirs or []) if str(d).strip()]
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        entries = []
        seen_exe = set()
        try:
            entries.extend(self._scan_start_menu(seen_exe))
            entries.extend(self._scan_dirs(seen_exe))
        except Exception as e:
            logger.error(f"本地游戏扫描异常: {e}")
        logger.info(f"本地游戏扫描完成: {len(entries)} 个候选")
        if not self._cancelled:
            self.finished_with.emit(entries)

    def _scan_start_menu(self, seen_exe: set):
        out = []
        for root in _START_MENU_ROOTS:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                if self._cancelled:
                    return out
                # 剪掉目录联接/符号链接，避免跟随重定向的开始菜单产生
                # 无限递归或跨网络路径的长耗时扫描（原地修改 dirnames 即阻止下钻）
                dirnames[:] = [d for d in dirnames
                               if not os.path.islink(os.path.join(dirpath, d))]
                for fn in filenames:
                    if not fn.lower().endswith(".lnk"):
                        continue
                    lnk_path = os.path.join(dirpath, fn)
                    exe_path = parse_lnk(lnk_path)
                    if not exe_path or exe_path.lower() in seen_exe:
                        continue
                    if _is_uninstall_shortcut(os.path.splitext(fn)[0], exe_path):
                        continue
                    seen_exe.add(exe_path.lower())
                    out.append({"name": os.path.splitext(fn)[0],
                                "exe_path": exe_path, "source": "lnk"})
        return out

    def _scan_dirs(self, seen_exe: set):
        out = []
        for base in self._game_dirs:
            if self._cancelled:
                return out
            if not os.path.isdir(base):
                logger.warning(f"游戏目录不存在，跳过: {base}")
                continue
            found_any = False
            try:
                subdirs = [e.path for e in os.scandir(base) if e.is_dir()]
            except OSError:
                continue
            for game_dir in subdirs:
                if self._cancelled:
                    return out
                exe_path = _find_game_exe(game_dir)
                if not exe_path or exe_path.lower() in seen_exe:
                    continue
                seen_exe.add(exe_path.lower())
                found_any = True
                out.append({"name": os.path.basename(os.path.normpath(game_dir)),
                            "exe_path": exe_path, "source": "dir"})
            # 目录本身就是单款游戏的情况（根级有合格 exe 且子目录无发现）
            if not found_any:
                exe_path = _find_game_exe(base)
                if exe_path and exe_path.lower() not in seen_exe:
                    seen_exe.add(exe_path.lower())
                    out.append({"name": os.path.basename(os.path.normpath(base)),
                                "exe_path": exe_path, "source": "dir"})
        return out
