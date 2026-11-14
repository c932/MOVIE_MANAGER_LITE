"""
douban-cli 通用封装模块

提供与 douban-cli (@marvae24/douban-cli) 交互的统一接口：
- run_douban_cli: 底层命令调用
- search_movie: 电影搜索 + 年份匹配
- get_movie_detail: 电影详情获取
- inject_douban_to_nfo: NFO 文件豆瓣数据注入
"""
import sys
import json
import subprocess
import shutil
import logging
import xml.etree.ElementTree as ET
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


# ─────────────────── 底层调用 ───────────────────


def run_douban_cli(*args: str, timeout: int = 30) -> Optional[dict | list]:
    """调用 douban-cli 并返回解析后的 JSON，失败返回 None"""
    npx_path = shutil.which("npx") or "npx"
    cmd = [npx_path, "--yes", "@marvae24/douban-cli@0.7.0"] + list(args) + ["--json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        stdout = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        stderr = result.stderr.decode('utf-8', errors='replace') if isinstance(result.stderr, bytes) else result.stderr
        if result.returncode != 0:
            logger.warning(f"douban-cli 命令失败 ({result.returncode}): {' '.join(args)} {stderr.strip()}")
            return None
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        logger.warning(f"douban-cli 命令超时 ({timeout}s): {' '.join(args)}")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"douban-cli 命令异常: {e}")
        return None


# ─────────────────── 搜索 ───────────────────


def search_movies(keyword: str, year: str = "") -> list[dict]:
    """完整电影候选，保留暂无评分的新片；人工匹配使用该接口。"""
    results = run_douban_cli("search", keyword, timeout=20)
    if not isinstance(results, list):
        return []
    return [dict(item) for item in results if isinstance(item, dict)
            and item.get("id") and item.get("title") and item.get("type", "movie") == "movie"]


def search_movie(keyword: str, year: str = "") -> Optional[dict]:
    """兼容自动补分：只有明确且唯一的片名/年份匹配才返回结果。"""
    import math
    import re
    normalize = lambda text: re.sub(r"[\W_]+", "", str(text).casefold())
    matches = []
    for item in search_movies(keyword, year):
        try:
            score = float(item.get("rating", 0))
            if not math.isfinite(score) or not 0 < score <= 10:
                continue
            if year and (not str(item.get("year", "")).isdigit() or abs(int(item["year"]) - int(year)) > 1):
                continue
        except (TypeError, ValueError):
            continue
        names = [item.get("title", ""), item.get("original_title", "")]
        if normalize(keyword) not in [normalize(name) for name in names if name]:
            continue
        matches.append({"id": str(item["id"]), "title": item["title"],
                        "rating": item["rating"], "year": item.get("year", "")})
    unique = {item["id"]: item for item in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


# ─────────────────── 详情 ───────────────────


def get_movie_detail(douban_id: str) -> Optional[dict]:
    """
    获取电影详情（评分、导演、演员、简介等）。

    使用 douban-cli movie <id> --json

    Returns:
        完整详情 dict 或 None
    """
    return run_douban_cli("movie", douban_id, timeout=20)


# ─────────────────── NFO 注入 ───────────────────


def inject_douban_to_nfo(nfo_path: str, douban_id: str, detail: dict) -> bool:
    """旧公开接口；实际字段合并和原子写盘与工作台共用。"""
    from scraper.scrape_persistence import update_douban_nfo
    try:
        return update_douban_nfo(nfo_path, douban_id, detail)
    except (OSError, ValueError, ET.ParseError):
        logger.warning("豆瓣 NFO 更新失败，原文件保持不变")
        return False


def _save_formatted_xml(tree: ET.ElementTree, file_path: str):
    """旧内部入口也统一使用原子替换。"""
    from parsers.nfo_writer import write_tree
    write_tree(tree, file_path)


def read_nfo_movie_info(nfo_path: str) -> Optional[dict]:
    """
    从 NFO 文件读取电影基本信息（用于刮削前判断）。

    Returns:
        {"title": str, "year": str, "original_title": str, "has_douban": bool}
        或 None（解析失败）
    """
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()

        title = ""
        title_elem = root.find('title')
        if title_elem is not None and title_elem.text:
            title = title_elem.text.strip()

        year = ""
        year_elem = root.find('year')
        if year_elem is not None and year_elem.text:
            year = year_elem.text.strip()

        original_title = ""
        orig_elem = root.find('originaltitle')
        if orig_elem is not None and orig_elem.text:
            original_title = orig_elem.text.strip()

        # 检查是否已有豆瓣评分
        has_douban = False
        ratings_elem = root.find('ratings')
        if ratings_elem is not None:
            for r in ratings_elem.findall('rating'):
                if r.get('name') == 'douban':
                    value_elem = r.find('value')
                    if value_elem is not None and value_elem.text:
                        try:
                            if float(value_elem.text) > 0:
                                has_douban = True
                        except ValueError:
                            pass

        return {
            "title": title,
            "year": year,
            "original_title": original_title,
            "has_douban": has_douban,
        }
    except Exception as e:
        logger.error(f"读取 NFO 信息失败 [{nfo_path}]: {e}")
        return None


# ─────────────────── 单电影刮削 ───────────────────


def scrape_single_movie(nfo_path: str, title: str, original_title: str = "",
                        year: str = "") -> dict:
    """兼容单片/批量调用；委托统一刮削服务的豆瓣专用用例。"""
    from scraper.scrape_service import scrape_douban_movie
    return scrape_douban_movie(nfo_path, title, original_title, year)
