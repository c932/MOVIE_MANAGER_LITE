"""
网页版服务端测试共享夹具。

⚠️ 安全铁律：任何写数据的测试必须通过 `service_data_dir` 夹具把
数据目录指到 pytest 临时目录，绝对不允许写进真实 data/ 目录。
MML_TESTING 会让 wall_common.settings.resolve() 在未显式指定目录时
也强制使用临时目录（双保险）。
"""
import os

import pytest

os.environ.setdefault("MML_TESTING", "1")


@pytest.fixture
def service_data_dir(tmp_path, monkeypatch):
    """
    把 utils.app_paths.DATA_DIR 指向临时目录，并重置 ConfigManager 单例，
    保证不经过 app 工厂的领域层测试也读写 tmp_path。返回该临时目录。
    """
    import utils.app_paths as app_paths

    monkeypatch.setattr(app_paths, "DATA_DIR", tmp_path)
    monkeypatch.setenv("MML_DATA_DIR", str(tmp_path))

    from utils.config_manager import ConfigManager

    monkeypatch.setattr(ConfigManager, "_instance", None)
    monkeypatch.setattr(ConfigManager, "_config", {})

    yield tmp_path
