"""WP0 冒烟测试：电影墙服务都能按需创建并响应 health/system/jobs。"""


def test_movie_app_boots(service_data_dir):
    from fastapi.testclient import TestClient
    from movie_service.main import create

    with TestClient(create(data_dir=str(service_data_dir))) as client:
        r = client.get("/api/movie/health")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["service"] == "movie"
        assert body["data_dir"] == str(service_data_dir)

        r = client.get("/api/movie/system/info")
        assert r.status_code == 200, r.text

        r = client.get("/api/movie/jobs")
        assert r.status_code == 200
        assert r.json()["jobs"] == []

        r = client.get("/api/movie/jobs/nonexistent")
        assert r.status_code == 404




def test_job_lifecycle(service_data_dir):
    """任务提交/进度/结果/取消的端到端行为。"""
    import time

    from fastapi.testclient import TestClient
    from movie_service.main import create
    from wall_common.jobs import JobContext

    with TestClient(create(data_dir=str(service_data_dir))) as client:
        # 普通任务
        def work(ctx: JobContext):
            ctx.update(current=1, total=2, stage="测试")
            ctx.log("第一步")
            ctx.check_cancelled()
            ctx.update(current=2, message="第二步")
            return {"ok": True}

        app = client.app
        job = app.state.jobs.submit("test.task", work)
        job = app.state.jobs.wait(job.id, timeout=10)
        assert job.status == "done"
        assert job.result == {"ok": True}
        assert job.logs == ["第一步"]

        r = client.get(f"/api/movie/jobs/{job.id}")
        assert r.status_code == 200
        assert r.json()["status"] == "done"

        # 失败任务
        def boom(ctx: JobContext):
            raise ValueError("故意失败")

        job2 = app.state.jobs.submit("test.boom", boom)
        job2 = app.state.jobs.wait(job2.id, timeout=10)
        assert job2.status == "error"
        assert "故意失败" in job2.error

        # unique 提交：同类未完成任务复用
        def slow(ctx: JobContext):
            for _ in range(50):
                ctx.check_cancelled()
                time.sleep(0.05)
            return "done"

        j1 = app.state.jobs.submit("test.slow", slow, unique=True)
        j2 = app.state.jobs.submit("test.slow", slow, unique=True)
        assert j1.id == j2.id
        app.state.jobs.cancel(j1.id)
        final = app.state.jobs.wait(j1.id, timeout=10)
        assert final.status == "cancelled"
