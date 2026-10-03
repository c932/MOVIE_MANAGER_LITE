"""契约 2.2：观看 / 收藏 / 用户评分 / 删除 / 重新解析 的写入与持久化。"""
import json

from tests.webapp.test_movie_helpers import (
    build_library,
    find_movie,
    movie_client,
    movies_of,
    prepare_library,
)


def test_watched_and_favorite_roundtrip(service_data_dir):
    """watched/favorite 写 WatchHistory/FavoriteManager 并落盘，重启后仍生效。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        response = client.post(
            f"/api/movie/movies/{saw['id']}/watched", json={"watched": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["watched"] is True

        response = client.post(
            f"/api/movie/movies/{saw['id']}/favorite", json={"favorite": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["favorite"] is True

        # 磁盘上的记录文件确实被写入
        history = json.loads((service_data_dir / "watch_history.json").read_text("utf-8"))
        assert history["total"] == 1
        favorites = json.loads((service_data_dir / "favorites.json").read_text("utf-8"))
        assert len(favorites["favorites"]) == 1

        # 列表接口同样反映状态
        assert find_movie(client, "电锯惊魂")["watched"] is True
        assert find_movie(client, "电锯惊魂")["favorite"] is True
        assert find_movie(client, "疯狂动物城")["watched"] is False

        # 取消标记
        client.post(f"/api/movie/movies/{saw['id']}/watched", json={"watched": False})
        assert find_movie(client, "电锯惊魂")["watched"] is False

    # 换一个 app 实例（同一数据目录）验证持久化
    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")
        assert saw["watched"] is False
        assert saw["favorite"] is True


def test_user_rating_writes_nfo(service_data_dir):
    """PUT /rating 写 NFO 的 rating name=user，且不破坏原有评分。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        response = client.put(
            f"/api/movie/movies/{saw['id']}/rating", json={"rating": 9.5}
        )
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["user_rating"] == 9.5
        assert detail["rating"] == 8.5  # 主评分不受用户评分影响

        nfo_text = library["saw"].read_text(encoding="utf-8")
        assert 'name="user"' in nfo_text
        assert "<value>9.5</value>" in nfo_text

        # 越界评分 → 400
        bad = client.put(f"/api/movie/movies/{saw['id']}/rating", json={"rating": 11})
        assert bad.status_code == 400
        assert "detail" in bad.json()
        negative = client.put(f"/api/movie/movies/{saw['id']}/rating", json={"rating": -1})
        assert negative.status_code == 400

        # 只有 user 评分的 NFO 也能读出 user_rating（include_user_rating）
        only_user = find_movie(client, "疯狂动物城")
        client.put(f"/api/movie/movies/{only_user['id']}/rating", json={"rating": 7})
        assert find_movie(client, "疯狂动物城")["user_rating"] == 7

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        assert find_movie(client, "电锯惊魂")["user_rating"] == 9.5


def test_delete_only_removes_local_records(service_data_dir):
    """DELETE 仅删本地记录，媒体文件保持原样。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")
        client.post(f"/api/movie/movies/{saw['id']}/watched", json={"watched": True})
        client.post(f"/api/movie/movies/{saw['id']}/favorite", json={"favorite": True})

        response = client.delete(f"/api/movie/movies/{saw['id']}")
        assert response.status_code == 200
        assert response.json() == {"removed": True}

        assert client.get(f"/api/movie/movies/{saw['id']}").status_code == 404
        assert len(movies_of(client)) == 1

        # 媒体文件与 NFO 未被删除
        assert library["saw"].is_file()

        history = json.loads((service_data_dir / "watch_history.json").read_text("utf-8"))
        assert history["total"] == 0
        favorites = json.loads((service_data_dir / "favorites.json").read_text("utf-8"))
        assert favorites["favorites"] == []

        # 缓存也已更新
        cache = json.loads((service_data_dir / "movie_cache.json").read_text("utf-8"))
        assert cache["movie_count"] == 1


def test_reparse_picks_up_external_nfo_change(service_data_dir):
    """POST /reparse 重新解析磁盘上的 NFO 并刷新缓存。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        xml = library["saw"].read_text(encoding="utf-8")
        library["saw"].write_text(
            xml.replace("<title>电锯惊魂</title>", "<title>电锯惊魂·重制</title>"),
            encoding="utf-8",
        )
        # 未 reparse 前列表仍是旧数据
        assert find_movie(client, "电锯惊魂")["title"] == "电锯惊魂"

        response = client.post(f"/api/movie/movies/{saw['id']}/reparse")
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "电锯惊魂·重制"
        assert find_movie(client, "电锯惊魂·重制")["title"] == "电锯惊魂·重制"
