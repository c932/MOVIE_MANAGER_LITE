"""
gamewall.name_utils 单元测试
覆盖：归一化（全/半角括号、中点）、中英文切分、Steam 名称匹配
"""
from gamewall.name_utils import normalize_name, split_title, SteamNameIndex


def test_normalize_name():
    assert normalize_name("ELDEN RING") == "eldenring"
    assert normalize_name("艾尔登法环") == "艾尔登法环"
    # 全/半角括号等价
    assert normalize_name("塞尔达传说（旷野之息）") == normalize_name("塞尔达传说(旷野之息)")
    # 中点（全角・半角）去除
    assert normalize_name("尼尔·机械纪元") == normalize_name("尼尔・机械纪元")
    assert normalize_name("NieR:Automata") == normalize_name("NieR Automata")
    # 冒号、连字符、空白
    assert normalize_name("Half-Life 2") == normalize_name("halflife2")
    assert normalize_name("The Witcher 3: Wild Hunt") == "thewitcher3wildhunt"
    # 重音符号
    assert normalize_name("Pokémon") == normalize_name("pokemon")
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_split_title():
    assert split_title("黎明行者之血/The Blood of Dawnwalker") == ("黎明行者之血", "The Blood of Dawnwalker")
    assert split_title("龙之信条2/Dragon's Dogma 2") == ("龙之信条2", "Dragon's Dogma 2")
    # 无分隔符
    assert split_title("不心动才有鬼") == ("不心动才有鬼", "")
    # 英文名自带斜杠：按首个切分
    assert split_title("命运之夜/Fate/Stay Night") == ("命运之夜", "Fate/Stay Night")
    # 全角斜杠
    assert split_title("艾尔登法环／ELDEN RING") == ("艾尔登法环", "ELDEN RING")
    assert split_title("") == ("", "")
    assert split_title(None) == ("", "")


def _index():
    names = {
        "ELDEN RING": 1245620,
        "艾尔登法环": 1245620,
        "The Witcher 3: Wild Hunt": 292030,
        "Cyberpunk 2077": 1091500,
        "DOOM": 379720,
        "Half-Life 2": 220,
        "Fate/Stay Night": 999999,
    }
    return SteamNameIndex(names)


def test_match_exact():
    idx = _index()
    assert idx.find_best_match(["艾尔登法环", "ELDEN RING"]) == 1245620
    assert idx.find_best_match(["Cyberpunk 2077"]) == 1091500
    # 归一化后精确（括号/中点差异）
    assert idx.find_best_match(["Cyberpunk 2077（豪华版）"]) == 1091500


def test_match_substring_and_fuzzy():
    idx = _index()
    # 子串：The Witcher 3 (长度比 12/24=0.5 < 0.6 → 不该命中，防止误匹配)
    assert idx.find_best_match(["The Witcher 3"]) == 0
    # 模糊：轻微变体
    assert idx.find_best_match(["The Witcher 3 Wild Hunt GOTY"]) == 292030
    # 完全无匹配
    assert idx.find_best_match(["完全无关的游戏名称XYZ"]) == 0
    # 英文名自带斜杠不影响
    assert idx.find_best_match(["Fate/Stay Night"]) == 999999


def test_match_performance():
    """4694 个游戏 × 20 万 Steam 名称规模的匹配应在可接受时间内完成（匹配阶段仅运行一次并缓存）"""
    import time
    big = {f"Steam Game Name {i}": i for i in range(1, 200001)}
    big["艾尔登法环"] = 1245620
    t0 = time.perf_counter()
    idx = SteamNameIndex(big)
    t1 = time.perf_counter()
    hits = idx.find_best_match(["艾尔登法环", "ELDEN RING"])
    miss = idx.find_best_match(["某款不存在的游戏"])
    t2 = time.perf_counter()
    assert hits == 1245620 and miss == 0
    assert t1 - t0 < 15, f"建索引过慢: {t1 - t0:.1f}s"
    assert t2 - t1 < 10, f"单次匹配过慢: {t2 - t1:.1f}s"


if __name__ == "__main__":
    test_normalize_name()
    test_split_title()
    test_match_exact()
    test_match_substring_and_fuzzy()
    test_match_performance()
    print("all name_utils tests passed")
