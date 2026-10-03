"""
游戏墙数据存取层（HTTP/任务层与领域模块之间的适配）。

职责：
- 每个 app 实例一份 GameStore（懒创建，挂在 app.state），持有 game_cache.json
  与 config.json；**绝不在模块导入期创建任何有状态对象**，多数据目录的多个 app
  互不干扰。
- 缓存与配置文件都按本 app 的 data_dir 显式定位（不依赖 utils.app_paths 的进程级
  全局目录），写盘用「临时文件 + os.replace」原子替换，失败抛错（Excel 事务靠它回滚）。
- 所有读改写都在 store.lock 内完成（FastAPI 线程池并发）。
- Game → 契约 3.1 的 DTO 转换；设置读写与白名单校验。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote

from gamewall.aaa_classifier import build_auto_evidence, classify_aaa
from gamewall.excel_parser import diff_games, parse_excel
from gamewall.game_cache import CACHE_VERSION, GameCacheManager
from gamewall.game_models import Game
from gamewall.llm_classifier import TIER_VALUES
from utils.config_manager import ConfigManager
from wall_common.settings import Settings

logger = logging.getLogger("game_service.store")

LIST_DESCRIPTION_LIMIT = 200          # 契约 3.1：列表截断简介
CUSTOM_POSTER_SUFFIX = "_custom.jpg"  # 自定义封面文件名后缀（与桌面版一致）

# PUT /games/{key} 可编辑字段白名单（steam_appid 走 POST /games/steam/apply）
EDITABLE_FIELDS: Tuple[str, ...] = (
    "description", "header_image", "genres", "steam_name", "developer",
    "publishers", "platforms", "steam_categories", "release_date",
    "ign_score", "gamersky_score", "metacritic", "steam_positive_pct",
    "steam_review_total",
)
_STR_FIELDS = {"description", "header_image", "steam_name", "developer", "release_date"}
_LIST_FIELDS = {"genres", "publishers", "platforms", "steam_categories"}
_NUM_FIELDS = {"ign_score", "gamersky_score", "metacritic", "steam_positive_pct",
               "steam_review_total"}
_INT_FIELDS = {"steam_review_total"}

# 设置白名单（契约 3.3）；GET 永远不回明文 llm_api_key
_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "excel_path": "",
    "game_dirs": [],
    "poster_scale": 100,
    "network_enabled": True,
    "enable_enrichment": True,
    "enable_gamersky_scraper": True,
    "enable_ign_scraper": False,
    "llm_enabled": False,
    "llm_base_url": "",
    "llm_model": "gpt-4o-mini",
    "llm_api_key": "",
}
_SETTINGS_TYPES: Dict[str, type] = {
    "excel_path": str,
    "game_dirs": list,
    "poster_scale": int,
    "network_enabled": bool,
    "enable_enrichment": bool,
    "enable_gamersky_scraper": bool,
    "enable_ign_scraper": bool,
    "llm_enabled": bool,
    "llm_base_url": str,
    "llm_model": str,
    "llm_api_key": str,
}
_SETTINGS_GET_KEYS: Tuple[str, ...] = (
    "excel_path", "game_dirs", "poster_scale", "network_enabled",
    "enable_enrichment", "enable_gamersky_scraper", "enable_ign_scraper",
    "llm_enabled", "llm_base_url", "llm_model",
)

# Steam 类型名（英文）→ 中文；已有的中文值原样透传
_GENRE_CN: Dict[str, str] = {
    "action": "动作", "adventure": "冒险", "rpg": "角色扮演",
    "role-playing": "角色扮演", "role playing game (rpg)": "角色扮演",
    "strategy": "策略", "simulation": "模拟", "sports": "体育", "racing": "竞速",
    "fighting": "格斗", "shooter": "射击", "platform": "平台跳跃", "puzzle": "解谜",
    "casual": "休闲", "indie": "独立", "massively multiplayer": "大型多人在线",
    "mmo": "大型多人在线", "arcade": "街机", "visual novel": "视觉小说",
    "turn-based strategy": "回合制策略", "real-time strategy": "即时战略",
    "hack and slash": "砍杀", "roguelike": "肉鸽", "rogue-like": "肉鸽",
    "metroidvania": "银河城", "survival": "生存", "horror": "恐怖",
    "open world": "开放世界", "card game": "卡牌", "tower defense": "塔防",
    "education": "教育", "family": "家庭", "software training": "软件培训",
}


class StoreError(ValueError):
    """业务校验失败：HTTP 层转 400，任务层转任务 error（detail 均为中文）。"""


class LLMConfigError(StoreError):
    """LLM 配置缺失/不完整。"""


# ─────────────────── DTO 转换 ───────────────────


def decode_key(raw: str) -> str:
    """路径参数 → 缓存 key（路由层拿到的是未解码的百分号编码，这里解一次）。"""
    return unquote(raw or "")


def tier_source(game: Game) -> str:
    """档位来源：manual > llm > excel > rule（与 Game.tier 的优先级一致）。"""
    override = game.aaa_manual_override
    if isinstance(override, str) and override in TIER_VALUES:
        return "manual"
    verdict = game.aaa_llm_verdict
    if isinstance(verdict, dict) and verdict.get("tier") in TIER_VALUES:
        return "llm"
    if game.aaa_excel_marked:
        return "excel"
    return "rule"


def rating_of(game: Game) -> Tuple[float, str]:
    """主评分归一到 0-10：ign > gamersky > steam 好评率/10（无则 0/空）。"""
    try:
        ign = float(game.ign_score or 0)
        gamersky = float(game.gamersky_score or 0)
        steam = float(game.steam_positive_pct or 0)
    except (TypeError, ValueError):
        ign = gamersky = steam = 0.0
    if ign > 0:
        return round(ign, 1), "ign"
    if gamersky > 0:
        return round(gamersky, 1), "gamersky"
    if steam > 0:
        return round(steam / 10.0, 1), "steam"
    return 0.0, ""


def genres_cn(genres: Optional[Iterable[str]]) -> List[str]:
    """中文可直接展示的类型列表（英文类型走内置映射，去重保序）。"""
    out: List[str] = []
    for item in genres or []:
        text = str(item).strip()
        if not text:
            continue
        mapped = _GENRE_CN.get(text.lower(), text)
        if mapped not in out:
            out.append(mapped)
    return out


def custom_cover_path(data_dir, key: str) -> Path:
    """
    自定义封面路径：`{data_dir}/posters/{key}_custom.jpg`。

    与桌面版 `steamgrid_search.get_custom_poster_path` 同一命名约定；此处按
    本 app 的 data_dir 拼接（那个函数读的是导入期的全局 DATA_DIR，多 app 会串台）。
    含 `/` 的 key（如 `fate/staynight`）自然形成子目录。
    """
    return Path(data_dir) / "posters" / f"{key}{CUSTOM_POSTER_SUFFIX}"


def game_to_dto(game: Game, *, detail: bool = False,
                has_custom_cover: bool = False) -> Dict[str, Any]:
    """Game → 契约 3.1 DTO。detail=False 时把 description 截断到 200 字符。"""
    description = game.description or ""
    if not detail and len(description) > LIST_DESCRIPTION_LIMIT:
        description = description[:LIST_DESCRIPTION_LIMIT]

    rating, source = rating_of(game)
    override = game.aaa_manual_override
    if not (isinstance(override, str) and override in TIER_VALUES):
        override = None
    verdict = game.aaa_llm_verdict
    if not (isinstance(verdict, dict) and verdict):
        verdict = None

    return {
        "key": game.norm_key,
        "title_cn": game.title_cn or "",
        "title_en": game.title_en or "",
        "raw_name": game.raw_name or "",
        "excel_row": int(game.excel_row or 0),
        "quark_link": game.quark_link or "",
        "size_text": game.size_text or "",
        "size_bytes": float(game.size_bytes or 0),
        "version": game.version or "",
        "update_date": game.update_date or "",
        "release_date": game.release_date or "",
        "aaa_excel_marked": bool(game.aaa_excel_marked),
        "steam_appid": int(game.steam_appid or 0),
        "steam_name": game.steam_name or "",
        "developer": game.developer or "",
        "publishers": list(game.publishers or []),
        "platforms": list(game.platforms or []),
        "steam_categories": list(game.steam_categories or []),
        "genres": list(game.genres or []),
        "description": description,
        "steam_positive_pct": float(game.steam_positive_pct or 0),
        "steam_review_total": int(game.steam_review_total or 0),
        "metacritic": float(game.metacritic or 0),
        "ign_score": float(game.ign_score or 0),
        "gamersky_score": float(game.gamersky_score or 0),
        "header_image": game.header_image or "",
        "installed": bool(game.installed),
        "installed_exe": game.installed_exe or "",
        "installed_source": game.installed_source or "",
        "tier": game.tier,
        "is_aaa": bool(game.is_aaa),
        "tier_source": tier_source(game),
        "aaa_score": int(game.aaa_score or 0),
        "aaa_tier": game.aaa_tier or "",
        "aaa_evidence": copy.deepcopy(game.aaa_evidence or {}),
        "aaa_rule_version": game.aaa_rule_version or "",
        "aaa_manual_override": override,
        "aaa_llm_verdict": verdict,
        "genres_cn": genres_cn(game.genres),
        "rating": rating,
        "rating_source": source,
        "has_cover": bool(game.has_cover() or has_custom_cover),
        "needs_enrichment": bool(GameCacheManager.needs_enrichment(game)),
    }


# ─────────────────── 缓存 / 配置 ───────────────────


class WebGameCache(GameCacheManager):
    """
    game_cache.json 的网页版缓存：

    - 文件路径由 store 显式传入（不依赖 utils.app_paths 的全局目录）；
    - save() 原子写且**失败抛错**（基类会吞掉异常，Excel 事务无法据此回滚）。
    """

    def __init__(self, cache_file: Path):
        self._path = Path(cache_file)
        super().__init__()

    @property
    def _cache_file(self) -> Path:
        return self._path

    @property
    def version(self) -> int:
        try:
            return int(self._data.get("version", CACHE_VERSION))
        except (TypeError, ValueError):
            return CACHE_VERSION

    def save(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False)
        tmp = self._path.parent / f".{self._path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self._path)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise OSError(f"游戏缓存写入失败: {exc}") from exc
        self._dirty = False

    def snapshot_state(self) -> dict:
        """深拷贝当前内存状态（事务回滚用）。"""
        return copy.deepcopy(self._data)

    def restore_state(self, state: dict) -> None:
        self._data = copy.deepcopy(state)
        self._dirty = True


def _new_config(config_file: Path) -> ConfigManager:
    """
    构造**不共享进程单例**的 ConfigManager（每个 store 一份配置字典）。

    `object.__new__` 绕过 ConfigManager.__new__ 的单例逻辑，类属性
    `_instance`/`_config` 完全不受影响；随后显式按本 app 的 config.json 加载。
    """
    manager = object.__new__(ConfigManager)
    manager._config = {}           # 实例属性遮蔽类属性
    manager.load_config(str(config_file))
    return manager


def mask_api_key(key: str) -> str:
    """API Key 掩码：sk-abcdefgh → sk-a***efgh。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def validate_edit_fields(payload: Any) -> Dict[str, Any]:
    """PUT /games/{key} 请求体校验（白名单 + 类型），失败抛 StoreError。"""
    if not isinstance(payload, dict) or not payload:
        raise StoreError("请求体为空：请至少提交一个可编辑字段")
    for field in payload:
        if field == "steam_appid":
            raise StoreError("steam_appid 请通过 POST /games/steam/apply 更新")
        if field not in EDITABLE_FIELDS:
            raise StoreError(
                f"不支持的字段: {field}；可编辑字段: {', '.join(EDITABLE_FIELDS)}")
    checked: Dict[str, Any] = {}
    for field, value in payload.items():
        if field in _STR_FIELDS:
            if not isinstance(value, str):
                raise StoreError(f"字段 {field} 必须是字符串")
        elif field in _LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise StoreError(f"字段 {field} 必须是字符串数组")
        elif field in _NUM_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise StoreError(f"字段 {field} 必须是数字")
            if field in _INT_FIELDS:
                value = int(value)
        checked[field] = copy.deepcopy(value)
    return checked


# ─────────────────── 存储 ───────────────────


class GameStore:
    """单个 app 实例的游戏数据存取（线程安全）。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.lock = threading.RLock()

        self.cache_file = self.data_dir / "game_cache.json"
        self.config_file = self.data_dir / "config.json"

        self._cache = WebGameCache(self.cache_file)
        self._config = _new_config(self.config_file)

        self._games: List[Game] = []
        self._by_key: Dict[str, Game] = {}
        self._loaded = False

    # ── 懒加载 / 基础读取 ─────────────────────────────────
    def ensure_loaded(self) -> None:
        """首次访问时载入库：缓存优先，缓存为空才回退解析 Excel。"""
        with self.lock:
            if self._loaded:
                return
            games = self._cache.load_games_from_cache()
            if games:
                self.reclassify(games)
                self._cache.save()
                logger.info("游戏库已从缓存载入: %d 款", len(games))
            else:
                games = self._load_excel_locked()
            self._set_games(games)
            self._loaded = True

    def _load_excel_locked(self) -> List[Game]:
        """缓存为空时按设置里的 Excel 建库；失败/未配置返回空表。"""
        excel_path = self.excel_path()
        if not excel_path:
            logger.info("未配置 Excel，游戏库为空")
            return []
        try:
            games, meta = parse_excel(excel_path)
        except Exception as exc:  # noqa: BLE001  文件不存在/表头异常都降级为空库
            logger.error("Excel 加载失败，游戏库为空: %s", exc)
            return []
        if not games:
            logger.warning("Excel 解析结果为空，游戏库为空")
            return []
        for game in games:
            self._cache.apply_to_game(game)
        self.reclassify(games)
        self._cache.snapshot_games(games)
        self._cache.save()
        self._config.set_value("_excel_mtime", meta.get("mtime", 0))
        self._save_config()
        logger.info("游戏库已从 Excel 载入: %d 款", len(games))
        return games

    def _set_games(self, games: Iterable[Game]) -> None:
        ordered: List[Game] = []
        by_key: Dict[str, Game] = {}
        for game in games:
            key = game.norm_key
            if not key or key in by_key:
                continue          # 同 key 保留第一个（与桌面版 diff 的口径一致）
            by_key[key] = game
            ordered.append(game)
        self._games = ordered
        self._by_key = by_key

    def games(self) -> List[Game]:
        self.ensure_loaded()
        with self.lock:
            return list(self._games)

    def get(self, key: str) -> Optional[Game]:
        self.ensure_loaded()
        with self.lock:
            return self._by_key.get(key)

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def keys(self) -> List[str]:
        self.ensure_loaded()
        with self.lock:
            return list(self._by_key)

    # ── 配置 ─────────────────────────────────────────────
    def excel_path(self) -> str:
        with self.lock:
            value = self._config.get_value("excel_path", "") or ""
            return str(value).strip()

    def network_enabled(self) -> bool:
        with self.lock:
            return bool(self._config.get_value("network_enabled", True))

    def enrich_flags(self) -> Tuple[bool, bool]:
        """(启用游民星空, 启用 IGN)。"""
        with self.lock:
            return (
                bool(self._config.get_value("enable_gamersky_scraper", True)),
                bool(self._config.get_value("enable_ign_scraper", False)),
            )

    def game_dirs(self) -> List[str]:
        with self.lock:
            value = self._config.get_value("game_dirs", []) or []
            return [str(p) for p in value] if isinstance(value, (list, tuple)) else []

    def llm_config(self) -> Tuple[str, str, str]:
        """读取 LLM 配置；不完整抛 LLMConfigError（中文）。"""
        with self.lock:
            base_url = str(self._config.get_value("llm_base_url", "") or "").strip()
            api_key = str(self._config.get_value("llm_api_key", "") or "").strip()
            model = str(self._config.get_value("llm_model", "") or "").strip() or "gpt-4o-mini"
        if not base_url or not api_key:
            raise LLMConfigError("未配置 LLM：请先在设置中填写 API Base URL 与 API Key")
        return base_url, api_key, model

    def _save_config(self) -> None:
        self._config.save_config(str(self.config_file))

    def settings_read(self) -> Dict[str, Any]:
        """契约 3.3 的 GET /settings（绝不回明文 API Key）。"""
        with self.lock:
            out: Dict[str, Any] = {}
            for key in _SETTINGS_GET_KEYS:
                value = self._config.get_value(key, _SETTINGS_DEFAULTS[key])
                if key == "game_dirs":
                    value = [str(p) for p in value] if isinstance(value, (list, tuple)) else []
                elif key == "poster_scale":
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        value = _SETTINGS_DEFAULTS[key]
                elif isinstance(_SETTINGS_DEFAULTS[key], bool):
                    value = bool(value)
                else:
                    value = str(value) if value is not None else _SETTINGS_DEFAULTS[key]
                out[key] = value
            api_key = str(self._config.get_value("llm_api_key", "") or "")
            out["llm_api_key_set"] = bool(api_key)
            out["llm_api_key_mask"] = mask_api_key(api_key)
            return out

    def settings_write(self, payload: Any) -> None:
        """PUT /settings：部分更新，未知键或类型错误抛 StoreError。"""
        if not isinstance(payload, dict) or not payload:
            raise StoreError("请求体为空：请至少提交一个设置项")
        with self.lock:
            for key, value in payload.items():
                if key not in _SETTINGS_TYPES:
                    raise StoreError(
                        f"未知设置项: {key}；可用设置项: {', '.join(_SETTINGS_TYPES)}")
                self._check_setting(key, value)
            for key, value in payload.items():
                if key == "game_dirs":
                    value = [str(p) for p in value]
                self._config.set_value(key, value)
            self._save_config()

    @staticmethod
    def _check_setting(key: str, value: Any) -> None:
        expected = _SETTINGS_TYPES[key]
        if expected is bool:
            if not isinstance(value, bool):
                raise StoreError(f"设置项 {key} 必须是布尔值")
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise StoreError(f"设置项 {key} 必须是整数")
            if key == "poster_scale" and not 50 <= value <= 200:
                raise StoreError("poster_scale 必须在 50-200 之间")
        elif expected is str:
            if not isinstance(value, str):
                raise StoreError(f"设置项 {key} 必须是字符串")
        elif expected is list:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise StoreError(f"设置项 {key} 必须是字符串数组")

    # ── 分类 ─────────────────────────────────────────────
    def reclassify(self, games: Optional[Iterable[Game]] = None) -> None:
        """从游戏已有数据推导证据并重算规则分类（语义同桌面版）。"""
        with self.lock:
            for game in games if games is not None else self._games:
                evidence = build_auto_evidence(game)
                result = classify_aaa(evidence)
                game.aaa_evidence = evidence
                game.aaa_score = int(result.get("score", 0) or 0)
                game.aaa_tier = result.get("tier", game.aaa_tier)
                game.aaa_rule_version = str(result.get("rule_version", "") or "")
                self._cache.set_auto_aaa_classification(game.norm_key, result, evidence)

    # ── 写入 ─────────────────────────────────────────────
    def save(self) -> None:
        with self.lock:
            self._cache.save()

    def dto(self, game: Game, *, detail: bool = True) -> Dict[str, Any]:
        with self.lock:
            has_custom = custom_cover_path(self.data_dir, game.norm_key).is_file()
            return game_to_dto(game, detail=detail, has_custom_cover=has_custom)

    def list_dto(self) -> Dict[str, Any]:
        """契约 3.2 的 GET /games。"""
        self.ensure_loaded()
        with self.lock:
            dtos = [self.dto(game, detail=False) for game in self._games]
            return {
                "total": len(dtos),
                "games": dtos,
                "cache_info": {
                    "version": self._cache.version,
                    "excel_mtime": float(self._config.get_value("_excel_mtime", 0) or 0),
                },
            }

    def put_fields(self, key: str, fields: Dict[str, Any]) -> Game:
        """编辑字段：允许写空值（与 merge_fields 的「跳过空值」语义不同）。"""
        with self.lock:
            game = self._by_key.get(key)
            if game is None:
                raise KeyError(key)
            entry = self._cache.games_data.setdefault(key, {})
            for field, value in fields.items():
                entry[field] = copy.deepcopy(value)
                setattr(game, field, copy.deepcopy(value))
            if fields:
                self.reclassify([game])
                self._cache.save()
            return game

    def set_tier(self, key: str, tier: Optional[str]) -> Game:
        """人工档位；None 清除覆盖恢复自动判断。"""
        with self.lock:
            game = self._by_key.get(key)
            if game is None:
                raise KeyError(key)
            if tier is not None and tier not in TIER_VALUES:
                raise StoreError(f"档位只能是五档之一或 null: {', '.join(TIER_VALUES)}")
            self._cache.set_manual_aaa_override(key, tier)
            game.aaa_manual_override = tier
            self._cache.save()
            return game

    def apply_fields(self, key: str, fields: Dict[str, Any], *, force: bool,
                     save: bool = True) -> Tuple[Optional[Game], bool]:
        """
        合并联网补全结果（语义同桌面版 _on_game_enriched/_apply_steam_update）：
        force=True 覆盖非空值；force=False 只填空槽。返回 (game, 是否写入了字段)。
        """
        if not fields:
            return self._by_key.get(key), False
        with self.lock:
            game = self._by_key.get(key)
            if game is None:
                return None, False
            changed = self._cache.merge_fields(key, fields, force=force)
            applied = False
            for field, value in fields.items():
                if not hasattr(game, field):
                    continue
                if force:
                    if not GameCacheManager._is_empty(value):
                        setattr(game, field, copy.deepcopy(value))
                        applied = True
                elif (GameCacheManager._is_empty(getattr(game, field, None))
                        and not GameCacheManager._is_empty(value)):
                    setattr(game, field, copy.deepcopy(value))
                    applied = True
            if applied or changed:
                self.reclassify([game])
            if save and (applied or changed):
                self._cache.save()
            return game, applied

    def record_negative(self, key: str, source: str) -> None:
        """记确定性负结果（7 天内跳过重试）。"""
        with self.lock:
            self._cache.set_scraper_neg(key, source)

    def scraper_neg(self, key: str, source: str) -> Optional[float]:
        with self.lock:
            return self._cache.get_scraper_neg(key, source)

    def set_llm_verdict(self, key: str, verdict: Dict[str, Any]) -> None:
        with self.lock:
            game = self._by_key.get(key)
            if game is None:
                raise KeyError(key)
            self._cache.set_llm_aaa_verdict(key, verdict)
            game.aaa_llm_verdict = self._cache.get_llm_aaa_verdict(key)
            self._cache.save()

    def set_installed(self, key: str, installed: bool, exe_path: str = "",
                      source: str = "") -> None:
        with self.lock:
            game = self._by_key.get(key)
            if game is None:
                raise KeyError(key)
            game.installed = bool(installed)
            game.installed_exe = exe_path
            game.installed_source = source
            self._cache.set_installed_state(key, bool(installed), exe_path, source)
            self._cache.save()

    def mark_installed(self, entries: List[Dict[str, str]]) -> int:
        """
        把扫描结果匹配进游戏库（仅标记尚未安装的），返回匹配数；有匹配才落盘。
        """
        from .scanner import build_match_index, match_local_entry

        with self.lock:
            if not entries or not self._games:
                return 0
            index, buckets = build_match_index(self._games)
            matched = 0
            for entry in entries:
                game = match_local_entry(entry.get("name", ""), index, buckets)
                if game is None or game.installed:
                    continue
                exe_path = str(entry.get("exe_path", ""))
                source = str(entry.get("source", ""))
                game.installed = True
                game.installed_exe = exe_path
                game.installed_source = source
                self._cache.set_installed_state(game.norm_key, True, exe_path, source)
                matched += 1
                logger.info("本地识别: %s -> %s", entry.get("name", ""), exe_path)
            if matched:
                self._cache.save()
            return matched

    # ── Excel 差分 / 应用 ────────────────────────────────
    def excel_diff(self, games: List[Game], meta: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure_loaded()
        with self.lock:
            return self._diff_payload(games, meta, self._games)

    @staticmethod
    def _diff_payload(new_games: List[Game], meta: Dict[str, Any],
                      against: List[Game]) -> Dict[str, Any]:
        added, updated, removed = diff_games(against, new_games)
        return {
            "added": [game.norm_key for game in added],
            "updated": [key for key, _title, _changes in updated],
            "removed": [game.norm_key for game in removed],
            "counts": {
                "added": len(added),
                "updated": len(updated),
                "removed": len(removed),
            },
            "excel_meta": {
                "path": str(meta.get("path", "")),
                "mtime": float(meta.get("mtime") or 0),
                "header_row": int(meta.get("header_row") or 0),
                "game_count": len(new_games),
            },
        }

    def excel_apply(self, games: List[Game], meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用 Excel 更新（事务）：套用缓存字段 → 重算分类 → 快照 → 原子落盘；
        任一步失败则内存与磁盘都回滚到应用前状态并抛错。
        """
        self.ensure_loaded()
        with self.lock:
            if not games:
                raise StoreError("Excel 解析结果为空，已保留当前游戏库")
            previous_games = list(self._games)
            backup = self._cache.snapshot_state()
            try:
                for game in games:
                    self._cache.apply_to_game(game)
                self.reclassify(games)
                self._cache.snapshot_games(games)
                self._cache.save()
            except Exception:
                self._cache.restore_state(backup)
                try:
                    self._cache.save()
                except Exception as exc:  # noqa: BLE001  回滚落盘失败只记录
                    logger.error("Excel 回滚落盘失败: %s", exc)
                logger.exception("应用 Excel 更新失败，已回滚")
                raise
            self._set_games(games)
            self._config.set_value("_excel_mtime", meta.get("mtime", 0))
            self._save_config()
            payload = self._diff_payload(games, meta, previous_games)
            payload["total"] = len(games)
            logger.info("Excel 已应用: 新增 %(added)s / 更新 %(updated)s / 移除 %(removed)s",
                        payload["counts"])
            return payload

    def cache_info(self) -> Dict[str, Any]:
        self.ensure_loaded()
        with self.lock:
            return {
                "version": self._cache.version,
                "excel_mtime": float(self._config.get_value("_excel_mtime", 0) or 0),
            }


def store_of(request) -> GameStore:
    """取当前 app 的 GameStore（懒初始化 + 锁，绝不放在导入期）。"""
    app = request.app
    store = getattr(app.state, "store", None)
    if store is not None:
        return store
    lock = getattr(app.state, "store_lock", None)
    if lock is None:
        lock = threading.Lock()
        app.state.store_lock = lock
    with lock:
        store = getattr(app.state, "store", None)
        if store is None:
            store = GameStore(app.state.settings)
            app.state.store = store
    return store
