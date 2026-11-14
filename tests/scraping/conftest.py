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
    return tmp_path / "data"
