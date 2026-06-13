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
    cmd = [npx_path, "--yes", "@marvae24/douban-cli"] + list(args) + ["--json"]
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


def search_movie(keyword: str, year: str = "") -> Optional[dict]:
    """
    搜索电影，返回最佳匹配结果。

    使用 douban-cli search <keyword> --json
    自动筛选年份匹配（±1 年容差）。

    Returns:
        {"id": str, "title": str, "rating": str, "year": str} 或 None
    """
    results = run_douban_cli("search", keyword, timeout=20)
    if not results or not isinstance(results, list):
        return None

    # 优先返回评分 > 0 且年份匹配的结果
    for item in results:
        if not isinstance(item, dict):
            continue
        item_year = item.get("year", "")
        item_rating = item.get("rating", "0")

        # 跳过评分为 0 的结果（通常是访谈、纪录片等附属条目）
        try:
            if float(item_rating) <= 0:
                continue
        except (ValueError, TypeError):
            continue

        # 年份匹配（±1 年容差）
        if year:
            try:
                if abs(int(item_year) - int(year)) > 1:
                    continue
            except (ValueError, TypeError):
                pass  # 年份格式异常时不验证

        return {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "rating": item_rating,
            "year": item_year,
        }

    return None


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
    """
    将豆瓣数据注入 NFO 文件。

    - 写入/更新 <ratings><rating name="douban">
    - 写入 <doubanid> 元素
    - 写入 <doubanurl> 元素

    Args:
        nfo_path: NFO 文件路径
        douban_id: 豆瓣电影 ID
        detail: douban-cli movie 命令返回的详情 dict

    Returns:
        是否注入成功
    """
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()

        # 提取评分
        rating_str = detail.get("rating", "0")
        try:
            rating_value = float(rating_str)
        except (ValueError, TypeError):
            rating_value = 0.0

        if rating_value <= 0:
            logger.warning(f"豆瓣评分为 0，跳过注入: {nfo_path}")
            return False

        # === 写入/更新 ratings ===
        ratings_elem = root.find('ratings')
        if ratings_elem is None:
            ratings_elem = ET.SubElement(root, 'ratings')

        # 查找已有的 douban rating
        douban_rating = None
        for r in ratings_elem.findall('rating'):
            if r.get('name') == 'douban':
                douban_rating = r
                break

        if douban_rating is None:
            douban_rating = ET.SubElement(ratings_elem, 'rating')
            douban_rating.set('name', 'douban')
            douban_rating.set('max', '10')
            douban_rating.set('default', 'false')

        # 更新 value
        value_elem = douban_rating.find('value')
        if value_elem is None:
            value_elem = ET.SubElement(douban_rating, 'value')
        value_elem.text = str(rating_value)

        # 更新 votes（comment_count 作为投票数参考）
        votes_elem = douban_rating.find('votes')
        comment_count = detail.get("comment_count", 0)
        if comment_count:
            if votes_elem is None:
                votes_elem = ET.SubElement(douban_rating, 'votes')
            votes_elem.text = str(comment_count)

        # === 写入 doubanid ===
        doubanid_elem = root.find('doubanid')
        if doubanid_elem is None:
            doubanid_elem = ET.SubElement(root, 'doubanid')
        doubanid_elem.text = douban_id

        # === 写入 doubanurl ===
        douban_url = f"https://movie.douban.com/subject/{douban_id}/"
        doubanurl_elem = root.find('doubanurl')
        if doubanurl_elem is None:
            doubanurl_elem = ET.SubElement(root, 'doubanurl')
        doubanurl_elem.text = douban_url

        # === 保存 ===
        _save_formatted_xml(tree, nfo_path)
        logger.info(f"豆瓣数据注入成功: {nfo_path} -> {detail.get('title', '?')} ({rating_value})")
        return True

    except ET.ParseError as e:
        logger.error(f"NFO XML 解析错误 [{nfo_path}]: {e}")
        return False
    except Exception as e:
        logger.error(f"NFO 注入异常 [{nfo_path}]: {e}")
        return False


def _save_formatted_xml(tree: ET.ElementTree, file_path: str):
    """保存格式化的 XML 文件"""
    ET.indent(tree, space="  ")
    tree.write(file_path, encoding='utf-8', xml_declaration=True)


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
    """
    刮削单部电影的豆瓣评分和链接。

    多级搜索策略：中文名 → 英文原名 → 简化标题
    仅写入 NFO：评分 + doubanid + doubanurl，不修改其他数据。

    Returns:
        {"success": bool, "message": str, "rating": str, "douban_id": str}
    """
    import time

    if not title:
        return {"success": False, "message": "电影标题为空"}

    # === 多级搜索策略 ===
    search_result = search_movie(title, year)

    if not search_result and original_title and original_title != title:
        time.sleep(0.5)
        search_result = search_movie(original_title, year)

    if not search_result and (':' in title or '：' in title):
        simple_title = title.replace('：', ':').split(':')[0].strip()
        if simple_title and simple_title != title:
            time.sleep(0.5)
            search_result = search_movie(simple_title, year)

    if not search_result and original_title and (':' in original_title or '：' in original_title):
        simple_original = original_title.replace('：', ':').split(':')[0].strip()
        if simple_original and simple_original != original_title:
            time.sleep(0.5)
            search_result = search_movie(simple_original, year)

    if not search_result:
        return {"success": False, "message": f"未找到豆瓣结果: {title} ({year})"}

    douban_id = search_result['id']
    matched_title = search_result.get('title', '')

    # === 获取详情 ===
    time.sleep(0.5)
    detail = get_movie_detail(douban_id)
    if not detail:
        return {"success": False, "message": f"获取详情失败: {matched_title}"}

    # === 注入 NFO（仅评分 + 链接） ===
    if inject_douban_to_nfo(nfo_path, douban_id, detail):
        rating_str = detail.get('rating', '?')
        return {
            "success": True,
            "message": f"成功: {matched_title} - {rating_str}/10",
            "rating": rating_str,
            "douban_id": douban_id,
        }
    else:
        return {"success": False, "message": "NFO 写入失败"}
