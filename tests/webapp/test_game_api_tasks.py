"""契约 3.2：任务提交校验、本地扫描、封面尺寸/ETag、搜索与自检等边界。"""
from pathlib import Path

from tests.webapp.test_game_helpers import (
    API,
    build_excel,
    excel_apply,
    find_game,
    game_client,
    scan_installed,
    set_game_settings,
)


def test_system_info(service_data_dir):
    """GET /system/info 返回 service 与 data_dir。"""
    with game_client(service_data_dir) as client:
        data = client.get(f"{API}/system/info").json()
        assert data["service"] == "game"
        assert data["data_dir"] == str(service_data_dir)


def test_steam_search_empty_query(service_data_dir):
    """缺少搜索词返回 400（不发起任何网络请求）。"""
    with game_client(service_data_dir) as client:
        assert client.get(f"{API}/games/steam/search?q=").status_code == 400
        assert client.get(f"{API}/games/steam/search").status_code == 400


def test_excel_missing_file(service_data_dir):
    """配置的 Excel 文件不存在时 diff/apply 返回 400。"""
    with game_client(service_data_dir) as client:
        set_game_settings(client, {
            "excel_path": str(service_data_dir / "missing.xlsx"),
        })
        response = client.post(f"{API}/games/excel/diff")
        assert response.status_code == 400, response.text
        response = client.post(f"{API}/games/excel/apply")
        assert response.status_code == 400, response.text


def test_enrich_submit_validation(service_data_dir):
    """enrich 提交期校验：scope、selected keys、options、network_enabled。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # 非法 scope
        response = client.post(f"{API}/games/enrich", json={"scope": "bogus"})
        assert response.status_code == 400, response.text

        # selected 指向不存在的 key
        response = client.post(
            f"{API}/games/enrich", json={"scope": "selected", "keys": ["不存在"]})
        assert response.status_code == 400, response.text

        # 两项都关闭
        response = client.post(f"{API}/games/enrich", json={
            "scope": "all", "options": {"steam": False, "ratings": False},
        })
        assert response.status_code == 400, response.text

        # 关闭联网后不允许提交
        set_game_settings(client, {"network_enabled": False})
        response = client.post(f"{API}/games/enrich", json={"scope": "all"})
        assert response.status_code == 400, response.text


def test_llm_classify_scope_validation(service_data_dir):
    """llm/classify 的 scope/keys 在提交期校验（早于 LLM 配置检查）。"""
    with game_client(service_data_dir) as client:
        response = client.post(f"{API}/games/llm/classify", json={"scope": "bogus"})
        assert response.status_code == 400, response.text
        assert "detail" in response.json()

        response = client.post(
            f"{API}/games/llm/classify",
            json={"scope": "selected", "keys": ["不存在"]})
        assert response.status_code == 400, response.text


def test_scan_installed_requires_game_dirs(service_data_dir):
    """未配置 game_dirs 时 scan-installed 返回 400。"""
    with game_client(service_data_dir) as client:
        response = client.post(f"{API}/games/scan-installed")
        assert response.status_code == 400, response.text


def test_scan_installed_task(service_data_dir):
    """本地扫描任务：识别 game_dirs 下的 exe 并标记 installed。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "测试游戏", "size_text": "10 GB"},
    ])
    games_root = data_dir / "games_root"
    game_dir = games_root / "测试游戏"
    game_dir.mkdir(parents=True)
    (game_dir / "测试游戏.exe").write_bytes(b"MZfake")

    with game_client(data_dir) as client:
        set_game_settings(client, {
            "excel_path": str(excel_path),
            "game_dirs": [str(games_root)],
        })
        excel_apply(client)

        job = scan_installed(client)
        result = job["result"]
        assert result["scanned"] >= 1
        assert result["matched"] == 1
        assert find_game(client, "测试游戏")["installed"] is True


def test_cover_invalid_size(service_data_dir):
    """封面尺寸非法（非数字/越界）返回 400（先于封面解析校验）。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")
        base = f"{API}/games/{game['key']}/cover"

        assert client.get(f"{base}?w=abc&h=100").status_code == 400
        assert client.get(f"{base}?w=9999&h=100").status_code == 400
        assert client.get(f"{base}?w=100&h=-5").status_code == 400


def test_cover_etag_304(service_data_dir):
    """封面端点带 ETag/Cache-Control，命中 If-None-Match 返回 304。"""
    from PIL import Image

    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        from game_service.store import custom_cover_path

        cover = custom_cover_path(data_dir, game["key"])
        cover.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 18), (40, 80, 120)).save(cover, format="JPEG")

        url = f"{API}/games/{game['key']}/cover?variant=custom"
        first = client.get(url)
        assert first.status_code == 200, first.text
        etag = first.headers["etag"]
        assert etag.startswith('"') and first.headers["cache-control"]

        second = client.get(url, headers={"If-None-Match": etag})
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["etag"] == etag


def test_cover_refresh_custom(service_data_dir):
    """cover/refresh variant=custom 返回本地路径，无自定义封面则 404。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")
        base = f"{API}/games/{game['key']}/cover/refresh"

        response = client.post(base, json={"variant": "custom"})
        assert response.status_code == 404, response.text

        from game_service.store import custom_cover_path

        cover = custom_cover_path(data_dir, game["key"])
        cover.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.new("RGB", (12, 18), (10, 20, 30)).save(cover, format="JPEG")

        response = client.post(base, json={"variant": "custom"})
        assert response.status_code == 200, response.text
        assert Path(response.json()["path"]) == cover
