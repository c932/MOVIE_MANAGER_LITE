"""契约 2.2/2.4：设置读写、媒体库刷新任务、library/info。"""
import time

from tests.webapp.test_movie_helpers import (
    add_movie,
    build_library,
    movie_client,
    movies_of,
    prepare_library,
    refresh,
    set_movie_paths,
    wait_job,
)


def test_settings_roundtrip_and_validation(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        # 默认值（契约 2.4 结构）
        response = client.get("/api/movie/settings")
        assert response.status_code == 200, response.text
        body = response.json()
        for key in (
            "movie_paths",
            "blacklist_folders",
            "blacklist_patterns",
            "poster_width",
            "poster_height",
            "grid_columns",
            "poster_scale",
        ):
            assert key in body
        assert body["movie_paths"] == []
        assert body["poster_width"] == 200 and body["poster_height"] == 300

        # 部分字段更新
        response = client.put(
            "/api/movie/settings",
            json={
                "movie_paths": [str(library["root"])],
                "blacklist_folders": ["Extras"],
                "blacklist_patterns": [".*[Ss]ample.*"],
                "poster_width": 240,
                "poster_height": 360,
                "grid_columns": 6,
                "poster_scale": 78,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"saved": True}

        updated = client.get("/api/movie/settings").json()
        assert updated["movie_paths"] == [str(library["root"])]
        assert updated["blacklist_folders"] == ["Extras"]
        assert updated["poster_width"] == 240
        assert updated["grid_columns"] == 6
        assert updated["poster_scale"] == 78

        # 只改一个键，其它键保持不变
        client.put("/api/movie/settings", json={"grid_columns": 4})
        again = client.get("/api/movie/settings").json()
        assert again["grid_columns"] == 4
        assert again["poster_width"] == 240
        assert again["poster_scale"] == 78

        # 非法取值 → 400
        for bad in ({"poster_width": 0}, {"grid_columns": 0}, {"poster_scale": 999}):
            assert client.put("/api/movie/settings", json=bad).status_code == 400


def test_library_info_shape(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        set_movie_paths(client, [library["root"]])
        info = client.get("/api/movie/library/info").json()
        assert info["cache_info"] is None  # 尚未刷新
        assert info["scanning"] is None
        assert info["paths_exist"] == [{"path": str(library["root"]), "exists": True}]

        # 不存在的目录 exists=False
        client.put(
            "/api/movie/settings",
            json={"movie_paths": [str(library["root"]), "/不存在的目录"]},
        )
        info = client.get("/api/movie/library/info").json()
        assert info["paths_exist"] == [
            {"path": str(library["root"]), "exists": True},
            {"path": "/不存在的目录", "exists": False},
        ]

        # 刷新后有缓存信息
        set_movie_paths(client, [library["root"]])
        refresh(client, force=True)
        info = client.get("/api/movie/library/info").json()
        assert info["cache_info"]["movie_count"] == 2
        assert info["scanning"] is None


def test_refresh_without_paths_fails_with_detail(service_data_dir):
    """未配置电影目录时刷新任务落 error，中文提示。"""
    with movie_client(service_data_dir) as client:
        response = client.post("/api/movie/library/refresh", json={"force": False})
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "error"
        assert "电影目录" in job["error"]
        assert client.get("/api/movie/library/info").json()["scanning"] is None


def test_refresh_progress_and_cancel(service_data_dir):
    """刷新任务上报进度，可协作取消。"""
    import movie_service.tasks as tasks

    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        set_movie_paths(client, [library["root"]])
        client.app.state.store = None  # 强制按当前设置重新建 store

        # 慢速扫描替身：足够长以便取消
        def slow_scan(movie_paths, folders, patterns, *, progress=None, check_cancelled=None):
            for step in range(200):
                if check_cancelled:
                    check_cancelled()
                if progress:
                    progress(step, 200, f"扫描中 {step}")
                time.sleep(0.01)
            return []

        original = tasks.scan_library
        tasks.scan_library = slow_scan
        try:
            response = client.post("/api/movie/library/refresh", json={"force": False})
            job_id = response.json()["job_id"]

            # 轮询到 running 且已有进度
            deadline = time.time() + 5
            seen_progress = False
            while time.time() < deadline:
                job = client.get(f"/api/movie/jobs/{job_id}").json()
                if job["total"] or job["current"] or job["logs"]:
                    seen_progress = True
                    break
                time.sleep(0.01)
            assert seen_progress

            cancelled = client.post(f"/api/movie/jobs/{job_id}/cancel")
            assert cancelled.status_code == 200

            final = wait_job(client, job_id)
            assert final["status"] == "cancelled"
        finally:
            tasks.scan_library = original

        # 取消后再次刷新仍可用
        task = refresh(client, force=True)
        assert task["status"] == "done"


def test_refresh_scan_empty_keeps_local_records(service_data_dir):
    """扫描结果为空时不清理本地记录（防误删）。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = next(m for m in movies_of(client) if m["title"] == "电锯惊魂")
        client.post(f"/api/movie/movies/{saw['id']}/watched", json={"watched": True})

        # 目录全部改指向不存在的位置 → 扫描为空
        set_movie_paths(client, [service_data_dir / "no-such-dir"])
        client.app.state.store = None
        job = refresh(client, force=False, expect="done")
        assert job["result"]["total"] == 0
        assert job["result"]["removed"] == 0

        # 观看记录仍在（未被 prune）
        import json

        data = json.loads((service_data_dir / "watch_history.json").read_text("utf-8"))
        assert data["total"] == 1


def test_blacklist_folder_is_skipped(service_data_dir):
    """黑名单文件夹中的 NFO 不入库。"""
    library = build_library(service_data_dir / "library")
    add_movie(
        library["root"] / "Extras" / "Trailer",
        "Trailer",
        title="预告片",
        poster=False,
    )

    with movie_client(service_data_dir) as client:
        set_movie_paths(client, [library["root"]])
        client.put("/api/movie/settings", json={"blacklist_folders": ["Extras"]})
        refresh(client, force=True)
        titles = [m["title"] for m in movies_of(client)]
        assert "预告片" not in titles
        assert len(titles) == 2
