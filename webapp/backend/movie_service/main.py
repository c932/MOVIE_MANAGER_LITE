"""
电影墙 Web 服务入口。

启动（仓库根目录）：
    MML_DATA_DIR=/var/lib/movie-wall \
    PYTHONPATH=".:webapp/backend" \
    uvicorn movie_service.main:app --host 127.0.0.1 --port 8010
"""
import threading
from typing import Optional

from fastapi import FastAPI

from wall_common.factory import create_app, jobs_router


def create(data_dir: Optional[str] = None, extra_routers: Optional[list] = None) -> FastAPI:
    """构建电影墙应用（测试传入临时数据目录）。"""
    from .router import router

    routers = [router, jobs_router()]
    if extra_routers:
        routers.extend(extra_routers)
    app = create_app(
        service="movie",
        title="Movie Wall API",
        version="3.5.0",
        routers=routers,
        data_dir=data_dir,
    )
    # 有状态对象只挂在 app 实例上（绝不放模块导入期）：
    # store 由 deps.get_store() 懒初始化，多 app/多数据目录互不干扰
    app.state.store = None
    app.state.store_lock = threading.Lock()
    return app


app = create()
