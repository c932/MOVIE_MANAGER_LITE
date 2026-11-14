"""无 Qt 的字段合并、海报校验、冲突检测与可恢复提交。"""
from __future__ import annotations

import hashlib
import io
import math
import re
import threading
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from parsers.nfo_writer import _atomic_write, apply_fields
from scraper.scrape_models import ScrapeDraft, ScrapeError

_LOCK = threading.RLock()
SOURCES = {"tmdb", "imdb", "douban"}
IDENTITY_TAGS = {"title", "originaltitle", "year", "premiered", "plot", "outline", "tagline", "runtime", "genre", "country", "director", "actor", "set", "thumb", "fanart", "id", "tmdbid", "tmdbId", "doubanid", "doubanurl", "url"}


def fingerprint(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def poster_path(draft: ScrapeDraft) -> Path:
    return draft.target.video_path.with_name(draft.target.video_path.stem + "-poster.jpg")


def snapshot_files(draft: ScrapeDraft) -> None:
    draft.expected_files = {str(p): fingerprint(p) for p in (draft.target.nfo_path, poster_path(draft))}


def validate_score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScrapeError("评分必须是 0–10 的有效数字") from exc
    if not math.isfinite(number) or not 0 <= number <= 10:
        raise ScrapeError("评分必须是 0–10 的有效数字")
    return number


def _xml(path: Path) -> ET.Element:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ScrapeError("原 NFO 损坏或无法读取，请先修复再保存") from exc
    if root.tag != "movie":
        raise ScrapeError("原 NFO 根元素不是 movie，请先修复")
    return root


def read_ids(root: ET.Element) -> dict[str, str]:
    result = {e.get("type", "").lower(): (e.text or "").strip() for e in root.findall("uniqueid")}
    result["imdb"] = result.get("imdb") or root.findtext("id", "").strip()
    result["tmdb"] = result.get("tmdb") or root.findtext("tmdbid", "").strip() or root.findtext("tmdbId", "").strip()
    douban = root.findtext("doubanid", "").strip()
    if not douban:
        match = re.search(r"douban\.com/subject/(\d+)", root.findtext("doubanurl", "") or root.findtext("url", ""))
        douban = match.group(1) if match else ""
    result["douban"] = result.get("douban") or douban
    return {key: val for key, val in result.items() if key and val}


def _filtered_fields(root: ET.Element, fields: dict, overwrite: bool) -> dict:
    if overwrite:
        return fields
    tags = {"original_title": "originaltitle", "genres": "genre", "countries": "country", "directors": "director", "actors": "actor", "set_name": "set"}
    result = {}
    for key, value in fields.items():
        if key == "ratings":
            present = {e.get("name", "").lower() for e in root.findall("ratings/rating") if e.findtext("value", "").strip()}
            result[key] = {s: v for s, v in value.items() if s not in present}
        elif key == "uniqueids":
            present = read_ids(root)
            result[key] = {s: v for s, v in value.items() if s not in present}
        else:
            elems = root.findall(tags.get(key, key))
            if not elems or not any("".join(e.itertext()).strip() for e in elems):
                result[key] = value
    return result


def sync_ids(root: ET.Element, ids: dict) -> None:
    for source, value in ids.items():
        legacy = {"douban": ("doubanid", "doubanurl"), "imdb": ("id",), "tmdb": ("tmdbid", "tmdbId")}.get(source, ())
        for tag in legacy:
            if source != "douban" and root.find(tag) is None:
                continue
            elem = root.find(tag)
            if elem is None:
                elem = ET.SubElement(root, tag)
            elem.text = f"https://movie.douban.com/subject/{value}/" if tag == "doubanurl" else str(value)
        if source == "douban":
            elem = root.find("url")
            if elem is not None and "douban.com/subject/" in (elem.text or ""):
                elem.text = f"https://movie.douban.com/subject/{value}/"


def jpeg_bytes(data: bytes) -> bytes:
    if not data or len(data) > 15 * 1024 * 1024:
        raise ScrapeError("海报为空或超过 15 MB，请重新选择")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > 40_000_000:
                raise ScrapeError("海报像素过大，请选择较小尺寸")
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            result = io.BytesIO()
            img.convert("RGB").save(result, format="JPEG", quality=94)
            return result.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ScrapeError("下载内容不是有效海报图片，请重新选择") from exc


def _set_poster(root: ET.Element, filename: str) -> None:
    for elem in list(root.findall("thumb")):
        if elem.get("aspect", "poster") == "poster":
            root.remove(elem)
    ET.SubElement(root, "thumb", {"aspect": "poster"}).text = filename


def commit_draft(draft: ScrapeDraft, selected_fields: set[str] | None = None,
                 overwrite: bool = False, metadata_only: bool = False,
                 poster_bytes: bytes | None = None) -> Movie:
    if not draft.confirmed:
        raise ScrapeError("请先确认电影匹配，再保存")
    if draft.target.error:
        raise ScrapeError(draft.target.error)
    if not draft.target.video_path.is_file():
        raise ScrapeError("视频文件不存在或暂时无法访问")
    if not metadata_only and poster_bytes is None:
        raise ScrapeError("请先选择海报，或明确选择仅保存元数据")
    data = jpeg_bytes(poster_bytes) if poster_bytes is not None else None
    fields = {k: v for k, v in draft.fields.items() if (selected_fields is None or k in selected_fields) and v not in (None, "", [], {})}
    if "ratings" in fields:
        fields["ratings"] = {s: validate_score(v) for s, v in fields["ratings"].items() if s in SOURCES}
    with _LOCK:
        if not draft.expected_files:
            raise ScrapeError("草稿缺少磁盘快照，请重新加载电影")
        for filename, expected in draft.expected_files.items():
            if fingerprint(Path(filename)) != expected:
                raise ScrapeError("文件已被其他应用改变，存在保存冲突，请重新加载")
        path = draft.target.nfo_path
        root = _xml(path) if path.exists() else ET.Element("movie")
        is_new = not path.exists()
        if draft.replace_identity:
            for child in list(root):
                if child.tag in IDENTITY_TAGS or (child.tag == "uniqueid" and child.get("type", "").lower() in SOURCES):
                    root.remove(child)
            for child in list(root.findall("ratings/rating")):
                if child.get("name", "").lower() in SOURCES | {"themoviedb"}:
                    root.find("ratings").remove(child)
        if "tmdb" in fields.get("ratings", {}):
            for alias in list(root.findall("ratings/rating[@name='themoviedb']")):
                canonical = root.find("ratings/rating[@name='tmdb']")
                if canonical is not None:
                    root.find("ratings").remove(alias)
                else:
                    alias.set("name", "tmdb")
        old_poster = NFOParser._local_artwork(root, path.parent, "poster", poster_path(draft), path.parent / "poster.jpg")
        if data is not None and (selected_fields is not None and "poster" not in selected_fields or old_poster and not overwrite and not draft.replace_identity):
            data = None
        fields = _filtered_fields(root, fields, overwrite or draft.replace_identity)
        apply_fields(root, fields)
        sync_ids(root, fields.get("uniqueids", {}))
        for source in fields.get("ratings", {}):
            rating = root.find(f"ratings/rating[@name='{source}']")
            if rating is None:
                continue
            for elem in list(rating.findall("votes")):
                rating.remove(elem)
            count = draft.votes.get(source)
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                ET.SubElement(rating, "votes").text = str(count)
        if not root.findtext("title", "").strip():
            raise ScrapeError("电影标题不能为空，请选择标题字段")
        if data is not None:
            _set_poster(root, poster_path(draft).name)
        elif is_new or draft.replace_identity:
            _set_poster(root, "")
        if is_new or draft.replace_identity:
            ET.SubElement(root, "fanart").text = ""
        ET.indent(root, space="  ")
        assets = [(poster_path(draft), data)] if data is not None else []
        assets.append((path, ET.tostring(root, encoding="utf-8", xml_declaration=True)))
        old = {p: p.read_bytes() if p.exists() else None for p, _ in assets}
        changed: list[Path] = []
        try:
            for p, original in old.items():
                if original is not None:
                    backup = p.with_name(p.name + ".mml-backup-" + uuid.uuid4().hex[:12])
                    _atomic_write(backup, original)
            for filename, expected in draft.expected_files.items():
                if fingerprint(Path(filename)) != expected:
                    raise ScrapeError("保存准备期间文件发生改变，请重新加载")
            for p, content in assets:
                _atomic_write(p, content)
                changed.append(p)
        except Exception as exc:
            failed = []
            for p in reversed(changed):
                try:
                    if old[p] is None:
                        p.unlink(missing_ok=True)
                    else:
                        _atomic_write(p, old[p])
                except OSError:
                    failed.append(str(p))
            message = "保存失败，已恢复原文件"
            if failed:
                message = "保存失败，部分文件未能恢复，请使用同目录 .mml-backup 备份恢复：" + "、".join(failed)
            raise ScrapeError(message) from exc
        movie = NFOParser.parse(str(path), include_user_rating=True)
        if movie is None or not movie.video_path:
            raise ScrapeError("NFO 已保存，但重新读取失败，请重新扫描")
        draft.target.existing = True
        stat = path.stat()
        draft.target.nfo_stamp = (stat.st_mtime_ns, stat.st_size)
        snapshot_files(draft)
        return movie


def update_douban_nfo(nfo_path: str, douban_id: str, detail: dict, *, expected_fingerprint: str | None = None) -> bool:
    if not re.fullmatch(r"\d+", str(douban_id)):
        raise ScrapeError("豆瓣 ID 无效")
    score = validate_score(detail.get("rating"))
    if score <= 0:
        return False
    with _LOCK:
        path = Path(nfo_path)
        before = fingerprint(path)
        if expected_fingerprint is not None and before != expected_fingerprint:
            raise ScrapeError("NFO 在豆瓣请求期间已改变，请重新加载")
        root = _xml(path)
        apply_fields(root, {"ratings": {"douban": score}, "uniqueids": {"douban": str(douban_id)}})
        sync_ids(root, {"douban": str(douban_id)})
        rating = root.find("ratings/rating[@name='douban']")
        for elem in list(rating.findall("votes")):
            rating.remove(elem)
        try:
            count = int(str(detail.get("rating_count")).replace(",", ""))
            if count > 0:
                ET.SubElement(rating, "votes").text = str(count)
        except (TypeError, ValueError):
            pass
        ET.indent(root, space="  ")
        if fingerprint(path) != before:
            raise ScrapeError("NFO 已被其他应用改变，请重试")
        _atomic_write(path, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        return True
