"""契约 3.3：设置读写（含 API key 掩码）。"""
from tests.webapp.test_game_helpers import (
    API,
    game_client,
    set_game_settings,
)


def test_settings_read_defaults(service_data_dir):
    """GET /settings 返回默认值，API key 不回明文。"""
    with game_client(service_data_dir) as client:
        response = client.get(f"{API}/settings")
        assert response.status_code == 200, response.text
        data = response.json()

        # 契约 3.3 字段齐全
        assert "excel_path" in data
        assert "game_dirs" in data
        assert "poster_scale" in data
        assert "network_enabled" in data
        assert "enable_enrichment" in data
        assert "enable_gamersky_scraper" in data
        assert "enable_ign_scraper" in data
        assert "llm_enabled" in data
        assert "llm_base_url" in data
        assert "llm_model" in data
        assert "llm_api_key_set" in data
        assert "llm_api_key_mask" in data

        # 默认值
        assert data["excel_path"] == ""
        assert data["game_dirs"] == []
        assert data["poster_scale"] == 100
        assert data["network_enabled"] is True
        assert data["llm_api_key_set"] is False
        assert data["llm_api_key_mask"] == ""

        # 绝不回明文 llm_api_key
        assert "llm_api_key" not in data or data.get("llm_api_key") == ""


def test_settings_write_and_read(service_data_dir):
    """PUT /settings 部分更新，GET 回读验证。"""
    with game_client(service_data_dir) as client:
        # 写入
        response = client.put(f"{API}/settings", json={
            "excel_path": "/tmp/test.xlsx",
            "game_dirs": ["/mnt/games"],
            "poster_scale": 120,
            "network_enabled": False,
            "llm_enabled": True,
            "llm_base_url": "https://api.example.com/v1",
            "llm_model": "gpt-4o",
            "llm_api_key": "sk-abcdefgh12345678",
        })
        assert response.status_code == 200, response.text
        assert response.json() == {"saved": True}

        # 回读
        data = client.get(f"{API}/settings").json()
        assert data["excel_path"] == "/tmp/test.xlsx"
        assert data["game_dirs"] == ["/mnt/games"]
        assert data["poster_scale"] == 120
        assert data["network_enabled"] is False
        assert data["llm_enabled"] is True
        assert data["llm_base_url"] == "https://api.example.com/v1"
        assert data["llm_model"] == "gpt-4o"
        assert data["llm_api_key_set"] is True
        # 掩码格式 sk-a***5678
        assert data["llm_api_key_mask"] == "sk-a***5678"


def test_settings_api_key_masking(service_data_dir):
    """API key 掩码规则：短 key → ***，长 key → sk-a***efgh。"""
    with game_client(service_data_dir) as client:
        # 短 key
        client.put(f"{API}/settings", json={"llm_api_key": "abc"})
        data = client.get(f"{API}/settings").json()
        assert data["llm_api_key_mask"] == "***"

        # 空 key
        client.put(f"{API}/settings", json={"llm_api_key": ""})
        data = client.get(f"{API}/settings").json()
        assert data["llm_api_key_set"] is False
        assert data["llm_api_key_mask"] == ""

        # 正常 key
        client.put(f"{API}/settings", json={"llm_api_key": "sk-proj-1234567890abcdef"})
        data = client.get(f"{API}/settings").json()
        assert data["llm_api_key_set"] is True
        assert data["llm_api_key_mask"] == "sk-p***cdef"


def test_settings_validation(service_data_dir):
    """设置校验：未知键、类型错误、范围越界。"""
    with game_client(service_data_dir) as client:
        # 未知键
        response = client.put(f"{API}/settings", json={"unknown_key": 1})
        assert response.status_code == 400, response.text

        # 类型错误
        response = client.put(f"{API}/settings", json={"poster_scale": "abc"})
        assert response.status_code == 400, response.text

        response = client.put(f"{API}/settings", json={"network_enabled": "yes"})
        assert response.status_code == 400, response.text

        # 范围越界
        response = client.put(f"{API}/settings", json={"poster_scale": 10})
        assert response.status_code == 400, response.text

        response = client.put(f"{API}/settings", json={"poster_scale": 300})
        assert response.status_code == 400, response.text

        # game_dirs 必须是字符串数组
        response = client.put(f"{API}/settings", json={"game_dirs": [123]})
        assert response.status_code == 400, response.text


def test_settings_empty_body(service_data_dir):
    """空请求体返回 400。"""
    with game_client(service_data_dir) as client:
        response = client.put(f"{API}/settings", json={})
        assert response.status_code == 400, response.text
