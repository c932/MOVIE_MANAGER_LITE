"""
本地已安装游戏扫描（网页版，非 Qt）。

复刻 `gamewall/local_scanner.py` 的判定与匹配逻辑，去掉 QThread/信号：
- 每个配置的 game_dirs：一级子目录视为一款游戏，目录内（深度≤2）挑主程序 exe，
  子目录没找到时回退到 game_dirs 自身；另外收集目录树内的 .lnk（深度≤2）。
- 不扫开始菜单：服务端没有桌面环境，契约只要求 game_dirs 内的 exe/.lnk。
- 符号链接一律剪掉，避免重定向/网络路径造成递归与长耗时扫描。

输出条目 `{name, exe_path, source}`（source: `dir` | `lnk`）；
与游戏库的名称匹配由 `match_local_entry` 完成（语义同桌面版）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from gamewall.lnk_parser import parse_lnk
from gamewall.name_utils import normalize_name

logger = logging.getLogger("game_service.scanner")

# 排除明显非游戏主程序的 exe（与桌面版一致）
_SKIP_EXE_KEYWORDS = ("uninstall", "uninst", "setup", "install", "redist",
                      "vcredist", "dxsetup", "crash", "unity", "config",
                      "settings", "update", "eac", "easyanticheat")

# game_dirs 内下钻的最大层级（根目录为 0）
_MAX_DEPTH = 2


def _is_game_exe(name: str) -> bool:
    low = name.lower()
    if not low.endswith(".exe"):
        return False
    return not any(keyword in low for keyword in _SKIP_EXE_KEYWORDS)


def _is_uninstall_shortcut(name: str, exe_path: str) -> bool:
    """「卸载 XXX」「Uninstall XXX」类快捷方式，避免误匹配游戏本体。"""
    low_name = name.lower()
    if low_name.startswith(("uninstall", "uninst")) or name.startswith("卸载"):
        return True
    return "uninst" in os.path.basename(exe_path).lower()


def find_game_exe(game_dir: str) -> Optional[str]:
    """
    在游戏目录内（深度≤2）挑选主程序 exe。
    优先级：根级同名 exe > 根级最大合格 exe > 深层同名 exe > 深层最大合格 exe。
    """
    folder_name = os.path.basename(os.path.normpath(game_dir))
    root_candidates: List[Tuple[str, int]] = []
    deep_candidates: List[Tuple[str, int]] = []
    try:
        for entry in os.scandir(game_dir):
            if entry.is_file() and _is_game_exe(entry.name):
                try:
                    root_candidates.append((entry.path, entry.stat().st_size))
                except OSError:
                    continue
            elif entry.is_dir() and not entry.is_symlink():
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
            return max(candidates, key=lambda item: item[1])[0]
    return None


def scan_installed(game_dirs: Iterable[str],
                   cancelled=None) -> List[Dict[str, str]]:
    """
    扫描配置目录，返回候选条目 `[{name, exe_path, source}]`。

    Args:
        game_dirs: 配置的本地游戏目录列表
        cancelled: 可选的取消回调（任务协作式取消），返回 True 时立即结束
    """
    entries: List[Dict[str, str]] = []
    seen_exe: set = set()
    for base in (str(d) for d in (game_dirs or []) if str(d).strip()):
        if cancelled and cancelled():
            break
        if not os.path.isdir(base):
            logger.warning("游戏目录不存在，跳过: %s", base)
            continue
        found_any = False
        subdirs: List[str] = []
        try:
            subdirs = [entry.path for entry in os.scandir(base) if entry.is_dir()]
        except OSError:
            continue
        for game_dir in subdirs:
            if cancelled and cancelled():
                return entries
            if os.path.islink(game_dir):
                continue
            exe_path = find_game_exe(game_dir)
            if not exe_path or exe_path.lower() in seen_exe:
                continue
            seen_exe.add(exe_path.lower())
            found_any = True
            entries.append({
                "name": os.path.basename(os.path.normpath(game_dir)),
                "exe_path": exe_path,
                "source": "dir",
            })
        # 目录本身就是单款游戏的情况（根级有合格 exe 且子目录无发现）
        if not found_any:
            exe_path = find_game_exe(base)
            if exe_path and exe_path.lower() not in seen_exe:
                seen_exe.add(exe_path.lower())
                entries.append({
                    "name": os.path.basename(os.path.normpath(base)),
                    "exe_path": exe_path,
                    "source": "dir",
                })
        entries.extend(_scan_lnk(base, seen_exe, cancelled))
    return entries


def _scan_lnk(base: str, seen_exe: set, cancelled=None) -> List[Dict[str, str]]:
    """收集 game_dirs 内（深度≤2）的 .lnk，解析出目标 exe。"""
    out: List[Dict[str, str]] = []
    root = Path(base)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if cancelled and cancelled():
            return out
        relative = Path(dirpath).relative_to(root)
        depth = len(relative.parts)
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
        # 剪掉符号链接，避免跟随重定向产生无限递归或跨网络路径的长耗时扫描
        dirnames[:] = [name for name in dirnames
                       if not os.path.islink(os.path.join(dirpath, name))]
        for filename in filenames:
            if not filename.lower().endswith(".lnk"):
                continue
            lnk_path = os.path.join(dirpath, filename)
            exe_path = parse_lnk(lnk_path)
            if not exe_path or exe_path.lower() in seen_exe:
                continue
            stem = os.path.splitext(filename)[0]
            if _is_uninstall_shortcut(stem, exe_path):
                continue
            seen_exe.add(exe_path.lower())
            out.append({"name": stem, "exe_path": exe_path, "source": "lnk"})
    return out


# ─────────────────── 与游戏库匹配 ───────────────────


def build_match_index(games) -> Tuple[Dict[str, object], Dict[str, Dict[str, object]]]:
    """
    建立「归一化名 → 游戏」索引与首字符分桶（语义同桌面版 _on_local_scan_finished）。

    原始名/中文名/英文名全部参与匹配（快捷方式名可能是其中任意一种）。
    """
    index: Dict[str, object] = {}
    for game in games:
        for name in (game.raw_name, game.title_cn, game.title_en):
            if name:
                index.setdefault(normalize_name(name), game)
    buckets: Dict[str, Dict[str, object]] = {}
    for key in index:
        buckets.setdefault(key[0], {})[key] = index[key]
    return index, buckets


def match_local_entry(name: str, index: Dict[str, object],
                      buckets: Dict[str, Dict[str, object]]):
    """
    扫描到的名称 → 游戏库匹配：归一化精确 → 长度比≥0.6 的唯一包含。

    归一化名过短（≤4 字符）时跨桶都可能是子串，兜底走全量扫描避免漏判。
    """
    nq = normalize_name(name)
    if not nq:
        return None
    game = index.get(nq)
    if game:
        return game

    if len(nq) <= 4:
        candidates = index.items()
    else:
        candidates = buckets.get(nq[0], {}).items()

    hits = []
    for key, candidate in candidates:
        if len(key) < 3:
            continue
        ratio = min(len(nq), len(key)) / max(len(nq), len(key))
        if ratio < 0.6:
            continue
        if nq in key or key in nq:
            hits.append(candidate)
    return hits[0] if len(hits) == 1 else None
