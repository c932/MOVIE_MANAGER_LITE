"""契约 2.1/2.2：电影列表、详情与筛选/排序。"""
from tests.webapp.test_movie_helpers import (
    MOVIE_DTO_KEYS,
    build_library,
    find_movie,
    movie_client,
    movies_of,
    prepare_library,
    refresh,
)


def test_list_detail_shape_and_truncation(service_data_dir):
    """列表/详情字段齐全，plot(200)/actors(8) 截断，详情不截断。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        result = prepare_library(client, library["root"])
        assert result["added"] == 2
        assert result["removed"] == 0
        assert result["unchanged"] == 0
        assert result["total"] == 2
        assert isinstance(result["duration"], float)

        response = client.get("/api/movie/movies")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert len(body["movies"]) == 2
        assert body["cache_info"]["movie_count"] == 2
        assert body["cache_info"]["movie_paths"] == [str(library["root"])]

        saw = find_movie(client, "电锯惊魂")
        for key in MOVIE_DTO_KEYS:
            assert key in saw, f"缺少契约字段 {key}"

        # 列表截断：plot 200 字符、演员 8 人
        assert len(saw["plot"]) == 200
        assert len(saw["actors"]) == 8
        # 详情不截断
        detail = client.get(f"/api/movie/movies/{saw['id']}").json()
        assert len(detail["plot"]) > 200
        assert len(detail["actors"]) == 10
        assert detail["id"] == saw["id"]
        for key in MOVIE_DTO_KEYS:
            assert key in detail

        # 契约 2.1 的取值语义
        assert saw["original_title"] == "Saw"
        assert saw["year"] == "2004"
        assert saw["rating"] == 8.5
        assert saw["rating_source"] == "douban"
        assert saw["ratings"] == {"douban": 8.5, "imdb": 8.4}
        assert saw["user_rating"] == 0
        assert saw["watched"] is False
        assert saw["favorite"] is False
        assert saw["resolution"] == "1080p"
        assert saw["video_codec"] == "h264"
        assert saw["audio_codec"] == "dts"
        assert saw["imdb_id"] == "tt0387564"
        assert saw["has_poster"] is True
        assert saw["added_time"] > 0
        assert saw["rank"] is None  # 无榜单缓存

        # id = sha1(normalize_path(nfo_path))[:16]
        from movie_service.store import movie_id

        assert saw["id"] == movie_id(saw["nfo_path"])


def test_list_filters_sort_and_paging(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        zootopia = find_movie(client, "疯狂动物城")

        # 关键字（片名/原名/导演/演员）
        assert client.get("/api/movie/movies", params={"q": "疯狂"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"q": "Saw"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"q": "霍华德"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"q": "演员01"}).json()["total"] == 1

        # 分类 / 年份 / 分辨率 / 评分
        assert client.get("/api/movie/movies", params={"genre": "恐怖"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"country": "美国"}).json()["total"] == 2
        assert client.get("/api/movie/movies", params={"year": "2016"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"director": "詹姆斯"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"resolution": "1080"}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"min_rating": 9.0}).json()["total"] == 1

        # 观看 / 收藏状态过滤
        assert (
            client.post(
                f"/api/movie/movies/{zootopia['id']}/watched", json={"watched": True}
            ).status_code
            == 200
        )
        assert client.get("/api/movie/movies", params={"watched": True}).json()["total"] == 1
        assert client.get("/api/movie/movies", params={"watched": False}).json()["total"] == 1
        assert (
            client.post(
                f"/api/movie/movies/{zootopia['id']}/favorite", json={"favorite": True}
            ).status_code
            == 200
        )
        assert client.get("/api/movie/movies", params={"favorite": True}).json()["total"] == 1

        # 排序 + 分页（total 为筛选后的匹配数）
        ascending = client.get(
            "/api/movie/movies", params={"sort": "title", "order": "asc"}
        ).json()
        assert [m["title"] for m in ascending["movies"]] == ["电锯惊魂", "疯狂动物城"]
        descending = client.get(
            "/api/movie/movies", params={"sort": "year", "order": "desc"}
        ).json()
        assert [m["year"] for m in descending["movies"]] == ["2016", "2004"]

        paged = client.get("/api/movie/movies", params={"sort": "year", "limit": 1, "offset": 1}).json()
        assert paged["total"] == 2
        assert len(paged["movies"]) == 1
        assert paged["movies"][0]["year"] == "2004"

        # 非法排序字段
        assert (
            client.get("/api/movie/movies", params={"sort": "hacker"}).status_code == 400
        )


def test_movie_endpoints_404(service_data_dir):
    """不存在的 id 各端点一律 404 + {"detail": …}。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        missing = "deadbeefdeadbeef"

        responses = [
            client.get(f"/api/movie/movies/{missing}"),
            client.post(f"/api/movie/movies/{missing}/watched", json={"watched": True}),
            client.post(f"/api/movie/movies/{missing}/favorite", json={"favorite": True}),
            client.put(f"/api/movie/movies/{missing}/rating", json={"rating": 5}),
            client.post(f"/api/movie/movies/{missing}/reparse"),
            client.delete(f"/api/movie/movies/{missing}"),
            client.get(f"/api/movie/movies/{missing}/poster"),
            client.post(f"/api/movie/movies/{missing}/poster/invalidate"),
            client.get(f"/api/movie/movies/{missing}/nfo"),
            client.put(f"/api/movie/movies/{missing}/nfo", json={"xml": "<movie/>"}),
            client.put(f"/api/movie/movies/{missing}/fields", json={"title": "x"}),
        ]
        for response in responses:
            assert response.status_code == 404, response.text
            assert "detail" in response.json()


def test_multiple_apps_do_not_share_state(service_data_dir):
    """两个不同数据目录的 app 实例同时存在时互不干扰。"""
    import shutil

    from tests.webapp.test_movie_helpers import set_movie_paths

    library_a = build_library(service_data_dir / "library-a")
    library_b = build_library(service_data_dir / "library-b")
    shutil.rmtree(library_b["root"] / "Zootopia")  # B 库只留 1 部
    data_b = service_data_dir / "data-b"

    with movie_client(service_data_dir) as client_a, movie_client(data_b) as client_b:
        prepare_library(client_a, library_a["root"])
        set_movie_paths(client_b, [library_b["root"]])
        refresh(client_b, force=True)

        assert len(movies_of(client_a)) == 2
        assert len(movies_of(client_b)) == 1
        assert client_a.get("/api/movie/settings").json()["movie_paths"] == [
            str(library_a["root"])
        ]
        assert client_b.get("/api/movie/settings").json()["movie_paths"] == [
            str(library_b["root"])
        ]
        assert (data_b / "movie_cache.json").is_file()
        assert (service_data_dir / "movie_cache.json").is_file()


def test_refresh_is_incremental(service_data_dir):
    """增量刷新：unchanged 保留 added_time；新增/移除正确计数。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        before = {m["title"]: m["added_time"] for m in movies_of(client)}

        # 新增一部
        from tests.webapp.test_movie_helpers import add_movie

        add_movie(
            library["root"] / "Inception",
            "Inception",
            title="盗梦空间",
            original_title="Inception",
            year="2010",
        )
        second = refresh(client, force=False)["result"]
        assert second["added"] == 1
        assert second["removed"] == 0
        assert second["unchanged"] == 2
        assert second["total"] == 3

        after = {m["title"]: m["added_time"] for m in movies_of(client)}
        assert after["电锯惊魂"] == before["电锯惊魂"]  # 未变化电影保留加入时间
        assert after["盗梦空间"] > 0

        # 删除目录
        import shutil

        shutil.rmtree(library["root"] / "Zootopia")
        third = refresh(client, force=False)["result"]
        assert third["added"] == 0
        assert third["removed"] == 1
        assert third["unchanged"] == 2
        assert third["total"] == 2
        assert all(m["title"] != "疯狂动物城" for m in movies_of(client))
