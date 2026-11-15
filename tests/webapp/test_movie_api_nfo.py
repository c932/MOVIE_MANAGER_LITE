"""契约 2.2/2.3：NFO 原文读写与结构化字段编辑。"""
import xml.etree.ElementTree as ET

from tests.webapp.test_movie_helpers import (
    build_library,
    find_movie,
    movie_client,
    prepare_library,
)


def test_get_and_put_raw_nfo(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        response = client.get(f"/api/movie/movies/{saw['id']}/nfo")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["path"] == str(library["saw"])
        assert "<title>电锯惊魂</title>" in body["xml"]

        # 整体覆盖：合法 <movie> XML
        new_xml = body["xml"].replace("<title>电锯惊魂</title>", "<title>电锯惊魂2</title>")
        response = client.put(
            f"/api/movie/movies/{saw['id']}/nfo", json={"xml": new_xml}
        )
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "电锯惊魂2"
        assert "<title>电锯惊魂2</title>" in library["saw"].read_text(encoding="utf-8")

        # 非法 XML / 根元素不是 <movie> → 400，且原文件保持不变
        before = library["saw"].read_text(encoding="utf-8")
        for bad in ("<movie><unclosed</movie>", "<tvshow><title>x</title></tvshow>", ""):
            response = client.put(f"/api/movie/movies/{saw['id']}/nfo", json={"xml": bad})
            assert response.status_code == 400, response.text
            assert "detail" in response.json()
        assert library["saw"].read_text(encoding="utf-8") == before


def test_structured_field_edit(service_data_dir):
    """PUT /fields 只写提交的键（契约 2.3）。"""
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")

        response = client.put(
            f"/api/movie/movies/{saw['id']}/fields",
            json={
                "title": "电锯惊魂（重制版）",
                "year": "2004",
                "genres": ["恐怖", "犯罪"],
                "tags": ["经典"],
                "ratings": {"douban": 7.0},
                "directors": ["詹姆斯·温", "达伦·林恩·鲍斯曼"],
                "actors": [{"name": "雷·沃纳尔", "role": "Adam", "thumb": ""}],
                "uniqueids": {"imdb": "tt0387564", "douban": "1418"},
                "fileinfo": {"resolution": "720p", "video_codec": "h265", "audio_codec": "dts"},
            },
        )
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["title"] == "电锯惊魂（重制版）"
        assert detail["genres"] == ["恐怖", "犯罪"]
        assert detail["tags"] == ["经典"]
        assert detail["ratings"]["douban"] == 7.0
        assert detail["directors"] == ["詹姆斯·温", "达伦·林恩·鲍斯曼"]
        assert len(detail["actors"]) == 1
        assert detail["resolution"] == "720p"
        assert detail["video_codec"] == "h265"
        assert detail["tmdb_id"] == ""  # 未提交的键不受影响

        root = ET.fromstring(library["saw"].read_text(encoding="utf-8"))
        assert root.findtext("title") == "电锯惊魂（重制版）"
        assert [e.text for e in root.findall("genre")] == ["恐怖", "犯罪"]
        assert [e.text for e in root.findall("custom")] == ["经典"]
        video = root.find("fileinfo/streamdetails/video")
        assert video.findtext("width") == "1280" and video.findtext("height") == "720"
        # 演员被整体替换
        assert [e.findtext("name") for e in root.findall("actor")] == ["雷·沃纳尔"]

        # 只提交部分键：其它字段保持原样
        response = client.put(
            f"/api/movie/movies/{saw['id']}/fields", json={"tagline": "游戏开始了"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "电锯惊魂（重制版）"
        assert response.json()["tagline"] == "游戏开始了"

        # 空数组 = 清空
        response = client.put(f"/api/movie/movies/{saw['id']}/fields", json={"tags": []})
        assert response.status_code == 200, response.text
        assert response.json()["tags"] == []

        # user 评分也能通过 fields 写入并被读出
        response = client.put(
            f"/api/movie/movies/{saw['id']}/fields", json={"ratings": {"user": 8.0}}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_rating"] == 8.0
        assert response.json()["ratings"]["douban"] == 7.0  # 未提交的来源保持不变


def test_field_edit_validation(service_data_dir):
    library = build_library(service_data_dir / "library")

    with movie_client(service_data_dir) as client:
        prepare_library(client, library["root"])
        saw = find_movie(client, "电锯惊魂")
        before = library["saw"].read_text(encoding="utf-8")

        cases = [
            {"unknown_field": "x"},                       # 不支持的字段
            {"fileinfo": {"bluray": "yes"}},              # 不支持的 fileinfo 子键
            {"fileinfo": {"resolution": "16k"}},          # 未知分辨率
            {"genres": "恐怖"},                            # 类型错误
            {},                                           # 空请求
        ]
        for payload in cases:
            response = client.put(f"/api/movie/movies/{saw['id']}/fields", json=payload)
            assert response.status_code == 400, f"{payload} -> {response.text}"
            assert "detail" in response.json()

        # 校验失败时 NFO 文件保持原样
        assert library["saw"].read_text(encoding="utf-8") == before
