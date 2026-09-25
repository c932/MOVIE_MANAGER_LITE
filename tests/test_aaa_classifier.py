"""gamewall.aaa_classifier 单元测试。"""
from gamewall.aaa_classifier import (
    RULES,
    RULE_VERSION,
    build_auto_evidence,
    classify_aaa,
)


def _boolean(key: str):
    return {key: {"confirmed": True, "sources": ["内置名录"]}}


def _metric(key: str, value: float):
    return {key: {"value": value, "sources": ["Steam 商店数据"]}}


def _status(result: dict, rule_id: str) -> str:
    return next(item["status"] for item in result["rule_results"] if item["id"] == rule_id)


class _FakeGame:
    """模拟 Game 对象：只提供 build_auto_evidence 需要的字段。"""

    def __init__(self, **kwargs):
        self.developer = ""
        self.publishers = []
        self.platforms = []
        self.genres = []
        self.steam_categories = []
        self.metacritic = 0.0
        self.steam_review_total = 0
        self.size_bytes = 0.0
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_rule_contract_and_individual_scores():
    assert len(RULES) == 10
    assert sum(weight for _, _, weight in RULES) == 100
    assert RULE_VERSION

    assert classify_aaa(_boolean("large_developer"))["score"] == 15
    assert classify_aaa(_boolean("large_publisher"))["score"] == 10
    assert classify_aaa(_boolean("open_world_or_complex_systems"))["score"] == 5
    assert classify_aaa(_boolean("global_multiplatform"))["score"] == 5
    assert classify_aaa(_metric("metacritic", 85))["score"] == 15
    assert classify_aaa(_metric("metacritic", 80))["score"] == 5
    assert classify_aaa(_metric("steam_review_total", 100_000))["score"] == 20
    assert classify_aaa(_metric("steam_review_total", 20_000))["score"] == 10
    assert classify_aaa(_metric("game_size_gb", 50))["score"] == 10
    assert classify_aaa(_metric("game_size_gb", 20))["score"] == 5


def test_metric_bands_are_mutually_exclusive():
    top = classify_aaa(_metric("metacritic", 94))
    assert _status(top, "metacritic_85") == "hit"
    assert _status(top, "metacritic_80") == "not_met"

    mid = classify_aaa(_metric("metacritic", 82))
    assert _status(mid, "metacritic_85") == "not_met"
    assert _status(mid, "metacritic_80") == "hit"
    assert mid["score"] == 5

    viral = classify_aaa(_metric("steam_review_total", 150_000))
    assert _status(viral, "steam_reviews_100k") == "hit"
    assert _status(viral, "steam_reviews_20k") == "not_met"

    small = classify_aaa(_metric("steam_review_total", 5_000))
    assert small["score"] == 0
    assert _status(small, "steam_reviews_20k") == "not_met"

    big = classify_aaa(_metric("game_size_gb", 60.5))
    assert _status(big, "game_size_50gb") == "hit"
    assert _status(big, "game_size_20gb") == "not_met"


def test_tier_boundaries():
    full = {
        **_boolean("large_developer"),
        **_boolean("large_publisher"),
        **_metric("metacritic", 94),
        **_metric("steam_review_total", 250_000),
        **_metric("game_size_gb", 60),
    }
    assert classify_aaa(full)["score"] == 70
    assert classify_aaa(full)["tier"] == "AAA"

    edge = {
        **_boolean("large_developer"),
        **_boolean("large_publisher"),
        **_metric("metacritic", 82),
        **_metric("steam_review_total", 150_000),
    }
    assert classify_aaa(edge)["score"] == 50
    assert classify_aaa(edge)["tier"] == "AAA_EDGE"

    aa = {
        **_boolean("large_developer"),
        **_boolean("large_publisher"),
        **_metric("steam_review_total", 30_000),
    }
    assert classify_aaa(aa)["score"] == 35
    assert classify_aaa(aa)["tier"] == "AA"
    assert classify_aaa({})["tier"] == "INDIE"


def test_unsourced_evidence_scores_zero():
    result = classify_aaa({
        "large_developer": {"confirmed": True},
        "metacritic": {"value": 100},
        "steam_positive_pct": {"value": 100, "sources": ["Steam"]},
        "ign_score": {"value": 10, "sources": ["IGN"]},
    })
    assert result["score"] == 0
    assert _status(result, "large_developer") == "unknown"

    rejected = classify_aaa({
        "large_publisher": {"confirmed": False, "sources": ["公开资料"]},
    })
    assert _status(rejected, "large_publisher") == "not_met"


def test_build_auto_evidence_for_typical_aaa():
    game = _FakeGame(
        developer="FromSoftware, Inc.",
        publishers=["FromSoftware, Inc.", "Bandai Namco Entertainment"],
        metacritic=94.0,
        steam_review_total=250_000,
        size_bytes=60 * 1024 ** 3,
        platforms=["windows"],
        genres=["动作", "角色扮演"],
    )
    evidence = build_auto_evidence(game)
    assert evidence["large_developer"]["confirmed"] is True
    assert "FromSoftware" in evidence["large_developer"]["sources"][0]
    assert evidence["large_publisher"]["confirmed"] is True
    assert evidence["metacritic"]["value"] == 94.0
    assert evidence["steam_review_total"]["value"] == 250_000
    assert evidence["game_size_gb"]["value"] == 60.0
    assert "open_world_or_complex_systems" not in evidence
    assert "global_multiplatform" not in evidence

    result = classify_aaa(evidence)
    assert result["score"] == 70
    assert result["tier"] == "AAA"


def test_build_auto_evidence_curated_matching_is_case_insensitive():
    game = _FakeGame(developer="larian studios gmbh")
    evidence = build_auto_evidence(game)
    assert evidence["large_developer"]["confirmed"] is True
    assert "Larian Studios" in evidence["large_developer"]["sources"][0]


def test_build_auto_evidence_open_world_and_multiplatform():
    game = _FakeGame(
        genres=["开放世界", "冒险"],
        platforms=["windows", "mac"],
    )
    evidence = build_auto_evidence(game)
    assert evidence["open_world_or_complex_systems"]["confirmed"] is True
    assert evidence["global_multiplatform"]["confirmed"] is True
    assert classify_aaa(evidence)["score"] == 10


def test_build_auto_evidence_skips_unknown_studio_and_missing_fields():
    game = _FakeGame(developer="Blackbird Interactive", publishers=["Gearbox Publishing"])
    evidence = build_auto_evidence(game)
    assert "large_developer" not in evidence
    assert evidence["large_publisher"]["confirmed"] is True

    empty = build_auto_evidence(_FakeGame())
    assert empty == {}
    assert classify_aaa(empty)["score"] == 0
    assert classify_aaa(empty)["tier"] == "INDIE"


if __name__ == "__main__":
    test_rule_contract_and_individual_scores()
    test_metric_bands_are_mutually_exclusive()
    test_tier_boundaries()
    test_unsourced_evidence_scores_zero()
    test_build_auto_evidence_for_typical_aaa()
    test_build_auto_evidence_curated_matching_is_case_insensitive()
    test_build_auto_evidence_open_world_and_multiplatform()
    test_build_auto_evidence_skips_unknown_studio_and_missing_fields()
    print("all aaa classifier tests passed")
