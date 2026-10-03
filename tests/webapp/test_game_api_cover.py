"""契约 3.2：封面端点（404/200）。"""
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tests.webapp.test_game_helpers import (
    API,
    build_excel,
    excel_apply,
    find_game,
    game_client,
    set_game_settings,
    set_steam_appid,
)


def _make_jpeg(path: Path, size=(12, 18)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 80, 120)).save(path, format="JPEG")
    return path


def test_cover_custom(service_data_dir):
    """custom 封面端点返回 image/jpeg。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        # 无自定义封面 → 404
        response = client.get(f"{API}/games/{game['key']}/cover?variant=custom")
        assert response.status_code == 404, response.text

        # 放置自定义封面
        from game_service.store import custom_cover_path
        cover = custom_cover_path(data_dir, game["key"])
        _make_jpeg(cover)

        response = client.get(
            f"{API}/games/{game['key']}/cover?variant=custom&w=100&h=150"
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/jpeg"
        assert "Cache-Control" in response.headers
        assert len(response.content) > 0


def test_cover_grid(service_data_dir, monkeypatch):
    """grid 封面端点：Steam 竖版代理缓存。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        # 先通过 apply_fields 写入 steam_appid（Excel 不含此字段）
        set_steam_appid(client, game["key"], 12345)

        # 先用 monkeypatch 让 fetch_remote 失败，验证 404
        monkeypatch.setattr(
            "wall_common.images.fetch_remote",
            lambda url, timeout=12.0, max_bytes=30*1024*1024: (_ for _ in ()).throw(Exception("no network"))
        )
        response = client.get(f"{API}/games/{game['key']}/cover?variant=grid")
        assert response.status_code == 404, response.text

        # 再 mock 远程图片
        monkeypatch.undo()
        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (10, 15), (10, 20, 30)).save(buf, format="JPEG")
        remote_bytes = buf.getvalue()

        def mock_fetch_remote(url, timeout=12.0, max_bytes=30 * 1024 * 1024):
            return remote_bytes

        monkeypatch.setattr("wall_common.images.fetch_remote", mock_fetch_remote)
        response = client.get(
            f"{API}/games/{game['key']}/cover?variant=grid&w=100&h=150"
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/jpeg"
        assert len(response.content) > 0


def test_cover_invalid_variant(service_data_dir):
    """非法 variant 返回 400。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        response = client.get(f"{API}/games/{game['key']}/cover?variant=bad")
        assert response.status_code == 400, response.text


def test_cover_refresh(service_data_dir, monkeypatch):
    """cover/refresh 强制重新拉取。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        # 先通过 apply_fields 写入 steam_appid（Excel 不含此字段）
        set_steam_appid(client, game["key"], 12345)

        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (10, 15), (10, 20, 30)).save(buf, format="JPEG")
        remote_bytes = buf.getvalue()

        def mock_fetch_remote(url, timeout=12.0, max_bytes=30 * 1024 * 1024):
            return remote_bytes

        with patch("wall_common.images.fetch_remote", mock_fetch_remote):
            response = client.post(f"{API}/games/{game['key']}/cover/refresh")
            assert response.status_code == 200, response.text
            assert "path" in response.json()
            assert Path(response.json()["path"]).exists()


def test_cover_404_when_no_urls(service_data_dir):
    """无封面 URL 时 refresh 404。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "游戏A")

        response = client.post(f"{API}/games/{game['key']}/cover/refresh")
        assert response.status_code in (404, 400), response.text
