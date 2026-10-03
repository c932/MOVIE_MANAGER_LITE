"""契约 3.2：Steam 搜索/应用、LLM 匹配。"""
from unittest.mock import patch

from tests.webapp.test_game_helpers import (
    API,
    build_excel,
    excel_apply,
    find_game,
    game_client,
    set_game_settings,
)


def test_steam_search(service_data_dir, monkeypatch):
    """Steam 搜索端点返回 results。"""
    with game_client(service_data_dir) as client:
        # mock steam_client.search_steam
        def mock_search_steam(term):
            return [{"appid": 123, "name": "Test Game"}], ""

        with patch("gamewall.steam_client.search_steam", mock_search_steam):
            response = client.get(f"{API}/games/steam/search?q=test")
            assert response.status_code == 200, response.text
            data = response.json()
            # 契约 3.2：results 每项含 definitive（名称与 q 归一化一致才为 True）
            assert data["results"] == [
                {"appid": 123, "name": "Test Game", "definitive": False}
            ]


def test_steam_search_error(service_data_dir, monkeypatch):
    """Steam 搜索失败返回 502。"""
    with game_client(service_data_dir) as client:
        def mock_search_steam(term):
            return [], "网络错误"

        with patch("gamewall.steam_client.search_steam", mock_search_steam):
            response = client.get(f"{API}/games/steam/search?q=test")
            assert response.status_code == 502, response.text
            assert "detail" in response.json()


def test_steam_apply(service_data_dir, monkeypatch):
    """Steam apply 拉取详情+评价合并写缓存。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        def mock_fetch_appdetails(appid):
            return {"steam_name": "Test Game", "description": "简介"}, ""

        def mock_fetch_appreviews(appid):
            return {"steam_positive_pct": 92.0, "steam_review_total": 5000}, ""

        with patch("gamewall.steam_client.fetch_appdetails", mock_fetch_appdetails), \
             patch("gamewall.steam_client.fetch_appreviews", mock_fetch_appreviews):
            response = client.post(f"{API}/games/steam/apply", json={
                "key": game["key"],
                "appid": 12345,
            })
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["steam_appid"] == 12345
            assert data["steam_name"] == "Test Game"
            assert data["description"] == "简介"
            assert data["steam_positive_pct"] == 92.0
            assert data["steam_review_total"] == 5000


def test_steam_apply_error(service_data_dir, monkeypatch):
    """Steam apply 详情拉取失败返回 502。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        def mock_fetch_appdetails(appid):
            return None, "网络超时"

        with patch("gamewall.steam_client.fetch_appdetails", mock_fetch_appdetails):
            response = client.post(f"{API}/games/steam/apply", json={
                "key": game["key"],
                "appid": 12345,
            })
            assert response.status_code == 502, response.text


def test_steam_apply_404_game(service_data_dir):
    """Steam apply 不存在的游戏返回 404。"""
    with game_client(service_data_dir) as client:
        response = client.post(f"{API}/games/steam/apply", json={
            "key": "不存在",
            "appid": 12345,
        })
        assert response.status_code == 404, response.text


def test_llm_match(service_data_dir, monkeypatch):
    """LLM 匹配成功返回 game + appid + verified。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        set_game_settings(client, {
            "llm_enabled": True,
            "llm_base_url": "https://api.example.com/v1",
            "llm_api_key": "sk-test1234567890",
        })
        excel_apply(client)
        game = find_game(client, "游戏A")

        def mock_llm_match_and_fetch(game_obj, base_url, api_key, model, timeout=30.0):
            return {"steam_appid": 12345, "steam_name": "Game A",
                    "description": "简介"}, ""

        with patch("gamewall.llm_search.llm_match_and_fetch",
                   mock_llm_match_and_fetch):
            response = client.post(f"{API}/games/llm/match", json={
                "key": game["key"],
            })
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["appid"] == 12345
            assert data["verified"] is True
            assert data["game"]["steam_appid"] == 12345
            assert data["game"]["description"] == "简介"


def test_llm_match_no_config(service_data_dir):
    """未配置 LLM 时 llm/match 返回 400。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        response = client.post(f"{API}/games/llm/match", json={
            "key": game["key"],
        })
        assert response.status_code == 400, response.text


def test_llm_match_error(service_data_dir, monkeypatch):
    """LLM 匹配失败返回 502。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        set_game_settings(client, {
            "llm_enabled": True,
            "llm_base_url": "https://api.example.com/v1",
            "llm_api_key": "sk-test1234567890",
        })
        excel_apply(client)
        game = find_game(client, "游戏A")

        def mock_llm_match_and_fetch(game_obj, base_url, api_key, model, timeout=30.0):
            return {}, "LLM 未给出有效建议"

        with patch("gamewall.llm_search.llm_match_and_fetch",
                   mock_llm_match_and_fetch):
            response = client.post(f"{API}/games/llm/match", json={
                "key": game["key"],
            })
            assert response.status_code == 502, response.text


def test_llm_poster(service_data_dir, monkeypatch):
    """LLM 重新获取竖版海报。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        set_game_settings(client, {
            "llm_enabled": True,
            "llm_base_url": "https://api.example.com/v1",
            "llm_api_key": "sk-test1234567890",
        })
        excel_apply(client)
        game = find_game(client, "游戏A")

        def mock_llm_match_and_fetch(game_obj, base_url, api_key, model, timeout=30.0):
            return {"steam_appid": 12345, "steam_name": "Game A",
                    "header_image": "https://example.com/img.jpg"}, ""

        with patch("gamewall.llm_search.llm_match_and_fetch",
                   mock_llm_match_and_fetch):
            response = client.post(f"{API}/games/llm/poster", json={
                "key": game["key"],
            })
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["steam_appid"] == 12345
            assert data["header_image"] == "https://example.com/img.jpg"
