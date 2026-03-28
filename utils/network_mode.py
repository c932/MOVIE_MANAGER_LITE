"""
网络可达性与离线缓存模式管理。

策略：
- 启动时仅探测一次 UNC 主机可达性。
- 若全部目标主机不可达，则进入“仅本地缓存模式”。
- 仅本次运行生效，不写入配置文件。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Iterable, Set

logger = logging.getLogger(__name__)

_OFFLINE_CACHE_ONLY = False
_INITIALIZED = False


def is_offline_cache_only() -> bool:
    """是否处于仅本地缓存模式。"""
    return _OFFLINE_CACHE_ONLY


def set_offline_cache_only(value: bool) -> None:
    """设置仅本地缓存模式。"""
    global _OFFLINE_CACHE_ONLY
    _OFFLINE_CACHE_ONLY = bool(value)


def _extract_unc_host(path: str) -> str | None:
    """从 UNC 路径提取主机名，例如 \\192.168.1.2\share -> 192.168.1.2。"""
    if not path:
        return None
    if not (path.startswith("\\\\") or path.startswith("//")):
        return None

    normalized = path.replace("/", "\\")
    tail = normalized[2:]
    if not tail:
        return None
    host = tail.split("\\", 1)[0].strip()
    return host or None


def _is_path_accessible_with_timeout(path: str, timeout: float) -> bool:
    """带超时判断 UNC 路径是否可访问，避免主线程阻塞。"""
    result = {"ok": False}

    def _probe():
        try:
            # 使用 scandir 比 exists 更能反映共享目录可读性
            with os.scandir(path) as it:
                for _ in it:
                    break
            result["ok"] = True
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False
    return result["ok"]


def initialize_offline_cache_mode_once(paths: Iterable[str], timeout: float = 0.35) -> bool:
    """
    启动时初始化一次离线缓存模式。

    返回：最终是否进入仅本地缓存模式。
    """
    global _INITIALIZED

    if _INITIALIZED:
        return _OFFLINE_CACHE_ONLY

    hosts: Set[str] = set()
    unc_paths: list[str] = []
    for p in paths or []:
        p_str = str(p)
        host = _extract_unc_host(p_str)
        if host:
            hosts.add(host)
            unc_paths.append(p_str)

    # 无 UNC 路径则不启用离线缓存模式
    if not hosts:
        set_offline_cache_only(False)
        _INITIALIZED = True
        logger.info("网络模式初始化: 未检测到 UNC 路径，使用常规模式")
        return _OFFLINE_CACHE_ONLY

    reachable = False
    unreachable_hosts: list[str] = []

    # 先按主机记录日志（可观测）
    for host in sorted(hosts):
        logger.info(f"网络模式初始化: 检测主机 {host}")

    # 核心判定改为“共享路径是否可访问”，避免仅端口可达导致误判在线
    for p in unc_paths:
        if _is_path_accessible_with_timeout(p, timeout):
            reachable = True
            logger.info(f"网络模式初始化: 共享路径可访问 {p}")
        else:
            host = _extract_unc_host(p)
            if host and host not in unreachable_hosts:
                unreachable_hosts.append(host)
            logger.warning(f"网络模式初始化: 共享路径不可访问或超时 {p}")

    # 只有当所有 UNC 主机都不可达时，启用仅缓存模式
    set_offline_cache_only(not reachable)
    _INITIALIZED = True

    if _OFFLINE_CACHE_ONLY:
        logger.warning(
            "网络模式初始化: 进入仅本地缓存模式（本次运行）"
            f"，不可达主机: {', '.join(unreachable_hosts)}"
        )
    else:
        logger.info("网络模式初始化: 使用常规模式")

    return _OFFLINE_CACHE_ONLY
