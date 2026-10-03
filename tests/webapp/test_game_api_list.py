"""契约 3.1/3.2：游戏列表、详情、DTO 归一化、手动 tier 标记与恢复。"""
from tests.webapp.test_game_helpers import (
    API,
    GAME_DTO_KEYS,
    build_excel,
    excel_apply,
    find_game,
    game_client,
    games_of,
    set_game_settings,
)


def test_list_detail_shape(service_data_dir):
    """列表/详情字段齐全，DTO 归一化正确。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {
            "name": "艾尔登法环.Elden.Ring",
            "quark_link": "https://pan.quark.cn/test",
            "size_text": "45.2 GB",
            "version": "v1.09",
            "update_date": "2024-01-01",
            "release_date": "2022-02-25",
            "ign_score": "9.5",
            "steam_appid": "1245620",
            "aaa_excel_marked": "",
        },
        {
            "name": "空洞骑士.Hollow.Knight",
            "quark_link": "",
            "size_text": "5 GB",
            "version": "",
            "update_date": "",
            "release_date": "2017-02-24",
            "ign_score": "",
            "steam_appid": "",
            "aaa_excel_marked": "",
        },
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        # 列表
        response = client.get(f"{API}/games")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert len(body["games"]) == 2
        assert body["cache_info"]["version"] >= 0

        # DTO 字段完整性
        from gamewall.name_utils import normalize_name
        elden_key = normalize_name("艾尔登法环.Elden.Ring")
        elden = find_game(client, elden_key)
        for key in GAME_DTO_KEYS:
            assert key in elden, f"缺少契约字段 {key}"

        # tier / is_aaa / tier_source（未标记时来自 rule）
        assert elden["tier"] in ("3A", "2A", "精品小众", "普通游戏", "避坑")
        assert elden["tier_source"] == "rule"
        assert isinstance(elden["is_aaa"], bool)
        assert elden["aaa_score"] >= 0

        # rating / rating_source（ign > gamersky > steam）
        assert elden["rating"] == 9.5
        assert elden["rating_source"] == "ign"

        # has_cover：Excel 不提供 steam_appid，初始无封面
        assert elden["has_cover"] is False

        # 详情
        detail = client.get(f"{API}/games/{elden['key']}").json()
        assert detail["key"] == elden["key"]
        assert detail["description"] == elden["description"]
        assert detail["ign_score"] == 9.5


def test_tier_manual_override_and_recovery(service_data_dir):
    """手动标记 tier 与恢复自动判断。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "测试游戏", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)

        game = find_game(client, "测试游戏")
        original_tier = game["tier"]
        assert game["tier_source"] == "rule"
        assert game["aaa_manual_override"] is None

        # 手动标记为 3A
        response = client.put(
            f"{API}/games/{game['key']}/tier",
            json={"tier": "3A"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["tier"] == "3A"
        assert data["tier_source"] == "manual"
        assert data["aaa_manual_override"] == "3A"
        assert data["is_aaa"] is True

        # 恢复自动判断
        response = client.put(
            f"{API}/games/{game['key']}/tier",
            json={"tier": None},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["tier"] == original_tier
        assert data["tier_source"] == "rule"
        assert data["aaa_manual_override"] is None


def test_tier_invalid_value(service_data_dir):
    """tier 非法值返回 400。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "测试游戏", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "测试游戏")

        response = client.put(
            f"{API}/games/{game['key']}/tier",
            json={"tier": "不存在"},
        )
        assert response.status_code == 400, response.text
        assert "detail" in response.json()


def test_game_404(service_data_dir):
    """不存在的 key 各端点一律 404。"""
    data_dir = service_data_dir

    with game_client(data_dir) as client:
        missing = "不存在的游戏"
        endpoints = [
            client.get(f"{API}/games/{missing}"),
            client.put(f"{API}/games/{missing}", json={"description": "x"}),
            client.put(f"{API}/games/{missing}/tier", json={"tier": "3A"}),
            client.get(f"{API}/games/{missing}/cover"),
            client.post(f"{API}/games/{missing}/cover/refresh"),
        ]
        for response in endpoints:
            assert response.status_code == 404, response.text
            assert "detail" in response.json()


def test_put_game_fields(service_data_dir):
    """PUT /games/{key} 编辑字段。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "测试游戏", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "测试游戏")

        # 正常编辑
        response = client.put(
            f"{API}/games/{game['key']}",
            json={
                "description": "这是一段新的简介",
                "genres": ["动作", "角色扮演"],
                "ign_score": 8.5,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["description"] == "这是一段新的简介"
        assert data["genres"] == ["动作", "角色扮演"]
        assert data["ign_score"] == 8.5

        # 编辑后 rating_source 更新（ign > gamersky > steam）
        assert data["rating"] == 8.5
        assert data["rating_source"] == "ign"

        # steam_appid 不允许通过 PUT 直接修改
        response = client.put(
            f"{API}/games/{game['key']}",
            json={"steam_appid": 12345},
        )
        assert response.status_code == 400, response.text

        # 未知字段
        response = client.put(
            f"{API}/games/{game['key']}",
            json={"unknown_field": "x"},
        )
        assert response.status_code == 400, response.text


def test_put_game_invalid_field_type(service_data_dir):
    """字段类型校验。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "测试游戏", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "测试游戏")

        # genres 必须是字符串数组
        response = client.put(
            f"{API}/games/{game['key']}",
            json={"genres": ["动作", 123]},
        )
        assert response.status_code == 400, response.text

        # ign_score 必须是数字
        response = client.put(
            f"{API}/games/{game['key']}",
            json={"ign_score": "abc"},
        )
        assert response.status_code == 400, response.text


def test_multiple_apps_do_not_share_state(service_data_dir):
    """两个不同数据目录的 app 实例互不干扰。"""
    data_dir = service_data_dir
    data_b = data_dir / "data-b"

    excel_a = build_excel(data_dir / "games_a.xlsx", [
        {"name": "游戏A", "size_text": "10 GB"},
        {"name": "游戏B", "size_text": "20 GB"},
    ])
    excel_b = build_excel(data_dir / "games_b.xlsx", [
        {"name": "游戏C", "size_text": "15 GB"},
    ])

    with game_client(data_dir) as client_a, game_client(data_b) as client_b:
        set_game_settings(client_a, {"excel_path": str(excel_a)})
        set_game_settings(client_b, {"excel_path": str(excel_b)})

        excel_apply(client_a)
        excel_apply(client_b)

        assert len(games_of(client_a)) == 2
        assert len(games_of(client_b)) == 1


def test_dto_rating_priority(service_data_dir):
    """rating 优先级：ign > gamersky > steam（百分比/10）。"""
    data_dir = service_data_dir
    excel_path = build_excel(data_dir / "games.xlsx", [
        {"name": "评分测试", "size_text": "10 GB"},
    ])

    with game_client(data_dir) as client:
        set_game_settings(client, {"excel_path": str(excel_path)})
        excel_apply(client)
        game = find_game(client, "评分测试")

        # 初始无评分
        assert game["rating"] == 0.0
        assert game["rating_source"] == ""

        # 添加 gamersky 评分
        client.put(f"{API}/games/{game['key']}",
                   json={"gamersky_score": 8.5})
        game = find_game(client, "评分测试")
        assert game["rating"] == 8.5
        assert game["rating_source"] == "gamersky"

        # 添加 ign 评分（更高优先级）
        client.put(f"{API}/games/{game['key']}",
                   json={"ign_score": 9.2})
        game = find_game(client, "评分测试")
        assert game["rating"] == 9.2
        assert game["rating_source"] == "ign"

        # 添加 steam 评分（最低优先级）
        client.put(f"{API}/games/{game['key']}",
                   json={"steam_positive_pct": 85})
        game = find_game(client, "评分测试")
        # ign 仍最高
        assert game["rating"] == 9.2
        assert game["rating_source"] == "ign"

        # 删除 ign
        client.put(f"{API}/games/{game['key']}",
                   json={"ign_score": 0})
        game = find_game(client, "评分测试")
        # gamersky 接棒
        assert game["rating"] == 8.5
        assert game["rating_source"] == "gamersky"

        # 删除 gamersky
        client.put(f"{API}/games/{game['key']}",
                   json={"gamersky_score": 0})
        game = find_game(client, "评分测试")
        # steam 百分比 / 10
        assert game["rating"] == 8.5  # 85 / 10 = 8.5
        assert game["rating_source"] == "steam"
