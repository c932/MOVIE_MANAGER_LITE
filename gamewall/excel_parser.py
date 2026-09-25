"""
Excel 游戏库解析器
解析「端游资源库」类 Excel：自动定位表头行，按表头文本映射列
"""
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import List, Tuple

from openpyxl import load_workbook

from gamewall.game_models import Game
from gamewall.name_utils import split_title

logger = logging.getLogger(__name__)


class ExcelParseError(Exception):
    pass


# 表头文本 → 字段映射（精确匹配优先，其余按包含关系兜底）
_HEADER_MATCHERS = [
    (("游戏名",), "name"),
    (("下载链接", "夸克"), "link"),
    (("大小",), "size"),
    (("版本",), "version"),
    (("更新日期",), "update_date"),
    (("发布日期",), "release_date"),
    (("ign",), "ign"),
    (("steam",), "steam"),
    (("3a",), "aaa"),
]

_SIZE_RE = re.compile(r'([\d.]+)\s*([TGMK])B?', re.IGNORECASE)
_SIZE_UNITS = {"T": 1024 ** 4, "G": 1024 ** 3, "M": 1024 ** 2, "K": 1024}
_AAA_TRUE = {"是", "3a", "3A大作", "yes", "true", "y", "1"}
_AAA_TRUE_LOWER = {text.lower() for text in _AAA_TRUE}


def _cell_text(value) -> str:
    """单元格转文本（日期→ISO 日期字符串）"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _parse_size_bytes(text: str) -> float:
    m = _SIZE_RE.search(str(text))
    if not m:
        return 0.0
    try:
        return float(m.group(1)) * _SIZE_UNITS[m.group(2).upper()]
    except (ValueError, KeyError):
        return 0.0


def _find_header_and_columns(ws) -> Tuple[int, dict]:
    """
    定位表头行并按表头文本映射列
    Returns: (表头行号, {字段名: 列号(1-based)})；必需列 name 缺失时报错
    """
    for row_idx, row in enumerate(ws.iter_rows(max_row=200, values_only=True), 1):
        for col_idx, value in enumerate(row, 1):
            text = _cell_text(value)
            if "游戏名" in text:
                columns = {}
                for col_idx2, value2 in enumerate(row, 1):
                    header = _cell_text(value2).lower()
                    if not header:
                        continue
                    for keys, field in _HEADER_MATCHERS:
                        if field in columns:
                            continue
                        if any(k.lower() in header for k in keys):
                            columns[field] = col_idx2
                            break
                if "name" in columns:
                    return row_idx, columns
                raise ExcelParseError(f"第 {row_idx} 行发现「游戏名」但缺少游戏名列表头")
    raise ExcelParseError("未找到表头行（需包含「游戏名」列）")


def parse_excel(path: str) -> Tuple[List[Game], dict]:
    """
    解析游戏库 Excel
    Returns: (游戏列表, 元信息 {header_row, path, mtime})
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ExcelParseError(f"Excel 文件不存在: {path}")

    wb = load_workbook(str(file_path), read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]

        header_row, columns = _find_header_and_columns(ws)

        games: List[Game] = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True),
                                     header_row + 1):
            def cell(field: str) -> str:
                col = columns.get(field)
                return _cell_text(row[col - 1]) if col and col <= len(row) else ""

            raw_name = cell("name")
            if not raw_name:
                continue

            title_cn, title_en = split_title(raw_name)
            game = Game(
                title_cn=title_cn,
                title_en=title_en,
                raw_name=raw_name,
                quark_link=cell("link"),
                size_text=cell("size"),
                size_bytes=_parse_size_bytes(cell("size")),
                version=cell("version"),
                update_date=cell("update_date"),
                release_date=cell("release_date"),
                excel_row=row_idx,
            )

            ign_text = cell("ign").replace("分", "")
            try:
                game.ign_score = float(ign_text)
            except ValueError:
                pass

            steam_text = cell("steam")
            # 支持 "92%" / "92" / "特别好评 92%" 三种写法
            m = re.search(r'(\d+(?:\.\d+)?)\s*%?', steam_text)
            if m and steam_text:
                try:
                    game.steam_positive_pct = float(m.group(1))
                except ValueError:
                    pass

            aaa_text = cell("aaa")
            game.aaa_excel_marked = (
                bool(aaa_text) and aaa_text.lower() in _AAA_TRUE_LOWER
            )

            games.append(game)
    finally:
        wb.close()
    logger.info(f"Excel 解析完成: {len(games)} 个游戏 (表头行 {header_row})")
    meta = {
        "header_row": header_row,
        "path": str(file_path),
        "mtime": file_path.stat().st_mtime,
    }
    return games, meta


# 差分对比字段：仅 Excel 实际维护的列（release_date/评分列由联网补全填充，
# 对比新表空值会产生假差异，故不参与）
_EXCEL_DIFF_FIELDS = ("title_cn", "title_en", "raw_name", "quark_link",
                      "size_text", "size_bytes", "version", "update_date",
                      "aaa_excel_marked")


def diff_games(old_games, new_games) -> Tuple[List[Game], list, List[Game]]:
    """
    对比当前库与新 Excel 的差异
    Returns: (新增, [(norm_key, 标题, [(字段, 旧值, 新值), ...])], 移除)
    """
    old_by_key = {}
    for g in old_games:
        old_by_key.setdefault(g.norm_key, g)
    new_by_key = {}
    for g in new_games:
        new_by_key.setdefault(g.norm_key, g)

    added = [g for k, g in new_by_key.items() if k not in old_by_key]
    removed = [g for k, g in old_by_key.items() if k not in new_by_key]
    updated = []
    for key, ng in new_by_key.items():
        og = old_by_key.get(key)
        if og is None:
            continue
        changes = []
        for f in _EXCEL_DIFF_FIELDS:
            ov, nv = getattr(og, f, None), getattr(ng, f, None)
            if ov != nv:
                changes.append((f, ov, nv))
        if changes:
            updated.append((key, ng.display_title(), changes))
    return added, updated, removed
