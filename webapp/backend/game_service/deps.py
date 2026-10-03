"""游戏墙服务共享依赖：获取 GameStore、404 处理、同步网络调用限时。"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, TypeVar

from fastapi import HTTPException, Request

from gamewall.name_utils import normalize_name

from .store import GameStore

T = TypeVar("T")


def get_store(request: Request) -> GameStore:
    """取当前 app 的 GameStore（懒初始化 + 锁）。

    有状态对象绝不放在模块导入期：每个 app 实例（不同数据目录）各自持有一份。
    """
    app = request.app
    store = getattr(app.state, "store", None)
    if store is not None:
        return store

    lock = getattr(app.state, "store_lock", None)
    if lock is None:
        lock = threading.Lock()
        app.state.store_lock = lock
    with lock:
        store = getattr(app.state, "store", None)
        if store is None:
            store = GameStore(app.state.settings)
            app.state.store = store
    return store


def require_game(store: GameStore, key: str) -> Any:
    """按 key 取游戏（归一化到 norm_key），不存在抛 404。"""
    game = store.get(normalize_name(key or ""))
    if game is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {key}")
    return game


def call_with_timeout(fn: Callable[[], T], timeout: float, detail: str) -> T:
    """
    在守护线程里执行同步网络调用并限时等待（契约的「同步（≤Ns）」约定）。

    - 超时：抛 502，调用方不得应用任何结果（线程在后台自行结束）；
    - 异常：原样重抛（HTTPException/SteamCancelled 等透传到错误处理层）。
    """
    box: Dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001  需要原样带回调用线程
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_target, name="game-sync-call", daemon=True).start()
    if not done.wait(timeout):
        raise HTTPException(status_code=502,
                            detail=f"{detail}（超时 {timeout:g}s，已中止）")
    if "error" in box:
        raise box["error"]
    return box.get("value")
