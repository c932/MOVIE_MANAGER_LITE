"""统一刮削用例；Qt 和旧豆瓣门面均调用此层。"""
from __future__ import annotations

import copy
import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from scraper.scrape_models import (
    Candidate, Metadata, ScrapeDraft, ScrapeError, VideoTarget,
    can_rebuild_nfo, capture_target_version, validate_target_version,
)
from scraper.scrape_persistence import commit_draft, ensure_writable_file, fingerprint, poster_path, read_ids, snapshot_files, update_douban_nfo, validate_score, _normalize_tmdb_rating
from scraper.scrape_settings import ScrapeSettings


class ScrapeService:
    def __init__(self, settings: ScrapeSettings | None = None) -> None:
        self.settings = settings or ScrapeSettings.load()
        self._providers: dict = {}

    def _provider(self, source: str):
        from scraper.metadata_sources import DoubanProvider, TmdbProvider
        if source not in {"tmdb", "douban"}:
            raise ScrapeError("请选择 TMDB 或豆瓣作为搜索来源")
        if source not in self._providers:
            self._providers[source] = (TmdbProvider if source == "tmdb" else DoubanProvider)(self.settings)
        return self._providers[source]

    def search(self, source: str, query: str, year: str = "", page: int = 1) -> list[Candidate]:
        if not query.strip():
            raise ScrapeError("请输入片名、来源 ID 或电影链接")
        return self._provider(source).search(query.strip(), year, page)

    def details(self, candidate: Candidate) -> Metadata:
        return self._provider(candidate.source).details(candidate)

    def enrich_metadata(self, metadata: Metadata) -> Metadata:
        from .rating_enrichment import enrich_ratings
        return enrich_ratings(metadata, self.settings)

    def automatic_tmdb_metadata(self, metadata: Metadata) -> list[Metadata]:
        """豆瓣资料无 TMDB 关联时，仅自动采用唯一精确同名同年候选。"""
        if (metadata.source != "douban" or "tmdb" in metadata.ids or "tmdb" in metadata.ratings
                or not (self.settings.tmdb_api_key or self.settings.tmdb_token)):
            return []
        title = re.sub(r"[\W_]+", "", str(metadata.fields.get("title", "")).casefold())
        original = re.sub(r"[\W_]+", "", str(metadata.fields.get("original_title", "")).casefold())
        year = str(metadata.fields.get("year", "")).strip()
        expected = {title, original} - {""}
        if not expected or not year:
            return []
        try:
            candidates = self.search("tmdb", metadata.fields.get("original_title") or metadata.fields.get("title", ""), year)
            exact = []
            for candidate in candidates:
                names = {re.sub(r"[\W_]+", "", str(candidate.title).casefold()),
                         re.sub(r"[\W_]+", "", str(candidate.original_title).casefold())} - {""}
                if candidate.media_type == "movie" and candidate.year == year and names & expected:
                    exact.append(candidate)
            if len(exact) != 1:
                return []
            tmdb = self.enrich_metadata(self.details(exact[0]))
            if tmdb.ids.get("tmdb"):
                return [tmdb]
        except (ScrapeError, OSError, ValueError) as exc:
            metadata.warnings.append("TMDB 自动关联未完成：" + str(exc))
        return []

    def build_draft(self, target: VideoTarget, metadata: Sequence[Metadata], plot_source: str = "tmdb") -> ScrapeDraft:
        if not metadata:
            raise ScrapeError("请先选择并获取电影详情")
        readonly_unreadable = target.error_kind == "unreadable"
        target = copy.copy(target) if readonly_unreadable else capture_target_version(target)
        draft = ScrapeDraft(target)
        if not readonly_unreadable:
            snapshot_files(draft)
            if draft.expected_files[str(target.nfo_path)] != target.nfo_fingerprint:
                raise ScrapeError("NFO 在生成草稿时已改变，请重新加载")
        if target.error or target.error_kind:
            reason = target.error_detail or target.error or "原 NFO 状态异常"
            if can_rebuild_nfo(target):
                draft.warnings.append(reason + "；可显式选择备份原 NFO 并重建，确认电影匹配后才能保存")
            else:
                draft.warnings.append(reason + "；当前仅供预览，请先解决原文件读取或路径问题再保存")
        by_source = {m.source: m for m in metadata}
        identifiers: dict[str, str] = {}
        ratings = {}
        # TMDB 作为基础资料优先，豆瓣仅补缺；简介单独按用户指定来源选择。
        ordered = sorted(by_source.values(), key=lambda m: 0 if m.source == "tmdb" else 1)
        for item in ordered:
            for key, value in item.fields.items():
                if key not in {"ratings", "uniqueids", "tags", "fileinfo"} and value not in (None, "", [], {}):
                    draft.fields.setdefault(key, copy.deepcopy(value))
            for source, value in {**item.ids, item.source: item.id}.items():
                if value and source in {"tmdb", "imdb", "douban"}:
                    if source in identifiers and identifiers[source] != str(value):
                        raise ScrapeError("两站结果指向不同电影，来源 ID 冲突，请重新匹配")
                    identifiers[source] = str(value)
            for source, value in item.ratings.items():
                if source in {"tmdb", "imdb", "douban"}:
                    ratings[source] = validate_score(value)
            draft.votes.update(item.votes)
            draft.artwork.extend(item.artwork)
            draft.warnings.extend(item.warnings)
        selected_plot = by_source.get(plot_source)
        if selected_plot and selected_plot.fields.get("plot"):
            draft.fields["plot"] = selected_plot.fields["plot"]
        elif draft.fields.get("plot"):
            actual = next((m.source for m in ordered if m.fields.get("plot")), "")
            draft.warnings.append(f"{plot_source} 简介缺失，当前预览采用 {actual} 简介")
        if identifiers:
            draft.fields["uniqueids"] = identifiers
        if ratings:
            draft.fields["ratings"] = ratings
        # 人工补充另一个来源后，不再显示已经解决的“缺少关联 / 未取得评分”提示。
        resolved = []
        if identifiers.get("imdb"):
            resolved.extend(("缺少可核验的 IMDb ID", "跨站评分关联未完成："))
        for source, label in (("tmdb", "TMDB"), ("imdb", "IMDb")):
            if source in ratings:
                resolved.append(label + " 评分未取得：")
        draft.warnings = [warning for warning in draft.warnings if not any(warning.startswith(prefix) for prefix in resolved)]
        draft.poster = draft.artwork[0] if draft.artwork else None
        if target.nfo_path.exists() and not (target.error or target.error_kind):
            try:
                content = target.nfo_path.read_bytes()
                if hashlib.sha256(content).hexdigest() != draft.expected_files[str(target.nfo_path)]:
                    raise ScrapeError("NFO 在生成草稿时已改变，请重新加载")
                root = ET.fromstring(content)
                if root.tag != "movie":
                    raise ET.ParseError("非电影 NFO")
            except (ET.ParseError, OSError, LookupError) as exc:
                raise ScrapeError("原 NFO 损坏，请先修复再保存") from exc
            old_ids = read_ids(root)
            common = set(old_ids) & set(identifiers)
            draft.replace_identity = any(old_ids[s] != identifiers[s] for s in common)
            if not common and root.findtext("title", "").strip() and draft.fields.get("title"):
                normalize = lambda value: re.sub(r'[\W_]+', '', str(value or '').casefold())
                old_names = {normalize(root.findtext('title')), normalize(root.findtext('originaltitle'))} - {''}
                new_names = {normalize(draft.fields.get('title')), normalize(draft.fields.get('original_title'))} - {''}
                title_changed = not bool(old_names & new_names)
                old_year, new_year = root.findtext("year", "").strip(), str(draft.fields.get("year", "")).strip()
                draft.replace_identity = title_changed or bool(old_year and new_year and old_year != new_year)
            if draft.replace_identity:
                draft.warnings.append("电影身份发生变化：保存将替换旧片名、简介、演职员、站点 ID、外部评分和图片关联；保留用户评分、标签及观看收藏状态")
            else:
                # 相同电影的来源选择只决定本次资料来源，不应让其他站评分从预览消失。
                normalized = copy.deepcopy(root)
                _normalize_tmdb_rating(normalized)
                previous = (NFOParser._extract_rating(normalized) or {}).get('all_ratings', {})
                for source in {'tmdb', 'imdb', 'douban'}:
                    if source not in ratings and source in previous:
                        try:
                            score = validate_score(previous[source])
                        except ScrapeError:
                            continue
                        if score > 0:
                            ratings[source] = score
                            count = normalized.findtext(f"ratings/rating[@name='{source}']/votes")
                            if count is not None and count.strip().isdigit():
                                draft.votes.setdefault(source, int(count))
                for source, identity in old_ids.items():
                    if source in {'tmdb', 'imdb', 'douban'} and identity:
                        identifiers.setdefault(source, identity)
                if ratings:
                    draft.fields['ratings'] = ratings
                if identifiers:
                    draft.fields['uniqueids'] = identifiers
        if any(fingerprint(Path(path)) != expected for path, expected in draft.expected_files.items()):
            raise ScrapeError("文件在生成草稿时已改变，请重新加载")
        if not readonly_unreadable:
            validate_target_version(target)
        return draft

    def automatic_douban_metadata(self, metadata: Metadata) -> list[Metadata]:
        """按已有豆瓣 ID 或唯一同名同年候选补分；歧义不能自动绑定。"""
        if metadata.source != 'tmdb' or metadata.ratings.get('douban'):
            return []
        normalize = lambda value: re.sub(r'[\W_]+', '', str(value or '').casefold())
        names = {normalize(metadata.fields.get('title')), normalize(metadata.fields.get('original_title'))} - {''}
        year = str(metadata.fields.get('year') or '').strip()
        identity = str(metadata.ids.get('douban') or '')
        try:
            if identity and re.fullmatch(r'\d+', identity):
                selected = Candidate('douban', identity, str(metadata.fields.get('title') or ''))
            else:
                if not names or not year:
                    metadata.warnings.append('豆瓣自动关联未完成：缺少片名或年份，请手动匹配豆瓣候选')
                    return []
                selected = None
                for query in dict.fromkeys(str(metadata.fields.get(key) or '') for key in ('title', 'original_title')):
                    if not query:
                        continue
                    candidates = self.search('douban', query, year)
                    exact = {candidate.id: candidate for candidate in candidates if candidate.source == 'douban'
                             and candidate.media_type == 'movie' and candidate.year == year
                             and names & ({normalize(candidate.title), normalize(candidate.original_title)} - {''})}
                    if len(exact) > 1:
                        metadata.warnings.append('豆瓣自动关联未完成：有多个同名同年候选，请手动选择')
                        return []
                    if exact:
                        selected = next(iter(exact.values()))
                        break
                if selected is None:
                    metadata.warnings.append('豆瓣自动关联未完成：未找到唯一同名同年候选，请手动匹配')
                    return []
            related = self.details(selected)
            if related.source != 'douban' or related.id != selected.id:
                raise ScrapeError('豆瓣返回了不同的条目 ID')
            for source in set(metadata.ids) & set(related.ids):
                if metadata.ids[source] != related.ids[source]:
                    raise ScrapeError('两站来源 ID 冲突，未合并豆瓣资料')
            if not identity and (str(related.fields.get('year') or '') != year or not names & {
                    normalize(related.fields.get('title')), normalize(related.fields.get('original_title'))}):
                raise ScrapeError('豆瓣详情与搜索候选不一致，未合并')
            return [related]
        except (ScrapeError, OSError, ValueError) as exc:
            metadata.warnings.append('豆瓣自动关联未完成：' + str(exc))
            return []

    def save(self, draft: ScrapeDraft, selected_fields: set[str] | None = None,
             overwrite: bool = False, metadata_only: bool = False) -> Movie:
        if not draft.confirmed:
            raise ScrapeError("请先确认匹配，再保存")
        rebuilding = draft.rebuild_nfo and can_rebuild_nfo(draft.target)
        if (draft.target.error or draft.target.error_kind) and not rebuilding:
            raise ScrapeError(draft.target.error or draft.target.error_detail or "原 NFO 状态不允许保存")
        validate_target_version(draft.target)
        ensure_writable_file(draft.target.nfo_path, "NFO", allow_readonly=True)
        wants_poster = bool(draft.poster) and (selected_fields is None or "poster" in selected_fields)
        existing_poster = False
        if draft.target.existing and not rebuilding and not overwrite and not draft.replace_identity:
            from parsers.nfo_parser import NFOParser
            existing = NFOParser.parse(str(draft.target.nfo_path))
            if existing and existing.poster_path:
                existing_poster = True
                wants_poster = False
        if not draft.poster and not metadata_only and not existing_poster:
            raise ScrapeError("请先选择海报，或明确选择仅保存元数据")
        metadata_only = metadata_only or not wants_poster
        image = None
        if not metadata_only and draft.poster:
            ensure_writable_file(poster_path(draft), "海报")
            from scraper.scrape_http import HttpClient
            image = HttpClient(self.settings).get_bytes(draft.poster.url, max_bytes=15 * 1024 * 1024)
        return commit_draft(draft, selected_fields, overwrite, metadata_only, image)

    def douban_only(self, target: VideoTarget) -> dict:
        return scrape_douban_movie(str(target.nfo_path), target.title, "", target.year, settings=self.settings)


def scrape_douban_movie(nfo_path: str, title: str, original_title: str = "", year: str = "", *, settings: ScrapeSettings | None = None) -> dict:
    """旧豆瓣补分的非交互门面；不依赖 TMDB/OMDb 凭据。"""
    from scraper import douban_cli as cli
    from scraper.metadata_sources import DoubanProvider
    provider = DoubanProvider(settings or ScrapeSettings.load())
    try:
        original = Path(nfo_path).read_bytes()
        expected = hashlib.sha256(original).hexdigest()
        root = ET.fromstring(original)
        if root.tag != "movie":
            raise ScrapeError("NFO 根元素不是 movie")
        ids = read_ids(root)
        douban_id = ids.get("douban", "")
        if not douban_id:
            queries = [title, original_title or root.findtext("originaltitle", "")]
            match = None
            for query in dict.fromkeys(q for q in queries if q):
                match = provider._call(cli.search_movie, query, year)
                if match:
                    break
            if not match:
                return {"success": False, "message": f"未找到明确的豆瓣匹配，请在刮削工作台手动确认：{title}", "requires_match": True}
            douban_id = str(match["id"])
        if not re.fullmatch(r"\d+", douban_id):
            raise ScrapeError("已有豆瓣 ID 无效，请手动重新匹配")
        detail = provider._call(cli.get_movie_detail, douban_id)
        if not isinstance(detail, dict):
            raise ScrapeError("豆瓣详情未取得，请稍后重试或手动匹配")
        if detail.get("id") and str(detail["id"]) != douban_id:
            raise ScrapeError("豆瓣返回的电影 ID 不一致，已停止写入")
        try:
            score = validate_score(detail.get("rating"))
        except ScrapeError:
            return {"success": False, "message": "该电影暂无豆瓣评分，原 NFO 保持不变", "douban_id": douban_id}
        if score <= 0:
            return {"success": False, "message": "该电影暂无豆瓣评分，原 NFO 保持不变", "douban_id": douban_id}
        if not update_douban_nfo(nfo_path, douban_id, detail, expected_fingerprint=expected):
            raise ScrapeError("豆瓣 NFO 更新失败")
        return {"success": True, "message": f"成功：{detail.get('title') or title} - {score}/10", "rating": str(score), "douban_id": douban_id}
    except (OSError, ET.ParseError, LookupError, ScrapeError) as exc:
        return {"success": False, "message": str(exc) if isinstance(exc, ScrapeError) else "原 NFO 无法读取，请先检查文件"}
