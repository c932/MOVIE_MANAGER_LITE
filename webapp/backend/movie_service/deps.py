"""路由共享依赖：懒初始化 MovieStore、404 处理、详情 DTO 构建。"""
from __future__ import annotations

import threading
from typing import Any, Dict

from fastapi import HTTPException, Request

from models.movie import Movie

from .store import MovieStore


def get_store(request: Request) -> MovieStore:
    """
    取当前 app 的 MovieStore（懒初始化 + 锁）。

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
            store = MovieStore(app.state.settings)
            app.state.store = store
    return store


def require_movie(store: MovieStore, movie_key: str) -> Movie:
    """按 id 取电影，不存在抛 404。"""
    movie = store.get(movie_key)
    if movie is None:
        raise HTTPException(status_code=404, detail=f"电影不存在: {movie_key}")
    return movie


def detail_dto(store: MovieStore, movie: Movie) -> Dict[str, Any]:
    """MovieDetail（不截断，含榜单名次）。"""
    return store.dto(movie, detail=True, rank_lookups=store.rank_lookups())
