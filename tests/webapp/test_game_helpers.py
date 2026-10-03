"""
游戏墙 API 测试共享工具（本文件不含测试用例）。

约定：
- 只允许在 `service_data_dir` 提供的临时目录里造数据，绝不触碰真实 data/；
- 通过 `game_client()` 创建的每个 app 实例都指向该临时目录；
- 网络相关行为一律由各测试文件 monkeypatch。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

API = "/api/game"

# 契约 3.1 GameListItem / GameDetail 的字段集合
GAME_DTO_KEYS = (
    "key", "title_cn", "title_en", "raw_name", "excel_row",
    "quark_link", "size_text", "size_bytes", "version", "update_date",
    "release_date", "aaa_excel_marked", "steam_appid", "steam_name",
    "developer", "publishers", "platforms", "steam_categories", "genres",
    "description", "steam_positive_pct", "steam_review_total",
    "metacritic", "ign_score", "gamersky_score", "header_image",
    "installed", "installed_exe", "installed_source",
    "tier", "is_aaa", "tier_source", "aaa_score", "aaa_tier",
    "aaa_evidence", "aaa_rule_version", "aaa_manual_override",
    "aaa_llm_verdict", "genres_cn", "rating", "rating_source",
    "has_cover", "needs_enrichment",
)


def build_excel(path: Path, games: Sequence[Dict[str, Any]]) -> Path:
    """创建测试用 Excel 文件。

    Args:
        path: Excel 文件保存路径
        games: 游戏数据列表，每项需含 name 键
    Returns:
        Excel 文件路径
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    # 表头（与 excel_parser._HEADER_MATCHERS 匹配）
    ws.append([
        "游戏名", "下载链接", "大小", "版本", "更新日期", "发布日期", "IGN", "Steam", "3A"
    ])
    for g in games:
        row = [
            g.get("name", ""),
            g.get("quark_link", ""),
            g.get("size_text", ""),
            g.get("version", ""),
            g.get("update_date", ""),
            g.get("release_date", ""),
            g.get("ign_score", ""),
            g.get("steam_appid", ""),
            g.get("aaa_excel_marked", ""),
        ]
        ws.append(row)
    wb.save(path)
    return path


@contextmanager
def game_client(data_dir: Path):
    """在指定临时数据目录上创建游戏墙 app 并以 TestClient 打开。"""
    from fastapi.testclient import TestClient
    from game_service.main import create

    with TestClient(create(data_dir=str(data_dir))) as client:
        yield client


def set_game_settings(client, settings: Dict[str, Any]) -> None:
    """配置游戏墙设置。"""
    response = client.put(f"{API}/settings", json=settings)
    assert response.status_code == 200, response.text


def wait_job(client, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
    """等待任务结束，返回任务对象。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"{API}/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"任务 {job_id} 超时未结束")


def excel_diff(client, expect: str = "done") -> Dict[str, Any]:
    """提交 Excel 差分并等待结束。"""
    response = client.post(f"{API}/games/excel/diff")
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == expect, f"任务状态={job['status']} error={job.get('error')}"
    return job


def excel_apply(client, expect: str = "done") -> Dict[str, Any]:
    """提交 Excel 应用并等待结束。"""
    response = client.post(f"{API}/games/excel/apply")
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == expect, f"任务状态={job['status']} error={job.get('error')}"
    return job


def enrich(client, scope: str = "all", keys: List[str] = None,
          options: Dict[str, bool] = None, expect: str = "done") -> Dict[str, Any]:
    """提交联网补全并等待结束。"""
    payload: Dict[str, Any] = {"scope": scope}
    if keys is not None:
        payload["keys"] = keys
    if options is not None:
        payload["options"] = options
    response = client.post(f"{API}/games/enrich", json=payload)
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == expect, f"任务状态={job['status']} error={job.get('error')}"
    return job


def scan_installed(client, expect: str = "done") -> Dict[str, Any]:
    """提交本地扫描并等待结束。"""
    response = client.post(f"{API}/games/scan-installed")
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == expect, f"任务状态={job['status']} error={job.get('error')}"
    return job


def games_of(client, **params) -> List[Dict[str, Any]]:
    """获取游戏列表。"""
    response = client.get(f"{API}/games", params=params)
    assert response.status_code == 200, response.text
    return response.json()["games"]


def find_game(client, key: str) -> Dict[str, Any]:
    """按 key（norm_key）或 title_cn 查找游戏。"""
    from gamewall.name_utils import normalize_name
    norm = normalize_name(key)
    for game in games_of(client):
        if game["key"] == norm or game["key"] == key:
            return game
        if game.get("title_cn") == key:
            return game
    raise AssertionError(f"列表中没有 key 为 {key!r} 的游戏")


def cancel_job(client, job_id: str) -> Dict[str, Any]:
    """取消任务。"""
    response = client.post(f"{API}/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    return response.json()


def set_steam_appid(client, key: str, appid: int) -> None:
    """直接给游戏写入 steam_appid（Excel 的 Steam 列是好评率，不是 appid）。"""
    store = client.app.state.store
    game, _applied = store.apply_fields(key, {"steam_appid": appid}, force=True)
    assert game is not None, f"游戏不存在: {key}"
