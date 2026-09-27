"""llm_search 模块测试"""
import json
from unittest.mock import patch

from gamewall.llm_search import suggest_steam_match, llm_match_and_fetch


class _FakeGame:
    def __init__(self, title_cn="测试游戏", title_en="Test Game", developer="Test Studio"):
        self.title_cn = title_cn
        self.title_en = title_en
        self.raw_name = title_cn
        self.developer = developer
        self.steam_appid = 0


def _mock_urlopen_factory(payload: dict):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode("utf-8")
    return lambda req, timeout=30: FakeResp()


def test_suggest_steam_match_parses_valid_json():
    game = _FakeGame()
    with patch("urllib.request.urlopen", _mock_urlopen_factory({"english_title": "Test Game", "appid": 12345})):
        result = suggest_steam_match(game, "https://api.test/v1", "key", "model")
        assert result == {"english_title": "Test Game", "appid": 12345}


def test_suggest_steam_match_returns_none_on_empty():
    game = _FakeGame()
    with patch("urllib.request.urlopen", _mock_urlopen_factory({"english_title": "", "appid": 0})):
        result = suggest_steam_match(game, "https://api.test/v1", "key", "model")
        assert result is None


def test_suggest_steam_match_returns_none_on_invalid_json():
    game = _FakeGame()
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode("utf-8")
    with patch("urllib.request.urlopen", lambda req, timeout=30: FakeResp()):
        result = suggest_steam_match(game, "https://api.test/v1", "key", "model")
        assert result is None


def test_llm_match_and_fetch_verifies_appid_via_appdetails():
    game = _FakeGame()
    with patch("gamewall.llm_search.suggest_steam_match", return_value={"english_title": "Test Game", "appid": 12345}):
        with patch("gamewall.steam_client.fetch_appdetails", return_value=({"steam_name": "Test Game", "description": "desc"}, "")):
            with patch("gamewall.steam_client.fetch_appreviews", return_value=({"steam_positive_pct": 85.0}, "")):
                fields, err = llm_match_and_fetch(game, "https://api.test/v1", "key", "model")
                assert err == ""
                assert fields["steam_appid"] == 12345
                assert fields["steam_name"] == "Test Game"
                assert fields["steam_positive_pct"] == 85.0


def test_llm_match_and_fetch_falls_back_to_search_when_appid_invalid():
    game = _FakeGame()
    # 首次 appdetails 返回 ({}, "")（商店页不存在，无错误）；命中搜索后第二次返回真实详情
    with patch("gamewall.llm_search.suggest_steam_match", return_value={"english_title": "Test Game", "appid": 99999}):
        with patch("gamewall.steam_client.fetch_appdetails", side_effect=[({}, ""), ({"steam_name": "Test Game"}, "")]):
            with patch("gamewall.steam_client.match_appid", return_value=(12345, "Test Game", True)):
                with patch("gamewall.steam_client.fetch_appreviews", return_value=({}, "")):
                    fields, err = llm_match_and_fetch(game, "https://api.test/v1", "key", "model")
                    assert err == ""
                    assert fields["steam_appid"] == 12345


def test_llm_match_and_fetch_returns_err_when_no_match():
    game = _FakeGame()
    with patch("gamewall.llm_search.suggest_steam_match", return_value={"english_title": "Test Game", "appid": 0}):
        with patch("gamewall.steam_client.match_appid", return_value=(0, "", False)):
            fields, err = llm_match_and_fetch(game, "https://api.test/v1", "key", "model")
            assert fields == {}
            assert "无法验证" in err


def test_llm_match_and_fetch_returns_err_on_llm_failure():
    game = _FakeGame()
    with patch("gamewall.llm_search.suggest_steam_match", return_value=None):
        fields, err = llm_match_and_fetch(game, "https://api.test/v1", "key", "model")
        assert fields == {}
        assert "LLM 未给出有效建议" in err
