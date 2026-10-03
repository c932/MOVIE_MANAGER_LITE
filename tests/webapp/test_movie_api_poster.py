"""契约 2.2：海报缩略图端点与失效缓存。"""
from tests.webapp.test_movie_helpers import (
    add_movie,
    build_library,
    find_movie,
    movie_client,
    prepare_library,
)

API = "/api/movie"


def test_poster_render_and_cache(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        response = client.get(
            f"{API}/movies/{saw['id']}/poster", params={"w": 40, "h": 60}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.content[:2] == b"\xff\xd8"  # 真实 JPEG

        # 服务端缩略图缓存已生成
        cache_files = list((service_data_dir / "web_cache" / "images").glob("*.jpg"))
        assert cache_files

        # 失效缓存 → 返回删除数量
        response = client.post(f"{API}/movies/{saw['id']}/poster/invalidate")
        assert response.status_code == 200
        assert response.json()["removed"] >= 1
        assert not list((service_data_dir / "web_cache" / "images").glob("*.jpg"))

        # contain 模式
        response = client.get(
            f"{API}/movies/{saw['id']}/poster",
            params={"w": 40, "h": 60, "mode": "contain"},
        )
        assert response.status_code == 200


def test_poster_invalid_params_and_missing_source(service_data_dir):
    library = build_library(service_data_dir / "library")
    # 一部没有海报的电影
    add_movie(library["root"] / "NoPoster", "NoPoster", title="无海报电影", poster=False)

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        no_poster = find_movie(client, "无海报电影")
        assert no_poster["has_poster"] is False
        assert (
            client.get(f"{API}/movies/{no_poster['id']}/poster").status_code == 404
        )

        saw = find_movie(client, "电锯惊魂")

        # 尺寸/模式非法 → 400
        for params in (
            {"w": 0, "h": 60},
            {"w": 2000, "h": 60},
            {"w": 40, "h": -1},
            {"w": 40, "h": 60, "mode": "stretch"},
        ):
            response = client.get(f"{API}/movies/{saw['id']}/poster", params=params)
            assert response.status_code == 400, f"{params} -> {response.text}"
            assert "detail" in response.json()

        # 源图被删除 → 404
        poster = library["root"] / "Saw" / "poster.jpg"
        poster.unlink()
        response = client.get(f"{API}/movies/{saw['id']}/poster", params={"w": 40, "h": 60})
        assert response.status_code == 404
