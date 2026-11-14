"""刮削测试始终隔离运行数据，禁止触碰真实影库。"""
import pytest


@pytest.fixture(autouse=True)
def scrape_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MML_DATA_DIR", str(tmp_path / "data"))
    import utils.app_paths as paths
    from utils.config_manager import ConfigManager
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(ConfigManager, "_instance", None)
    monkeypatch.setattr(ConfigManager, "_config", {})
    # 测试不等待生产环境的站点限速，网络仍由每个测试明确替换。
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "scrape_config.json").write_text('{"douban_delay": 0}', encoding="utf-8")
    return tmp_path / "data"
