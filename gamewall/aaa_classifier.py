"""
可追溯的 3A 自动分类规则。

证据必须带来源，格式示例：
{
    "large_developer": {"confirmed": True, "sources": ["内置大型开发商名录：FromSoftware"]},
    "metacritic": {"value": 94, "sources": ["Steam 商店 Metacritic 评分"]},
}

build_auto_evidence() 从游戏已有数据（Steam 商店资料、评价统计、网盘资源体积
与内置大厂名录）推导证据；无来源或格式不合法的证据一律未知并计 0。
"""
from collections.abc import Mapping
from typing import Any


RULE_VERSION = "3.0"

RULES = (
    ("large_developer", "大型开发商", 15),
    ("large_publisher", "大型发行商", 10),
    ("metacritic_high", "Metacritic 80 分以上", 12),
    ("metacritic_mid", "Metacritic 70-79 分", 5),
    ("steam_reviews_high", "Steam 评价数 5 万以上", 15),
    ("steam_reviews_mid", "Steam 评价数 1-5 万", 8),
    ("game_size_50gb", "资源体积 50GB 以上", 10),
    ("game_size_20gb", "资源体积 20-50GB", 5),
    ("open_world_or_complex_systems", "开放世界/沙盒等大型系统", 10),
    ("global_multiplatform", "跨多平台发行", 10),
)

if len(RULES) != 10 or sum(weight for _, _, weight in RULES) != 100:
    raise RuntimeError("3A 分类规则必须恰好十项且总权重为 100")

# 命名档位：>=55 AAA；>=40 准 3A；>=25 AA；其余 INDIE
_TIER_THRESHOLDS = ((55, "AAA"), (40, "AAA_EDGE"), (25, "AA"))

_BOOLEAN_EVIDENCE = {
    "large_developer": "large_developer",
    "large_publisher": "large_publisher",
    "open_world_or_complex_systems": "open_world_or_complex_systems",
    "global_multiplatform": "global_multiplatform",
}

_METRIC_EVIDENCE = {
    "metacritic_high": ("metacritic", lambda value: value >= 80),
    "metacritic_mid": ("metacritic", lambda value: 70 <= value < 80),
    "steam_reviews_high": ("steam_review_total", lambda value: value >= 50_000),
    "steam_reviews_mid": ("steam_review_total", lambda value: 10_000 <= value < 50_000),
    "game_size_50gb": ("game_size_gb", lambda value: value >= 50),
    "game_size_20gb": ("game_size_gb", lambda value: 20 <= value < 50),
}

# 内置名录：与 Steam developer/publishers 字段做不区分大小写的包含匹配
LARGE_DEVELOPERS = (
    "FromSoftware", "Rockstar Games", "Rockstar North", "Rockstar San Diego",
    "Naughty Dog", "Santa Monica Studio", "SIE Santa Monica Studio",
    "CD Projekt RED", "CD PROJEKT RED", "Bethesda Game Studios", "id Software",
    "MachineGames", "Arkane Studios", "ZeniMax Online Studios", "Valve",
    "Ubisoft Montreal", "Ubisoft Massive", "Massive Entertainment", "Ubisoft",
    "Electronic Arts", "EA DICE", "DICE", "Motive Studio", "Criterion Games",
    "Respawn Entertainment", "Infinity Ward", "Treyarch", "Sledgehammer Games",
    "Raven Software", "Blizzard Entertainment", "Bungie", "343 Industries",
    "Halo Studios", "Capcom", "Square Enix", "Bandai Namco Studios",
    "Kojima Productions", "Insomniac Games", "Guerrilla Games",
    "Nixxes Software", "Rocksteady Studios", "Remedy Entertainment",
    "Nintendo", "Game Freak", "HAL Laboratory", "Intelligent Systems",
    "Monolith Soft", "Firaxis Games", "Visual Concepts", "Hangar 13",
    "Cloud Chamber", "Digital Extremes", "Warhorse Studios", "Larian Studios",
    "GSC Game World", "Techland", "Quantic Dream", "Don't Nod",
    "Dontnod Entertainment", "Sucker Punch Productions", "Bluepoint Games",
    "Team NINJA", "KOEI TECMO", "PlatinumGames", "Gearbox Software",
    "NetherRealm Studios", "Turn 10 Studios", "Playground Games",
    "Rare Ltd", "Rare Limited", "Mojang Studios", "miHoYo", "HoYoverse",
    "米哈游", "库洛游戏", "Kuro Games", "腾讯游戏", "Tencent Games",
    "网易游戏", "NetEase Games",
)

LARGE_PUBLISHERS = (
    "Electronic Arts", "EA Sports", "Activision", "Ubisoft",
    "Take-Two Interactive", "Take-Two", "2K Games", "2K Sports",
    "Private Division", "Rockstar Games", "Sony Interactive Entertainment",
    "Xbox Game Studios", "Microsoft Studios", "Bethesda Softworks",
    "Bandai Namco Entertainment", "万代南梦宫", "Square Enix", "Capcom",
    "Sega", "Atlus", "Nintendo", "Warner Bros. Games",
    "Warner Bros. Interactive Entertainment", "WB Games", "Koch Media",
    "Deep Silver", "Plaion", "Focus Entertainment", "Focus Home Interactive",
    "505 Games", "CD PROJEKT RED", "CD Projekt", "Gearbox Publishing",
    "Paradox Interactive", "THQ Nordic", "Tencent Games", "Level Infinite",
    "Perfect World", "NetEase Games", "网易游戏", "miHoYo", "HoYoverse",
    "米哈游", "Nexon", "NCSoft", "KRAFTON", "Koei Tecmo Games",
)

_OPEN_WORLD_KEYWORDS = ("开放世界", "open world", "沙盒", "sandbox")

_GB = 1024 ** 3


def _match_curated(text_lower: str, names) -> str:
    for name in names:
        if name.lower() in text_lower:
            return name
    return ""


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _string_list(value) -> list:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def build_auto_evidence(game) -> dict:
    """从游戏已有数据推导带来源证据；缺失字段保持未知，不参与计分。"""
    evidence = {}

    developer = (getattr(game, "developer", "") or "").strip()
    if developer:
        matched = _match_curated(developer.lower(), LARGE_DEVELOPERS)
        if matched:
            evidence["large_developer"] = {
                "confirmed": True,
                "sources": [f"内置大型开发商名录：{matched}"],
            }

    publishers = "、".join(_string_list(getattr(game, "publishers", None)))
    if publishers:
        matched = _match_curated(publishers.lower(), LARGE_PUBLISHERS)
        if matched:
            evidence["large_publisher"] = {
                "confirmed": True,
                "sources": [f"内置大型发行商名录：{matched}"],
            }

    metacritic = _number(getattr(game, "metacritic", 0))
    if metacritic > 0:
        evidence["metacritic"] = {
            "value": metacritic,
            "sources": ["Steam 商店 Metacritic 评分"],
        }

    review_total = getattr(game, "steam_review_total", 0)
    if isinstance(review_total, int) and not isinstance(review_total, bool) and review_total > 0:
        evidence["steam_review_total"] = {
            "value": review_total,
            "sources": ["Steam 商店评价统计"],
        }

    size_gb = round(_number(getattr(game, "size_bytes", 0)) / _GB, 1)
    if size_gb > 0:
        evidence["game_size_gb"] = {
            "value": size_gb,
            "sources": ["网盘资源体积"],
        }

    tags = _string_list(getattr(game, "genres", None)) + \
        _string_list(getattr(game, "steam_categories", None))
    tag_text = " | ".join(tags).lower()
    if tag_text:
        hit = next((k for k in _OPEN_WORLD_KEYWORDS if k in tag_text), "")
        if hit:
            evidence["open_world_or_complex_systems"] = {
                "confirmed": True,
                "sources": [f"Steam 类型/分类标签：{hit}"],
            }

    platforms = _string_list(getattr(game, "platforms", None))
    if len(platforms) >= 2:
        evidence["global_multiplatform"] = {
            "confirmed": True,
            "sources": ["Steam 平台支持：" + "/".join(platforms)],
        }

    return evidence


def _sources(record: Mapping[str, Any]) -> list[str]:
    value = record.get("sources", record.get("source", []))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _record(evidence: Any, key: str) -> tuple[Mapping[str, Any] | None, list[str]]:
    if not isinstance(evidence, Mapping):
        return None, []
    value = evidence.get(key)
    if not isinstance(value, Mapping):
        return None, []
    sources = _sources(value)
    return (value, sources) if sources else (None, [])


def _tier(score: int) -> str:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return "INDIE"


def classify_aaa(evidence: Any) -> dict:
    """按固定十项规则计算 3A 分数；无来源或格式不合法的证据一律未知并计 0。"""
    score = 0
    rule_results = []

    for rule_id, label, weight in RULES:
        result = {
            "id": rule_id,
            "label": label,
            "weight": weight,
            "status": "unknown",
            "sources": [],
        }
        if rule_id in _BOOLEAN_EVIDENCE:
            record, sources = _record(evidence, _BOOLEAN_EVIDENCE[rule_id])
            if record is not None:
                result["sources"] = sources
                result["status"] = "hit" if record.get("confirmed") is True else "not_met"
        else:
            evidence_key, predicate = _METRIC_EVIDENCE[rule_id]
            record, sources = _record(evidence, evidence_key)
            if record is not None:
                value = record.get("value")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    result["sources"] = sources
                    result["observed_value"] = value
                    result["status"] = "hit" if predicate(value) else "not_met"

        if result["status"] == "hit":
            score += weight
        rule_results.append(result)

    return {
        "score": score,
        "tier": _tier(score),
        "rule_version": RULE_VERSION,
        "rule_results": rule_results,
    }
