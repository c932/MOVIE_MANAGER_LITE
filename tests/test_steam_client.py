"""gamewall.steam_client 的商店详情解析测试。"""
from gamewall import steam_client


def test_appreviews_rejects_response_without_summary(monkeypatch):
    monkeypatch.setattr(steam_client, "_http_get_json", lambda url: ({"success": 2}, None))
    fields, error = steam_client.fetch_appreviews(620)
    assert fields is None
    assert error.startswith(steam_client.RESPONSE_ERROR_PREFIX)


def test_bad_review_responses_pause_reviews_but_keep_fetching_details(monkeypatch):
    from gamewall.enrichment_worker import EnrichmentWorker, REVIEW_RESPONSE_BREAKER
    from gamewall.game_models import Game

    monkeypatch.setattr("gamewall.enrichment_worker.STEAM_WORKERS", 1)
    monkeypatch.setattr(steam_client, "set_cancel_check", lambda _: None)
    monkeypatch.setattr(steam_client, "fetch_appdetails",
                        lambda appid: ({"description": "valid details"}, ""))
    requests = []

    def bad_reviews(appid):
        requests.append(appid)
        return None, steam_client.RESPONSE_ERROR_PREFIX + "non-JSON"

    monkeypatch.setattr(steam_client, "fetch_appreviews", bad_reviews)
    games = [Game(raw_name=f"Game {i}", steam_appid=i + 1)
             for i in range(REVIEW_RESPONSE_BREAKER + 3)]
    worker = EnrichmentWorker(games, enable_gamersky=False)
    enriched, failed, negatives = [], [], []
    worker.game_enriched.connect(lambda key, fields: enriched.append(key))
    worker.failed.connect(failed.append)
    worker.negative_recorded.connect(lambda *args: negatives.append(args))
    worker.run()
    assert len(requests) == REVIEW_RESPONSE_BREAKER
    assert len(enriched) == len(games)
    assert not failed and not negatives


def test_steam_retries_transient_transport_failure(monkeypatch):
    import io
    from urllib.error import URLError

    attempts = iter([URLError(TimeoutError("timed out")), io.BytesIO(b'{}')])

    def open_request(*args, **kwargs):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        result.headers = {}
        return result

    monkeypatch.setattr(steam_client.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(steam_client, "_sleep", lambda _: None)
    assert steam_client._http_get_json("https://store.steampowered.com/appreviews/620") == ({}, None)


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


def test_search_steam_merges_and_dedupes_sources(monkeypatch):
    monkeypatch.setattr(steam_client, "_search_store",
                        lambda term: ([{"id": 10, "name": "Game A"},
                                       {"id": 20, "name": "Game B"}], ""))
    monkeypatch.setattr(steam_client, "_search_community",
                        lambda term: ([{"appid": 20, "name": "Game B dup"},
                                       {"appid": 30, "name": "Game C"}], ""))
    items, err = steam_client.search_steam("abc")
    assert err == ""
    assert [(i["appid"], i["name"]) for i in items] == [
        (10, "Game A"), (20, "Game B"), (30, "Game C")]


def test_search_steam_rejects_empty_term():
    assert steam_client.search_steam("   ") == ([], "搜索词为空")


def test_search_steam_reports_network_error(monkeypatch):
    monkeypatch.setattr(steam_client, "_search_store", lambda term: ([], "URLError"))
    monkeypatch.setattr(steam_client, "_search_community", lambda term: ([], "timeout"))
    items, err = steam_client.search_steam("abc")
    assert items == []
    assert err == "URLError"


if __name__ == "__main__":
    test_fetch_appdetails_keeps_auditable_store_metadata()
    test_lookup_steam_alias_matches_renamed_games()
    test_match_appid_returns_alias_without_network()
    test_match_appid_reports_definitiveness()
    test_match_appid_counts_partial_success_as_definitive()
    print("steam client tests passed")
