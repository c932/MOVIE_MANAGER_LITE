"""
SteamGridDB 竖版海报搜索与下载

通过 SteamGridDB v2 API 搜索游戏的竖版封面（600×900），
下载到本地 DATA_DIR/posters/ 目录。
"""
import logging
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from utils.app_paths import DATA_DIR

logger = logging.getLogger(__name__)

SGDB_BASE = "https://www.steamgriddb.com/api/v2"
SGDB_TIMEOUT = 10
SGDB_DOWNLOAD_TIMEOUT = 12

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalGameWall/1.0"


def _sgdb_get(url: str, api_key: str) -> tuple:
    """GET SteamGridDB API，返回 (data, err)。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Authorization": f"Bearer {api_key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=SGDB_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        logger.warning(f"SteamGridDB HTTP {e.code}: {e.reason}")
        return None, f"HTTP {e.code}"
    except Exception as e:
        logger.warning(f"SteamGridDB 请求失败: {e}")
        return None, str(e)


def search_game(name: str, api_key: str) -> tuple:
    """按游戏名搜索 SteamGridDB，返回 (game_id, err)。"""
    url = f"{SGDB_BASE}/search/autocomplete/{urllib.parse.quote(name)}"
    data, err = _sgdb_get(url, api_key)
    if err:
        return 0, err
    items = (data or {}).get("data") or []
    if not items:
        return 0, "未找到匹配游戏"
    return items[0].get("id", 0), ""


def get_vertical_grids(game_id: int, api_key: str) -> tuple:
    """获取游戏的 600×900 竖版封面列表，返回 (grids, err)。"""
    url = f"{SGDB_BASE}/grids/game/{game_id}?dimensions=600x900"
    data, err = _sgdb_get(url, api_key)
    if err:
        return [], err
    items = (data or {}).get("data") or []
    grids = []
    for it in items:
        url = it.get("url", "")
        author = it.get("author") or {}
        grids.append({
            "id": it.get("id"),
            "url": url,
            "thumb": it.get("thumb", "") or url,
            "author": author.get("name", ""),
            "style": it.get("style", ""),
            "score": int(it.get("score", 0)),
        })
    # 按评分降序
    grids.sort(key=lambda g: g["score"], reverse=True)
    return grids, ""


def search_grids(game_name: str, api_key: str) -> tuple:
    """一站式：搜索游戏 → 获取竖版封面列表，返回 (grids, err)。"""
    game_id, err = search_game(game_name, api_key)
    if err:
        return [], err
    if not game_id:
        return [], f"未找到游戏：{game_name}"
    return get_vertical_grids(game_id, api_key)


def search_grids_best(names: list, api_key: str) -> tuple:
    """按多个候选名依次搜索（英文名优先），首个命中即返回。"""
    last_err = ""
    for name in names:
        if not name:
            continue
        grids, err = search_grids(name, api_key)
        if grids:
            return grids, ""
        if err:
            last_err = err
    return [], last_err or "未找到竖版海报"


def download_poster_bytes(grid_url: str, api_key: str,
                          timeout: float = SGDB_DOWNLOAD_TIMEOUT) -> bytes:
    """下载海报图片字节（供缩略图等直接使用）。"""
    req = urllib.request.Request(grid_url, headers={
        "User-Agent": UA,
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_poster(grid_url: str, save_path: str, api_key: str,
                    timeout: float = SGDB_DOWNLOAD_TIMEOUT) -> str:
    """下载海报图片到本地路径，返回 err（成功时为空串）。"""
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img_bytes = download_poster_bytes(grid_url, api_key, timeout)
        with open(save_path, "wb") as f:
            f.write(img_bytes)
        return ""
    except Exception as e:
        logger.warning(f"海报下载失败: {e}")
        return str(e)


def fetch_and_download_poster(names: list, api_key: str, save_path: str) -> str:
    """搜索并下载评分最高的竖版海报到本地，返回 err（成功为空串）。"""
    grids, err = search_grids_best(names, api_key)
    if not grids:
        return err or "未找到竖版海报"
    return download_poster(grids[0]["url"], save_path, api_key)


def get_custom_poster_path(norm_key: str) -> str:
    """返回 custom_poster 本地存储路径。"""
    posters_dir = os.path.join(str(DATA_DIR), "posters")
    return os.path.join(posters_dir, f"{norm_key}_custom.jpg")