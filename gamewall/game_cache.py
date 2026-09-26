"""
游戏库缓存管理器。

Excel 原始字段、自动 3A 分类和人工 3A 覆盖分别持久化：联网补全只填空，
Excel 快照只更新 Excel 来源，人工覆盖只能通过专用 API 修改。
"""
import copy
import json
import logging
import time
from pathlib import Path
from typing import Optional

from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)

CACHE_VERSION = 2
_WEB_FIELDS = (
    "steam_appid", "steam_name", "developer", "publishers", "platforms",
    "steam_categories", "genres", "description", "header_image",
    "steam_positive_pct", "steam_review_total", "metacritic", "release_date",
    "ign_score", "gamersky_score",
)
_LOCAL_FIELDS = ("installed", "installed_exe", "installed_source")
_EXCEL_FIELDS = (
    "title_cn", "title_en", "raw_name", "quark_link", "size_text",
    "size_bytes", "version", "update_date", "release_date", "aaa_excel_marked",
)
_CLASSIFICATION_FIELDS = (
    "aaa_score", "aaa_tier", "aaa_evidence", "aaa_rule_version",
)
_LLM_FIELDS = ("aaa_llm_verdict",)
_MANUAL_OVERRIDE_FIELD = "aaa_manual_override"
_ALL_FIELDS = _EXCEL_FIELDS + _WEB_FIELDS + _LOCAL_FIELDS + _CLASSIFICATION_FIELDS + _LLM_FIELDS + (
    _MANUAL_OVERRIDE_FIELD, "excel_row",
)
_MERGEABLE_FIELDS = _WEB_FIELDS + _LOCAL_FIELDS
_NEG_TTL = 7 * 86400


class GameCacheManager:
    """game_cache.json 读写与按来源合并。"""

    def __init__(self):
        self._data = {"version": CACHE_VERSION, "games": {}, "scraper_neg": {}}
        self._dirty = False
        self._load()

    @property
    def _cache_file(self) -> Path:
        return resolve_data_file("game_cache.json")

    def _load(self):
        path = self._cache_file
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("games"), dict):
                return
            self._data = data
            self._data.setdefault("scraper_neg", {})
            try:
                version = int(self._data.get("version", 1))
            except (TypeError, ValueError):
                version = 1
            if version < CACHE_VERSION:
                self._migrate(version)
            else:
                self._data.setdefault("version", CACHE_VERSION)
            logger.info("游戏缓存加载成功: %d 条", len(self._data["games"]))
        except Exception as e:
            logger.error("游戏缓存加载失败，使用空缓存: %s", e)

    def _migrate(self, version: int):
        if version < 2:
            for entry in self._data["games"].values():
                if isinstance(entry, dict):
                    entry.pop("is_aaa", None)
            logger.info("游戏缓存已迁移至 v2；旧 is_aaa 不作为人工 3A 结论保留")
        self._data["version"] = CACHE_VERSION
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            self._dirty = False
            logger.debug("游戏缓存已保存: %d 条", len(self._data["games"]))
        except Exception as e:
            logger.error("游戏缓存保存失败: %s", e)

    def apply_to_game(self, game, force: bool = False):
        """将持久化的联网、本地、自动分类及人工覆盖状态应用到游戏。"""
        data = self._data["games"].get(game.norm_key)
        if not data:
            return False
        applied = False
        fields = _ALL_FIELDS if force else (
            _WEB_FIELDS + _LOCAL_FIELDS + _CLASSIFICATION_FIELDS + _LLM_FIELDS + (_MANUAL_OVERRIDE_FIELD,)
        )
        for field in fields:
            if field not in data:
                continue
            value = copy.deepcopy(data[field])
            if field in _CLASSIFICATION_FIELDS or field in _LLM_FIELDS or field == _MANUAL_OVERRIDE_FIELD:
                if getattr(game, field, None) != value:
                    setattr(game, field, value)
                    applied = True
                continue
            current = getattr(game, field, None)
            if force or self._is_empty(current):
                setattr(game, field, value)
                applied = True
        return applied

    def load_games_from_cache(self):
        """Excel 不可用时，直接从缓存构建游戏库。"""
        from gamewall.game_models import Game

        games = []
        for key, data in self._data["games"].items():
            game = Game(raw_name=key)
            for field in _ALL_FIELDS:
                if field in data:
                    setattr(game, field, copy.deepcopy(data[field]))
            if not game.title_cn and not game.title_en:
                game.title_cn = key
            games.append(game)
        return games

    def merge_fields(self, norm_key: str, fields: dict, force: bool = False):
        """合并联网或本地字段；分类与人工覆盖必须调用专用 API。"""
        entry = self._data["games"].setdefault(norm_key, {})
        changed = False
        for field, value in fields.items():
            if field not in _MERGEABLE_FIELDS:
                continue
            if not force and not self._is_empty(entry.get(field)):
                continue
            if force and self._is_empty(value):
                continue
            if entry.get(field) != value:
                entry[field] = copy.deepcopy(value)
                changed = True
        if changed:
            self._dirty = True
        return changed

    def set_installed_state(self, norm_key: str, installed: bool,
                            exe_path: str = "", source: str = ""):
        """直接写入本地安装状态，允许 False 与空路径。"""
        entry = self._data["games"].setdefault(norm_key, {})
        for field, value in (("installed", installed), ("installed_exe", exe_path),
                             ("installed_source", source)):
            if entry.get(field) != value:
                entry[field] = value
                self._dirty = True

    def get_manual_aaa_override(self, norm_key: str) -> Optional[bool]:
        value = self._data["games"].get(norm_key, {}).get(_MANUAL_OVERRIDE_FIELD)
        return value if isinstance(value, bool) else None

    def set_llm_aaa_verdict(self, norm_key: str, verdict: dict):
        """持久化 LLM 3A 判定结论；空 dict 表示清除。"""
        entry = self._data["games"].setdefault(norm_key, {})
        if not isinstance(verdict, dict) or not verdict:
            if "aaa_llm_verdict" in entry:
                del entry["aaa_llm_verdict"]
                self._dirty = True
            return
        value = {
            "is_aaa": bool(verdict.get("is_aaa")),
            "confidence": str(verdict.get("confidence", "low")),
            "score": int(verdict.get("score", 0)),
            "reasoning": str(verdict.get("reasoning", "")),
        }
        if entry.get("aaa_llm_verdict") != value:
            entry["aaa_llm_verdict"] = value
            self._dirty = True

    def get_llm_aaa_verdict(self, norm_key: str) -> dict:
        """读取已持久化的 LLM 3A 判定。"""
        value = self._data["games"].get(norm_key, {}).get("aaa_llm_verdict")
        if isinstance(value, dict):
            return copy.deepcopy(value)
        return {}

    def set_manual_aaa_override(self, norm_key: str, override: Optional[bool]):
        """保存人工 3A 覆盖；None 表示清除覆盖并恢复自动判断。"""
        if override is not None and not isinstance(override, bool):
            raise ValueError("3A 人工覆盖只能是 True、False 或 None")
        entry = self._data["games"].setdefault(norm_key, {})
        if override is None:
            if _MANUAL_OVERRIDE_FIELD in entry:
                del entry[_MANUAL_OVERRIDE_FIELD]
                self._dirty = True
            return
        if entry.get(_MANUAL_OVERRIDE_FIELD) != override:
            entry[_MANUAL_OVERRIDE_FIELD] = override
            self._dirty = True

    def clear_manual_aaa_override(self, norm_key: str):
        self.set_manual_aaa_override(norm_key, None)

    def set_auto_aaa_classification(self, norm_key: str, result: dict, evidence: dict):
        """完整替换自动分类结果，不影响人工覆盖。"""
        entry = self._data["games"].setdefault(norm_key, {})
        score = result.get("score", 0)
        if not isinstance(score, int) or isinstance(score, bool):
            score = 0
        tier = result.get("tier", "INDIE")
        if tier not in {"AAA", "AAA_EDGE", "AA", "INDIE"}:
            tier = "INDIE"
        values = {
            "aaa_score": score,
            "aaa_tier": tier,
            "aaa_evidence": copy.deepcopy(evidence) if isinstance(evidence, dict) else {},
            "aaa_rule_version": str(result.get("rule_version") or ""),
        }
        for field, value in values.items():
            if entry.get(field) != value:
                entry[field] = value
                self._dirty = True

    def get_auto_aaa_classification(self, norm_key: str) -> dict:
        entry = self._data["games"].get(norm_key, {})
        return {field: copy.deepcopy(entry.get(field)) for field in _CLASSIFICATION_FIELDS
                if field in entry}

    def snapshot_games(self, games):
        """以当前 Excel 库为准同步原始字段，同时保留分类、人工覆盖与联网数据。"""
        valid_keys = {game.norm_key for game in games}
        removed = set(self._data["games"]) - valid_keys
        for key in removed:
            del self._data["games"][key]
        if removed:
            self._dirty = True
            logger.info("缓存修剪: 移除 %d 条不再存在的游戏", len(removed))

        for game in games:
            entry = self._data["games"].setdefault(game.norm_key, {})
            for field in _EXCEL_FIELDS + ("excel_row",):
                value = copy.deepcopy(getattr(game, field, None))
                if entry.get(field) != value:
                    entry[field] = value
                    self._dirty = True

    @staticmethod
    def game_to_fields(game) -> dict:
        """Game 对象 → 可序列化的非空字段字典。"""
        fields = {}
        for field in _ALL_FIELDS:
            value = getattr(game, field, None)
            if not GameCacheManager._is_empty(value) or isinstance(value, bool):
                fields[field] = copy.deepcopy(value)
        return fields

    @staticmethod
    def _is_empty(value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0
        if isinstance(value, (int, float)):
            return value == 0
        return False

    @staticmethod
    def needs_enrichment(game) -> bool:
        return (not game.steam_appid or not game.description
                or not game.release_date or game.steam_positive_pct <= 0)

    @property
    def games_data(self) -> dict:
        return self._data["games"]

    def __len__(self):
        return len(self._data["games"])

    def get_scraper_neg(self, norm_key: str, source: str) -> Optional[float]:
        entry = self._data["scraper_neg"].get(f"{norm_key}|{source}")
        if not entry:
            return None
        remain = entry.get("ts", 0) + _NEG_TTL - time.time()
        return remain if remain > 0 else None

    def set_scraper_neg(self, norm_key: str, source: str):
        self._data["scraper_neg"][f"{norm_key}|{source}"] = {"ts": time.time()}
        self._dirty = True

    def prune_scraper_neg(self):
        expired = [key for key, value in self._data["scraper_neg"].items()
                   if value.get("ts", 0) + _NEG_TTL < time.time()]
        for key in expired:
            del self._data["scraper_neg"][key]
        if expired:
            self._dirty = True
