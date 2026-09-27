"""
游戏数据模型
定义游戏对象的所有属性字段
"""
from dataclasses import dataclass, field
from typing import List, Optional

from gamewall.llm_classifier import (
    TIER_3A, TIER_2A, TIER_NICHE, TIER_NORMAL, TIER_AVOID, TIER_VALUES,
)
from gamewall.name_utils import normalize_name

# 旧规则/LLM 档位 → 五档映射（兼容缓存中旧数据）
_OLD_TIER_MAP = {"AAA": TIER_3A, "AAA_EDGE": TIER_2A, "AA": TIER_NICHE, "INDIE": TIER_NORMAL}


def _normalize_tier(raw) -> str:
    """将旧档位或任意值规范化为五档之一。"""
    if isinstance(raw, str) and raw in TIER_VALUES:
        return raw
    if isinstance(raw, str):
        return _OLD_TIER_MAP.get(raw, TIER_NORMAL)
    return TIER_NORMAL


def _normalize_manual_override(value) -> Optional[str]:
    """兼容旧版 bool 人工覆盖：True→3A，False→普通游戏。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return TIER_3A if value else TIER_NORMAL
    if isinstance(value, str) and value in TIER_VALUES:
        return value
    return None


@dataclass
class Game:
    """
    游戏完整数据模型
    基础信息来自 Excel，元数据由 Steam 等来源联网补全
    """
    # Excel 基础信息
    title_cn: str = ""  # 中文名（原始名不含 / 时即完整名）
    title_en: str = ""  # 英文名
    raw_name: str = ""  # Excel 原始名称（中/英混合）
    quark_link: str = ""  # 夸克网盘下载链接
    size_text: str = ""  # 大小文本（如 48.4G）
    size_bytes: float = 0.0  # 解析后的字节数（用于排序）
    version: str = ""  # 版本描述
    update_date: str = ""  # 更新日期 (YYYY-MM-DD)
    release_date: str = ""  # 发售日期 (YYYY-MM-DD)，Excel 或 Steam
    aaa_excel_marked: bool = False  # 当前 Excel 原始 3A 标记
    aaa_score: int = 0
    aaa_tier: str = TIER_NORMAL  # 规则计算的五档结果
    aaa_evidence: dict = field(default_factory=dict)
    aaa_rule_version: str = ""
    aaa_manual_override: Optional[str] = None  # 人工五档覆盖（3A/2A/精品小众/普通游戏/避坑）
    aaa_llm_verdict: dict = field(default_factory=dict)  # LLM 判定结论 {tier, is_aaa, confidence, score, reasoning}
    excel_row: int = 0  # Excel 行号（诊断用）

    # Steam 联网补全
    steam_appid: int = 0
    steam_name: str = ""  # Steam 商店名
    developer: str = ""  # 制作公司（Steam developers，取前两家）
    publishers: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    steam_categories: List[str] = field(default_factory=list)
    genres: List[str] = field(default_factory=list)
    description: str = ""  # 简介文本
    header_image: str = ""  # Steam 头图 URL（兜底封面）
    steam_positive_pct: float = 0.0  # Steam 好评率（0-100）
    steam_review_total: int = 0
    metacritic: float = 0.0  # Metacritic 媒体评分

    # 第三方评分（尽力而为）
    ign_score: float = 0.0
    gamersky_score: float = 0.0

    # 本地安装状态
    installed: bool = False
    installed_exe: str = ""  # 本地 exe 绝对路径
    installed_source: str = ""  # dir / lnk

    @property
    def norm_key(self) -> str:
        """归一化标题，作为缓存与卡片池的 key"""
        return normalize_name(self.raw_name or self.title_cn)

    @property
    def tier(self) -> str:
        """最终展示的五档分类（3A/2A/精品小众/普通游戏/避坑）。

        优先级：人工标记 > LLM 判定 > Excel 3A 标记 > 规则计算。
        """
        if isinstance(self.aaa_manual_override, str) and self.aaa_manual_override in TIER_VALUES:
            return self.aaa_manual_override
        verdict = self.aaa_llm_verdict
        if isinstance(verdict, dict):
            raw_tier = verdict.get("tier")
            # 仅当 LLM 给出了合法档位时才采信，避免空判定覆盖规则结果
            if isinstance(raw_tier, str) and raw_tier in TIER_VALUES:
                return raw_tier
        if self.aaa_excel_marked:
            return TIER_3A
        return _normalize_tier(self.aaa_tier)

    @property
    def is_aaa(self) -> bool:
        """供现有卡片与筛选使用的最终 3A 展示结论。"""
        if isinstance(self.aaa_manual_override, bool):
            return self.aaa_manual_override
        return self.tier == TIER_3A

    @property
    def aaa_auto_label(self) -> str:
        if not self.aaa_rule_version:
            return "自动分类未评估"
        return f"规则计算：{_normalize_tier(self.aaa_tier)}（{self.aaa_score} 分）"

    @property
    def aaa_llm_label(self) -> str:
        """LLM 判定结论的可读文本；未判定时返回空串。"""
        verdict = self.aaa_llm_verdict
        if not isinstance(verdict, dict) or not verdict:
            return ""
        tier = _normalize_tier(verdict.get("tier", ""))
        confidence = verdict.get("confidence", "low")
        reasoning = verdict.get("reasoning", "")
        label = f"LLM 判定：{tier}（置信度 {confidence}）"
        if reasoning:
            label += f"：{reasoning}"
        return label

    @property
    def aaa_source_label(self) -> str:
        if isinstance(self.aaa_manual_override, str) and self.aaa_manual_override in TIER_VALUES:
            return f"人工标记为 {self.aaa_manual_override}；{self.aaa_auto_label}"
        if self.aaa_manual_override is True:
            return f"人工标记为 3A；{self.aaa_auto_label}"
        if self.aaa_manual_override is False:
            return f"人工标记为非 3A；{self.aaa_auto_label}"
        if self.aaa_excel_marked:
            return f"Excel 标记为 3A；{self.aaa_auto_label}"
        if self.aaa_llm_label:
            return f"{self.aaa_llm_label}；{self.aaa_auto_label}"
        return self.aaa_auto_label

    def display_title(self) -> str:
        """获取显示标题（优先中文名）"""
        return self.title_cn or self.title_en or self.raw_name

    def has_cover(self) -> bool:
        """是否有可加载的封面"""
        return bool(self.steam_appid or self.header_image)

    def get_cover_urls(self) -> list:
        """候选封面 URL 列表（竖版优先，头图兜底）"""
        urls = []
        if self.steam_appid:
            urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{self.steam_appid}/library_600x900.jpg")
        if self.header_image:
            urls.append(self.header_image)
        return urls

    def get_rating_value(self) -> float:
        """综合评分值（用于排序）：Steam 好评率优先，其次 Metacritic"""
        if self.steam_positive_pct > 0:
            return self.steam_positive_pct
        return self.metacritic

    def get_release_display(self) -> str:
        return self.release_date or "未知"
