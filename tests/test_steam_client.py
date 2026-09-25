"""gamewall.steam_client 的商店详情解析测试。"""
from gamewall import steam_client


def test_fetch_appdetails_keeps_auditable_store_metadata():
    response = {
        "123": {
            "success": True,
            "data": {
                "name": "Example Game",
                "short_description": "A game",
                "header_image": "https://cdn.example/header.jpg",
                "developers": ["Studio One", "Studio Two", "Studio Three"],
                "publishers": ["Publisher One", "Publisher Two"],
                "platforms": {"windows": True, "mac": False, "linux": True},
                "categories": [
                    {"id": 2, "description": "单人"},
                    {"id": 1, "description": "多人"},
                ],
                "genres": [{"description": "动作"}],
                "release_date": {"date": "2024 年 3 月 5 日"},
                "metacritic": {"score": 88},
            },
        },
    }
    original = steam_client._http_get_json
    steam_client._http_get_json = lambda _url, timeout=12: (response, "")
    try:
        fields, error = steam_client.fetch_appdetails(123)
    finally:
        steam_client._http_get_json = original

    assert error == ""
    assert fields["developer"] == "Studio One、Studio Two"
    assert fields["publishers"] == ["Publisher One", "Publisher Two"]
    assert fields["platforms"] == ["windows", "linux"]
    assert fields["steam_categories"] == ["单人", "多人"]
    assert fields["release_date"] == "2024-03-05"
    assert fields["metacritic"] == 88.0
    assert "aaa_evidence" not in fields


def test_lookup_steam_alias_matches_renamed_games():
    assert steam_client.lookup_steam_alias(["杀手3豪华版", ""]) == 1659040
    assert steam_client.lookup_steam_alias(["杀手3", ""]) == 1659040
    assert steam_client.lookup_steam_alias(["", "HITMAN 3"]) == 1659040
    assert steam_client.lookup_steam_alias(["艾尔登法环", "Elden Ring"]) == 0
    # 泛化短名不允许命中，防止误配到同名系列旧作
    assert steam_client.lookup_steam_alias(["Hitman", ""]) == 0
    assert steam_client.lookup_steam_alias(["", ""]) == 0


def test_match_appid_returns_alias_without_network(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("alias hit must not trigger network search")

    monkeypatch.setattr(steam_client, "_search_store", _fail)
    monkeypatch.setattr(steam_client, "_search_community", _fail)
    assert steam_client.match_appid(["杀手3豪华版", "HITMAN 3"]) == (1659040, "", True)


def test_match_appid_reports_definitiveness(monkeypatch):
    monkeypatch.setattr(steam_client, "_search_store", lambda term: ([], ""))
    monkeypatch.setattr(steam_client, "_search_community", lambda term: ([], ""))
    # 搜索连通但无结果：可安全记负缓存
    assert steam_client.match_appid(["某游戏", "Some Game"]) == (0, "", True)

    monkeypatch.setattr(steam_client, "_search_store",
                        lambda term: ([], "URLError: dns failure"))
    monkeypatch.setattr(steam_client, "_search_community",
                        lambda term: ([], "URLError: dns failure"))
    # 全部搜索网络失败：不可据此记负缓存
    assert steam_client.match_appid(["某游戏", "Some Game"]) == (0, "", False)


def test_match_appid_counts_partial_success_as_definitive(monkeypatch):
    monkeypatch.setattr(steam_client, "_search_store",
                        lambda term: ([], "timeout"))
    monkeypatch.setattr(steam_client, "_search_community", lambda term: ([], ""))
    assert steam_client.match_appid(["某游戏", "Some Game"]) == (0, "", True)


if __name__ == "__main__":
    test_fetch_appdetails_keeps_auditable_store_metadata()
    test_lookup_steam_alias_matches_renamed_games()
    test_match_appid_returns_alias_without_network()
    test_match_appid_reports_definitiveness()
    test_match_appid_counts_partial_success_as_definitive()
    print("steam client tests passed")
