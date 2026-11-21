"""契约 2.2/2.5/2.6：批量刮削、榜单、新片与图片代理。"""
import io
import types

from tests.webapp.test_movie_helpers import (
    build_library,
    find_movie,
    movie_client,
    prepare_library,
    wait_job,
)

API = "/api/movie"


def test_system_info(service_data_dir):
    with movie_client(service_data_dir) as client:
        body = client.get(f"{API}/system/info").json()
        assert body["service"] == "movie"
        assert isinstance(body["node"], bool)
        assert isinstance(body["npx"], bool)
        assert body["data_dir"] == str(service_data_dir)


# ─────────────────── 豆瓣刮削 ───────────────────


def test_scrape_batch_result_shape(service_data_dir, monkeypatch):
    """succeeded / failed / skipped 三类结果（网络由假实现替代）。"""
    import scraper.douban_cli as douban_cli

    library = build_library(service_data_dir / "library")
    calls = []

    def fake_scrape(nfo_path, title, original_title, year):
        calls.append(title)
        if title == "疯狂动物城":
            return {"success": False, "message": "未匹配到豆瓣"}
        return {"success": True, "message": "评分已更新"}

    monkeypatch.setattr(douban_cli, "scrape_single_movie", fake_scrape)
    import movie_service.tasks as tasks

    monkeypatch.setattr(tasks, "shutil", types.SimpleNamespace(which=lambda name: "/usr/bin/npx"))

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")
        zoo = find_movie(client, "疯狂动物城")

        response = client.post(
            f"{API}/scrape",
            json={"ids": [saw["id"], zoo["id"], "0000000000000000"]},
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["kind"] == "scrape.batch"

        result = job["result"]
        assert result["succeeded"] == [saw["id"]]
        assert result["failed"] == [{"id": zoo["id"], "message": "未匹配到豆瓣"}]
        assert result["skipped"] == ["0000000000000000"]
        assert calls == ["电锯惊魂", "疯狂动物城"]
        assert job["current"] == 3 and job["total"] == 3


def test_scrape_without_npx_reports_error(service_data_dir, monkeypatch):
    """服务端缺少 Node.js 时任务落 error（中文提示）。"""
    import movie_service.tasks as tasks

    monkeypatch.setattr(tasks, "shutil", types.SimpleNamespace(which=lambda name: None))

    library = build_library(service_data_dir / "library")
    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")
        response = client.post(f"{API}/scrape", json={"ids": [saw["id"]]})
        assert response.status_code == 200
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "error"
        assert "Node.js" in job["error"]


# ─────────────────── 榜单 ───────────────────


def test_rankings_without_cache(service_data_dir):
    with movie_client(service_data_dir) as client:
        body = client.get(f"{API}/rankings/top250").json()
        assert body == {
            "kind": "top250",
            "fetched_at": 0.0,
            "items": [],
            "owned_count": 0,
            "missing_count": 0,
        }
        assert client.get(f"{API}/rankings/chart").json()["fetched_at"] == 0.0
        assert client.get(f"{API}/rankings/bogus").status_code == 400


def test_rankings_cache_compare(service_data_dir):
    from scraper.douban_ranking import RankedMovie, save_ranking_cache

    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        cache_path = service_data_dir / "douban_ranking_cache.json"
        top250 = [
            RankedMovie(
                title="电锯惊魂", year="2004", rating=8.5, douban_id="1418",
                rank=1, source="top250",
                poster_url="https://img2.doubanio.com/x.jpg",
            ),
            RankedMovie(
                title="肖申克的救赎", year="1994", rating=9.7, douban_id="1292052",
                rank=2, source="top250",
                poster_url="https://img1.doubanio.com/y.jpg",
            ),
        ]
        imdb = [
            RankedMovie(
                title="Saw", year="2004", rating=8.4, douban_id="",
                rank=1, source="imdb_top250", poster_url="https://m.media-amazon.com/z.jpg",
            ),
            RankedMovie(
                title="The Shawshank Redemption", year="1994", rating=9.3, douban_id="",
                rank=2, source="imdb_top250", poster_url="https://m.media-amazon.com/w.jpg",
            ),
        ]
        assert save_ranking_cache(top250, [], imdb, cache_path=cache_path)

        body = client.get(f"{API}/rankings/top250").json()
        assert body["kind"] == "top250"
        assert body["fetched_at"] > 0
        assert body["owned_count"] == 1 and body["missing_count"] == 1

        owned = body["items"][0]
        assert owned["rank"] == 1
        assert owned["title"] == "电锯惊魂"
        assert owned["original_title"] == "Saw"  # 匹配到的本地片原名
        assert owned["owned"] is True and owned["in_library"] is True
        assert owned["movie_id"] == saw["id"]

        missing = body["items"][1]
        assert missing["rank"] == 2
        assert missing["owned"] is False
        assert missing["in_library"] is False
        assert missing["movie_id"] is None

        # IMDB 榜单：original_title 为榜单原文，title 取本地中文名
        body = client.get(f"{API}/rankings/imdb_top250").json()
        assert body["owned_count"] == 1 and body["missing_count"] == 1
        assert body["items"][0]["title"] == "电锯惊魂"
        assert body["items"][0]["original_title"] == "Saw"
        assert body["items"][1]["title"] == "The Shawshank Redemption"
        assert body["items"][1]["original_title"] == "The Shawshank Redemption"

        # 榜单缓存同时驱动 DTO 的 rank 角标
        assert find_movie(client, "电锯惊魂")["rank"] == {
            "douban_top250": 1,
            "imdb_top250": 1,
        }


def test_rankings_fetch_from_cache_and_invalid_source(service_data_dir):
    from scraper.douban_ranking import RankedMovie, save_ranking_cache

    library = build_library(service_data_dir / "library")
    cache_path = service_data_dir / "douban_ranking_cache.json"
    save_ranking_cache(
        [
            RankedMovie(
                title="电锯惊魂", year="2004", rating=8.5, douban_id="1418",
                rank=1, source="top250",
            )
        ],
        [],
        None,
        cache_path=cache_path,
    )

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])

        # 未知来源 → 400
        assert (
            client.post(f"{API}/rankings/fetch", json={"sources": ["bogus"]}).status_code
            == 400
        )

        response = client.post(
            f"{API}/rankings/fetch",
            json={"sources": ["top250", "imdb_top250"], "use_cache": True},
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["kind"] == "rankings.fetch"
        result = job["result"]
        assert result["from_cache"] is True
        assert result["sources"] == ["top250", "imdb_top250"]
        assert result["owned"] == 1
        assert result["missing"] == 0


def test_rankings_fetch_from_network(service_data_dir, monkeypatch):
    """use_cache=False 走抓取分支（网络全部打桩），完成后缓存可读。"""
    import scraper.douban_ranking as dr
    from movie_service import browse_cache

    monkeypatch.setattr(browse_cache, 'warm_browse', lambda *_: {'posters': 0, 'plots': 0, 'poster_total': 0, 'plot_total': 0})
    monkeypatch.setattr(
        browse_cache, 'enrich_top250',
        lambda *_, **__: {'ratings': 0, 'plots': 0, 'posters': 0},
    )

    library = build_library(service_data_dir / "library")

    def top250(cached_movies=None):
        return [
            dr.RankedMovie(
                title="电锯惊魂", year="2004", rating=8.5, douban_id="1418",
                rank=1, source="top250",
            )
        ]

    def chart(cached_movies=None, *, fetch_details=True):
        assert fetch_details is True
        return [
            dr.RankedMovie(
                title="疯狂动物城", year="2016", rating=9.2, douban_id="25669958",
                rank=1, source="chart",
            )
        ]

    monkeypatch.setattr(dr, "fetch_douban_top250", top250)
    monkeypatch.setattr(dr, "fetch_douban_chart", chart)
    monkeypatch.setattr(dr, "fetch_imdb_top250", lambda cached_movies=None: [])

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        response = client.post(
            f"{API}/rankings/fetch",
            json={"sources": ["top250", "chart"], "use_cache": False},
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["result"]["from_cache"] is False
        assert job["result"]["total"] == 2
        assert job["result"]["owned"] == 2
        assert job["result"]["stale_sources"] == []

        body = client.get(f"{API}/rankings/chart").json()
        assert body["fetched_at"] > 0
        assert body["items"][0]["title"] == "疯狂动物城"
        assert body["items"][0]["owned"] is True


def test_top250_refresh_keeps_previous_full_ranking(service_data_dir, monkeypatch):
    """豆瓣来源返回不完整时保留原 Top250，并避免推进缓存更新时间。"""
    import json
    import scraper.douban_ranking as dr
    from movie_service import browse_cache
    from utils.library_sync import atomic_json

    monkeypatch.setattr(browse_cache, 'warm_browse', lambda *_: {'posters': 0, 'plots': 0, 'poster_total': 0, 'plot_total': 0})
    monkeypatch.setattr(
        browse_cache, 'enrich_top250',
        lambda *_, **__: {'ratings': 0, 'plots': 0, 'posters': 0},
    )
    cache_path = service_data_dir / "douban_ranking_cache.json"
    previous = [
        dr.RankedMovie(title=f"旧电影{rank}", year="2000", rating=8.0, douban_id=str(1000 + rank),
                       rank=rank, source="top250", poster_url=f"https://img3.doubanio.com/{rank}.jpg",
                       plot=f"旧简介{rank}")
        for rank in range(1, 251)
    ]
    dr.save_ranking_cache(previous, [], cache_path=cache_path)
    original_timestamp = json.loads(cache_path.read_text(encoding="utf-8"))["source_timestamps"]["top250"]

    def partial(cached_movies=None, *, fetch_page=None):
        assert fetch_page is None
        return [dr.RankedMovie(title="只拿到一部", year="2026", rating=0.0, douban_id="1",
                               rank=1, source="top250")]

    monkeypatch.setattr(dr, "fetch_douban_top250", partial)
    monkeypatch.setattr(dr, "fetch_douban_chart", lambda cached_movies=None, *, fetch_details=True: [])
    monkeypatch.setattr(dr, "fetch_imdb_top250", lambda cached_movies=None: [])

    with movie_client(service_data_dir) as client:
        response = client.post(
            f"{API}/rankings/fetch", json={"sources": ["top250"], "use_cache": False}
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["result"]["stale_sources"] == ["top250"]
        assert job["result"]["total"] == 250

        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        assert cache["source_timestamps"]["top250"] == original_timestamp
        assert [item["title"] for item in cache["top250"]] == [movie.title for movie in previous]


# ─────────────────── 新片 ───────────────────


def test_newmovies_cache_compare(service_data_dir):
    from scraper.new_movie_checker import NewMovie, save_new_movie_cache

    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        zoo = find_movie(client, "疯狂动物城")

        cache_path = service_data_dir / "new_movie_cache.json"
        nowplaying = [
            NewMovie(
                title="疯狂动物城", year="2016", rating=9.2, douban_id="25669958",
                status="nowplaying", genres=["喜剧", "动作"],
                poster_url="https://img2.doubanio.com/p.jpg",
                premiered="2016-03-04",
            ),
            NewMovie(
                title="阿凡达3", year="2027", rating=0.0, douban_id="3011111",
                status="nowplaying", genres=["科幻"],
            ),
        ]
        coming = [
            NewMovie(
                title="阿凡达4", year="2029", rating=0.0, douban_id="3011112",
                status="coming", genres=["科幻"],
            )
        ]
        assert save_new_movie_cache(nowplaying, coming, cache_path=cache_path)

        body = client.get(f"{API}/newmovies/nowplaying").json()
        assert body["kind"] == "nowplaying"
        assert body["fetched_at"] > 0
        assert body["owned_count"] == 1 and body["missing_count"] == 1

        owned = body["items"][0]
        assert owned["in_library"] is True
        assert owned["movie_id"] == zoo["id"]
        assert owned["genre"] == "喜剧 / 动作"
        assert owned["release_date"] == "2016-03-04"
        assert owned["rating"] == 9.2
        assert owned["douban_url"] == "https://movie.douban.com/subject/25669958/"
        assert owned["poster_url"] == "https://img2.doubanio.com/p.jpg"

        missing = body["items"][1]
        assert missing["in_library"] is False and missing["movie_id"] is None

        body = client.get(f"{API}/newmovies/coming").json()
        assert body["items"][0]["title"] == "阿凡达4"
        assert body["owned_count"] == 0

        assert client.get(f"{API}/newmovies/bogus").status_code == 400
        assert (
            client.post(f"{API}/newmovies/fetch", json={"sources": ["bogus"]}).status_code
            == 400
        )

        response = client.post(
            f"{API}/newmovies/fetch", json={"sources": ["nowplaying"], "use_cache": True}
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["kind"] == "newmovies.fetch"
        assert job["result"]["from_cache"] is True
        assert job["result"]["owned"] == 1


def test_newmovies_fetch_from_network(service_data_dir, monkeypatch):
    from movie_service import browse_cache

    monkeypatch.setattr(browse_cache, 'warm_browse', lambda *_: None)
    import scraper.new_movie_checker as nc

    library = build_library(service_data_dir / "library")

    monkeypatch.setattr(
        nc,
        "fetch_nowplaying",
        lambda cached_movies=None: [
            nc.NewMovie(
                title="电锯惊魂", year="2004", rating=8.5, douban_id="1418",
                status="nowplaying", genres=["恐怖"],
            )
        ],
    )
    monkeypatch.setattr(nc, "fetch_coming_soon", lambda cached_movies=None: [])

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        response = client.post(
            f"{API}/newmovies/fetch",
            json={"sources": ["nowplaying", "coming"], "use_cache": False},
        )
        assert response.status_code == 200, response.text
        job = wait_job(client, response.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["result"]["from_cache"] is False
        assert job["result"]["owned"] == 1

        body = client.get(f"{API}/newmovies/nowplaying").json()
        assert body["fetched_at"] > 0
        assert body["items"][0]["in_library"] is True


# ─────────────────── 图片代理 ───────────────────


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 6), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_proxy_image_whitelist_and_cache(service_data_dir, monkeypatch):
    import wall_common.images as images

    payload = _png_bytes()
    monkeypatch.setattr(images, "fetch_remote", lambda url, **kwargs: payload)

    with movie_client(service_data_dir) as client:
        # host 白名单 / 协议校验
        assert (
            client.get(f"{API}/proxy/image", params={"url": "ftp://img2.doubanio.com/a.jpg"})
            .status_code
            == 400
        )
        assert (
            client.get(f"{API}/proxy/image", params={"url": "https://evil.example.com/a.jpg"})
            .status_code
            == 400
        )
        assert (
            client.get(f"{API}/proxy/image", params={"url": "https://notdouban.com/a.jpg"})
            .status_code
            == 400
        )

        response = client.get(
            f"{API}/proxy/image", params={"url": "https://img2.doubanio.com/poster.png"}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("image/png")
        assert response.content == payload

        # 白名单子域名同样放行
        sub = client.get(f"{API}/proxy/image", params={"url": "https://movie.douban.com/a.jpg"})
        assert sub.status_code == 200

        # 命中缓存后不再联网
        def boom(url, **kwargs):
            raise AssertionError("命中缓存后不应再次联网")

        monkeypatch.setattr(images, "fetch_remote", boom)
        for url in (
            "https://img2.doubanio.com/poster.png",
            "https://movie.douban.com/a.jpg",
        ):
            cached = client.get(f"{API}/proxy/image", params={"url": url})
            assert cached.status_code == 200
            assert cached.content == payload
