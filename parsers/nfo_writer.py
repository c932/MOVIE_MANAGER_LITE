"""
NFO 结构化写入器（纯 Python，无 Qt 依赖）。

网页版 API 使用：
- PUT /movies/{id}/nfo   → write_xml()
- PUT /movies/{id}/fields → write_fields()

写入语义与桌面版 `ui/nfo_editor_dialog.py` 的保存逻辑等价（本文件为独立复刻，
桌面版对话框不做任何改动）。原则：**只写调用方明确提交的字段**，
未提交的键一律不动；所有写盘均为「临时文件 + os.replace」原子替换，
失败时原文件保持原样。
"""
from __future__ import annotations

import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# 契约 2.3 允许提交的顶层键（顺序即写入顺序，保证输出稳定）
FIELD_KEYS: Sequence[str] = (
    "title",
    "original_title",
    "year",
    "premiered",
    "plot",
    "tagline",
    "runtime",
    "genres",
    "countries",
    "tags",
    "set_name",
    "ratings",
    "directors",
    "actors",
    "uniqueids",
    "fileinfo",
)

# 标量字段 → NFO 元素名（与 parsers/nfo_parser.py 的解析保持一致）
_SCALAR_TAGS: Dict[str, str] = {
    "title": "title",
    "original_title": "originaltitle",
    "year": "year",
    "premiered": "premiered",
    "plot": "plot",
    "tagline": "tagline",
    "runtime": "runtime",
}

# 多值字段 → NFO 元素名（tags 写 <custom>，与解析器「只读 custom 作标签」对应）
_MULTI_TAGS: Dict[str, str] = {
    "genres": "genre",
    "countries": "country",
    "tags": "custom",
    "directors": "director",
}

# resolution → (width, height)：解析器由 width/height 反推分辨率等级
_RESOLUTION_SIZE: Dict[str, tuple] = {
    "4k": (3840, 2160),
    "2160p": (3840, 2160),
    "1080p": (1920, 1080),
    "fhd": (1920, 1080),
    "720p": (1280, 720),
    "sd": (640, 480),
    "480p": (640, 480),
}

_FILEINFO_KEYS = ("resolution", "hdr_type", "video_codec", "audio_codec")


class NFOWriteError(ValueError):
    """NFO 写入参数非法（路由层转成 400）。"""


# ─────────────────── 基础工具 ───────────────────


def parse_xml_text(xml_text: str) -> ET.Element:
    """校验一段 XML 文本可解析且根元素为 <movie>，返回根元素。"""
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise NFOWriteError("NFO 内容为空")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NFOWriteError(f"NFO XML 无法解析: {exc}") from exc
    if root.tag != "movie":
        raise NFOWriteError("NFO 根元素必须是 <movie>")
    return root


def _atomic_write(path: Path, data: bytes) -> None:
    """临时文件 + os.replace 原子写盘（失败时原文件保持不变）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_xml(nfo_path: str, xml_text: str) -> None:
    """校验后把原始 XML 文本原子写入 NFO 文件。"""
    parse_xml_text(xml_text)
    _atomic_write(Path(nfo_path), xml_text.encode("utf-8"))


def write_tree(tree: ET.ElementTree, nfo_path: str) -> None:
    """格式化并原子写入 XML 树。"""
    ET.indent(tree, space="  ")
    data = ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)
    _atomic_write(Path(nfo_path), data)


# ─────────────────── 字段写入 ───────────────────


def _set_text(root: ET.Element, tag: str, value: Any) -> None:
    """更新或创建元素文本；空值清空文本（元素保留）。"""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise NFOWriteError(f"字段 {tag} 需要字符串")
    elem = root.find(tag)
    if elem is None:
        elem = ET.SubElement(root, tag)
    elem.text = value


def _replace_multi(root: ET.Element, tag: str, values: Any) -> None:
    """删除同名元素后按新值重建（多值字段）。"""
    if not isinstance(values, (list, tuple)):
        raise NFOWriteError(f"字段 {tag} 需要数组")
    for elem in list(root.findall(tag)):
        root.remove(elem)
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        elem = ET.SubElement(root, tag)
        elem.text = text


def _handle_set_name(root: ET.Element, value: Any) -> None:
    """系列名写入 <set><name>（解析器同时兼容 <set>纯文本 格式）。"""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise NFOWriteError("字段 set_name 需要字符串")
    set_elem = root.find("set")
    if set_elem is None:
        set_elem = ET.SubElement(root, "set")
    name_elem = set_elem.find("name")
    if name_elem is None:
        name_elem = ET.SubElement(set_elem, "name")
    name_elem.text = value


def _handle_ratings(root: ET.Element, value: Any) -> None:
    """按 {source: value} 写入 <ratings><rating name=…>，未提交的来源不动。"""
    if not isinstance(value, Mapping):
        raise NFOWriteError("字段 ratings 需要对象")
    ratings_elem = root.find("ratings")
    if ratings_elem is None:
        ratings_elem = ET.SubElement(root, "ratings")
    for source, score in value.items():
        name = str(source).strip().lower()
        if not name:
            continue
        rating_elem = None
        for candidate in ratings_elem.findall("rating"):
            if (candidate.get("name") or "").lower() == name:
                rating_elem = candidate
                break
        if score is None:
            if rating_elem is not None:
                ratings_elem.remove(rating_elem)
            continue
        try:
            score_value = float(score)
        except (TypeError, ValueError) as exc:
            raise NFOWriteError(f"评分 {source} 数值非法: {score!r}") from exc
        if rating_elem is None:
            rating_elem = ET.SubElement(ratings_elem, "rating")
            rating_elem.set("name", name)
            rating_elem.set("max", "10")
        value_elem = rating_elem.find("value")
        if value_elem is None:
            value_elem = ET.SubElement(rating_elem, "value")
        # 保留整数观感：8.5 → "8.5"，8.0 → "8"
        value_elem.text = str(int(score_value)) if score_value == int(score_value) else str(score_value)


def _handle_actors(root: ET.Element, value: Any) -> None:
    """整体替换 <actor> 列表。"""
    if not isinstance(value, (list, tuple)):
        raise NFOWriteError("字段 actors 需要数组")
    for elem in list(root.findall("actor")):
        root.remove(elem)
    for item in value:
        if not isinstance(item, Mapping):
            raise NFOWriteError("actors 的元素需要对象 {name, role, thumb}")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        actor_elem = ET.SubElement(root, "actor")
        for tag, key in (("name", "name"), ("role", "role"), ("thumb", "thumb")):
            text = str(item.get(key) or "")
            child = ET.SubElement(actor_elem, tag)
            child.text = text
        # 去掉空的 role/thumb，保持与常见 NFO 结构一致
        for child in list(actor_elem):
            if child.tag != "name" and not (child.text or "").strip():
                actor_elem.remove(child)


def _handle_uniqueids(root: ET.Element, value: Any) -> None:
    """按 {type: id} 写入 <uniqueid type=…>；imdb 同步 <id>。"""
    if not isinstance(value, Mapping):
        raise NFOWriteError("字段 uniqueids 需要对象")
    for id_type, id_value in value.items():
        key = str(id_type).strip().lower()
        if not key:
            continue
        text = "" if id_value is None else str(id_value).strip()
        uniqueid = None
        for candidate in root.findall("uniqueid"):
            if (candidate.get("type") or "").lower() == key:
                uniqueid = candidate
                break
        if uniqueid is None:
            uniqueid = ET.SubElement(root, "uniqueid")
            uniqueid.set("type", key)
            uniqueid.set("default", "true" if key == "imdb" else "false")
        uniqueid.text = text
        if key == "imdb" and text and root.find("id") is not None:
            # 旧格式 <id> 存在时保持同步，避免解析器读到过期值
            id_elem = root.find("id")
            if id_elem is not None:
                id_elem.text = text


def _ensure(root: ET.Element, path: Sequence[str]) -> ET.Element:
    """确保多级父元素存在并返回最深层元素。"""
    parent = root
    for tag in path:
        child = parent.find(tag)
        if child is None:
            child = ET.SubElement(parent, tag)
        parent = child
    return parent


def _set_or_clear(parent: ET.Element, tag: str, value: Any, *, remove_when_empty: bool = True) -> None:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise NFOWriteError(f"fileinfo.{tag} 需要字符串")
    elem = parent.find(tag)
    if value == "":
        if elem is not None and remove_when_empty:
            parent.remove(elem)
        return
    if elem is None:
        elem = ET.SubElement(parent, tag)
    elem.text = value


def _handle_fileinfo(root: ET.Element, value: Any) -> None:
    """写入 fileinfo/streamdetails 的技术参数（分辨率由 width/height 反推）。"""
    if not isinstance(value, Mapping):
        raise NFOWriteError("字段 fileinfo 需要对象")
    unknown = [k for k in value if k not in _FILEINFO_KEYS]
    if unknown:
        raise NFOWriteError(f"fileinfo 不支持的字段: {', '.join(sorted(unknown))}")

    needs_video = any(value.get(k) for k in ("resolution", "hdr_type", "video_codec"))
    needs_audio = bool(value.get("audio_codec"))
    if not needs_video and not needs_audio and not value:
        return

    video = audio = None
    if needs_video:
        video = _ensure(root, ("fileinfo", "streamdetails", "video"))
    if needs_audio:
        stream = _ensure(root, ("fileinfo", "streamdetails"))
        audio = stream.find("audio")
        if audio is None:
            audio = ET.SubElement(stream, "audio")

    if "resolution" in value:
        resolution = str(value.get("resolution") or "").strip()
        if resolution:
            size = _RESOLUTION_SIZE.get(resolution.lower())
            if size is None:
                raise NFOWriteError(
                    f"不支持的分辨率 {resolution!r}，可用值: {', '.join(sorted(set(_RESOLUTION_SIZE)))}"
                )
            for tag, number in (("width", size[0]), ("height", size[1])):
                elem = video.find(tag)
                if elem is None:
                    elem = ET.SubElement(video, tag)
                elem.text = str(number)
    if "hdr_type" in value:
        _set_or_clear(video, "hdrtype", value.get("hdr_type"))
    if "video_codec" in value:
        _set_or_clear(video, "codec", value.get("video_codec"))
    if "audio_codec" in value:
        _set_or_clear(audio, "codec", value.get("audio_codec"))


_HANDLERS = {
    "set_name": _handle_set_name,
    "ratings": _handle_ratings,
    "actors": _handle_actors,
    "uniqueids": _handle_uniqueids,
    "fileinfo": _handle_fileinfo,
}
for _key, _tag in _SCALAR_TAGS.items():
    _HANDLERS[_key] = lambda root, value, tag=_tag: _set_text(root, tag, value)
for _key, _tag in _MULTI_TAGS.items():
    _HANDLERS[_key] = lambda root, value, tag=_tag: _replace_multi(root, tag, value)


def apply_fields(root: ET.Element, fields: Mapping[str, Any]) -> None:
    """把契约 2.3 的结构化字段就地写入 XML 树（仅处理提交的键）。"""
    unknown = [k for k in fields if k not in FIELD_KEYS]
    if unknown:
        raise NFOWriteError(f"不支持的字段: {', '.join(sorted(unknown))}")
    for key in FIELD_KEYS:
        if key not in fields:
            continue
        handler = _HANDLERS.get(key)
        if handler is None:  # pragma: no cover - FIELD_KEYS 与 HANDLERS 同步维护
            raise NFOWriteError(f"字段 {key} 未实现")
        handler(root, fields[key])


def write_fields(nfo_path: str, fields: Mapping[str, Any]) -> None:
    """把结构化字段写入 NFO 文件（先解析 → 修改 → 原子写回）。"""
    path = Path(nfo_path)
    if not path.is_file():
        raise NFOWriteError(f"NFO 文件不存在: {nfo_path}")
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as exc:
        raise NFOWriteError(f"原 NFO 无法解析: {exc}") from exc
    apply_fields(tree.getroot(), fields)
    write_tree(tree, nfo_path)
    logger.info("NFO 结构化字段已写入: %s (%s)", nfo_path, ", ".join(sorted(fields)))
