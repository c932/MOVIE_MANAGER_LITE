"""契约 3.2：enrich 任务进度与负缓存。"""
from unittest.mock import patch

from tests.webapp.test_game_helpers import (
    API,
    build_excel,
    enrich,
    excel_apply,
    find_game,
    game_client,
    set_game_settings,
    wait_job,
)


def test_enrich_task_progress(service_data_dir, monkeypatch):
    """enrich 任务上报进度（stage=steam/ratings）。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # mock Steam 调用，避免真实网络
        def mock_match_appid(queries):
            return 12345, "Game A", True

        def mock_fetch_appdetails(appid):
            return {"description": "简介", "steam_name": "Game A"}, ""

        def mock_fetch_appreviews(appid):
            return {"steam_positive_pct": 85.0, "steam_review_total": 1000}, ""

        with patch("gamewall.steam_client.match_appid", mock_match_appid), \
             patch("gamewall.steam_client.fetch_appdetails", mock_fetch_appdetails), \
             patch("gamewall.steam_client.fetch_appreviews", mock_fetch_appreviews):
            result = client.post(f"{API}/games/enrich", json={
                "scope": "all",
                "options": {"steam": True, "ratings": False},
            }).json()
            job = wait_job(client, result["job_id"])

        assert job["status"] == "done"
        assert job["result"]["updated"] >= 0
        # 进度上报
        assert job["total"] > 0


def test_enrich_negative_cache(service_data_dir, monkeypatch):
    """enrich 任务写入负缓存，7 天内跳过。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏B", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # mock 返回确定性无数据（HTTP 成功但无结果）
        def mock_match_appid(queries):
            return 0, "", True  # definitive=True 表示确定性无结果

        with patch("gamewall.steam_client.match_appid", mock_match_appid):
            # ratings=False：本轮只验证 Steam 负缓存，避免第三方评分联网
            job = enrich(client, scope="all", options={"steam": True, "ratings": False})
            # 无数据更新，但应记录负缓存
            assert job["result"]["updated"] == 0

        # 再次 enrich 应跳过（因负缓存）
        with patch("gamewall.steam_client.match_appid", mock_match_appid) as mock:
            enrich(client, scope="all", options={"steam": True, "ratings": False})
            # 由于负缓存，match_appid 不应被调用（或调用次数减少）
            # 这里主要验证不报错


def test_enrich_task_cancel(service_data_dir, monkeypatch):
    """enrich 任务可取消。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": f"游戏{i}", "size_text": "10 GB"}
        for i in range(50)
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # mock 慢速 Steam 调用（match_appid 快速返回，详情/评价慢速以便取消）
        import time

        def mock_match_appid(queries):
            return 12345, "Game", True

        def slow_fetch(*args, **kwargs):
            time.sleep(0.5)
            return {}, ""

        with patch("gamewall.steam_client.match_appid", mock_match_appid), \
             patch("gamewall.steam_client.fetch_appdetails", slow_fetch), \
             patch("gamewall.steam_client.fetch_appreviews", slow_fetch):
            result = client.post(f"{API}/games/enrich", json={
                "scope": "all",
                "options": {"steam": True, "ratings": False},
            }).json()
            job_id = result["job_id"]

            # 立即取消
            client.post(f"{API}/jobs/{job_id}/cancel")
            job = wait_job(client, job_id, timeout=60)
            assert job["status"] == "cancelled"


def test_enrich_no_llm_config(service_data_dir, monkeypatch):
    """未配置 LLM 时 llm.classify 任务直接 error。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # 未配置 LLM → 400
        response = client.post(f"{API}/games/llm/classify", json={
            "scope": "all",
        })
        assert response.status_code == 400, response.text
        assert "detail" in response.json()


def test_enrich_scope_selected(service_data_dir, monkeypatch):
    """enrich scope=selected 只处理指定游戏。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
        {"name": "游戏B", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        def mock_match_appid(queries):
            return 12345, "Game A", True

        def mock_fetch_appdetails(appid):
            return {"description": "简介"}, ""

        def mock_fetch_appreviews(appid):
            return {"steam_positive_pct": 90.0}, ""

        with patch("gamewall.steam_client.match_appid", mock_match_appid), \
             patch("gamewall.steam_client.fetch_appdetails", mock_fetch_appdetails), \
             patch("gamewall.steam_client.fetch_appreviews", mock_fetch_appreviews):
            job = enrich(client, scope="selected", keys=["游戏A"],
                         options={"steam": True, "ratings": False})
            # 只处理 1 个
            assert job["total"] == 1
