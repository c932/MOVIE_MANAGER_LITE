"""契约 3.2：Excel 差分/应用任务。"""
from tests.webapp.test_game_helpers import (
    API,
    build_excel,
    excel_apply,
    excel_diff,
    find_game,
    game_client,
    games_of,
    set_game_settings,
)


def test_excel_diff_task(service_data_dir):
    """excel.diff 任务返回 added/updated/removed/counts/excel_meta。"""
    from gamewall.name_utils import normalize_name

    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
        {"name": "游戏B", "size_text": "20 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        # 先应用一次建立库
        excel_apply(client)

        # 修改 Excel：新增 C，改 B 的版本，移除 A
        excel_path = build_excel(data_dir / "games.xlsx", [
            {"name": "游戏B", "size_text": "20 GB", "version": "v2.0"},
            {"name": "游戏C", "size_text": "15 GB"},
        ])

        job = excel_diff(client)
        result = job["result"]
        # norm_key 经 normalize_name 小写化
        assert result["added"] == [normalize_name("游戏C")]
        assert result["updated"] == [normalize_name("游戏B")]
        assert result["removed"] == [normalize_name("游戏A")]
        assert result["counts"] == {"added": 1, "updated": 1, "removed": 1}
        assert result["excel_meta"]["path"] == str(excel_path)
        assert result["excel_meta"]["game_count"] == 2


def test_excel_apply_task(service_data_dir):
    """excel.apply 应用后游戏库更新，含 total。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB", "quark_link": "https://a"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        job = excel_apply(client)
        result = job["result"]
        assert result["total"] == 1
        # 首次应用时 store 已自动加载 Excel，故 added 可能为 0
        assert result["counts"]["added"] == 0

        # 库已建立
        assert len(games_of(client)) == 1
        game = find_game(client, "游戏A")
        assert game["quark_link"] == "https://a"


def test_excel_apply_reclassify(service_data_dir):
    """excel.apply 触发规则分类重算（tier_source=excel 当 Excel 标记 3A）。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "大制作游戏", "size_text": "80 GB", "aaa_excel_marked": "是"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        game = find_game(client, "大制作游戏")
        assert game["aaa_excel_marked"] is True
        assert game["tier_source"] == "excel"


def test_excel_apply_no_config(service_data_dir):
    """未配置 Excel 时提交任务返回 400。"""
    with game_client(service_data_dir) as client:
        response = client.post(f"{API}/games/excel/diff")
        assert response.status_code == 400, response.text
        assert "detail" in response.json()

        response = client.post(f"{API}/games/excel/apply")
        assert response.status_code == 400, response.text


def test_excel_apply_empty_result(service_data_dir):
    """Excel 解析结果为空时任务 error，保留当前库。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        assert len(games_of(client)) == 1

        # 用空表覆盖（只有表头无数据）
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["游戏名", "下载链接", "大小", "版本", "更新日期", "发布日期", "IGN", "Steam", "3A"])
        wb.save(excel_path)

        job = excel_apply(client, expect="error")
        assert "error" in job
        # 库未被清空
        assert len(games_of(client)) == 1
