"""SteamGridDB 竖版海报搜索与下载测试"""
import json
from unittest.mock import patch

from gamewall.steamgrid_search import (
    search_game, search_grids, search_grids_best, download_poster,
    get_custom_poster_path,
)


class _FakeResp:
    """模拟 urllib 响应（JSON 上下文管理器）。"""
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class _BytesResp:
    """模拟图片字节响应。"""
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def test_search_grids_returns_grids_sorted_by_score():
    with patch("gamewall.steamgrid_search.urllib.request.urlopen") as m:
        m.side_effect = [
            _FakeResp({"data": [{"id": 99, "name": "Game"}]}),
            _FakeResp({"data": [
                {"id": 1, "url": "https://x/1.jpg", "title": "a", "score": 10},
                {"id": 2, "url": "https://x/2.jpg", "title": "b", "score": 50},
            ]}),
        ]
        grids, err = search_grids("Game", "key")
    assert err == ""
    assert [g["score"] for g in grids] == [50, 10]
    assert grids[0]["url"] == "https://x/2.jpg"
    assert grids[0]["thumb"] == "https://x/2.jpg"


def test_search_game_no_match():
    with patch("gamewall.steamgrid_search.urllib.request.urlopen",
               return_value=_FakeResp({"data": []})):
        game_id, err = search_game("Nonexistent", "key")
    assert game_id == 0
    assert err == "未找到匹配游戏"


def test_search_grids_best_falls_through_names():
    with patch("gamewall.steamgrid_search.search_grids") as m:
        m.side_effect = [
            ([], "未找到匹配游戏"),                      # 第一个名字无结果
            ([{"id": 1, "url": "u", "score": 1}], ""),   # 第二个名字命中
        ]
        grids, err = search_grids_best(["中文名", "English Name"], "key")
    assert err == ""
    assert len(grids) == 1


def test_search_grids_best_returns_err_when_all_empty():
    with patch("gamewall.steamgrid_search.search_grids", return_value=([], "未找到匹配游戏")):
        grids, err = search_grids_best(["无", "None"], "key")
    assert grids == []
    assert err == "未找到匹配游戏"


def test_download_poster_writes_file(tmp_path):
    dest = tmp_path / "posters" / "x.jpg"
    payload = b"\xff\xd8\xfffakejpeg"
    with patch("gamewall.steamgrid_search.urllib.request.urlopen",
               return_value=_BytesResp(payload)):
        err = download_poster("https://x/1.jpg", str(dest), "key")
    assert err == ""
    assert dest.read_bytes() == payload


def test_download_poster_returns_err_on_failure(tmp_path):
    dest = tmp_path / "posters" / "x.jpg"

    def boom(*a, **k):
        raise Exception("network down")

    with patch("gamewall.steamgrid_search.urllib.request.urlopen", side_effect=boom):
        err = download_poster("https://x/1.jpg", str(dest), "key")
    assert "network down" in err


def test_get_custom_poster_path_naming():
    p = get_custom_poster_path("some_game")
    assert p.replace("\\", "/").endswith("posters/some_game_custom.jpg")
