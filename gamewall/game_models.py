"""
游戏数据模型
定义游戏对象的所有属性字段
"""
from dataclasses import dataclass, field
from typing import List, Optional

from gamewall.name_utils import normalize_name


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
    aaa_tier: str = "INDIE"
    aaa_evidence: dict = field(default_factory=dict)
    aaa_rule_version: str = ""
    aaa_manual_override: Optional[bool] = None
    aaa_llm_verdict: dict = field(default_factory=dict)  # LLM 判定结论 {is_aaa, confidence, score, reasoning}
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
    def is_aaa(self) -> bool:
        """供现有卡片与筛选使用的最终 3A 展示结论。"""
        if self.aaa_manual_override is not None:
            return self.aaa_manual_override
        if self.aaa_excel_marked or self.aaa_tier == "AAA":
            return True
        # LLM 判定只做「提升」（规则漏判时补上），不做「降级」。
        verdict = self.aaa_llm_verdict
        if isinstance(verdict, dict) and verdict.get("is_aaa"):
            return True
        return False

    @property
    def aaa_auto_label(self) -> str:
        if not self.aaa_rule_version:
            return "自动分类未评估"
        return f"规则计算：{self.aaa_tier}（{self.aaa_score} 分）"

    @property
    def aaa_llm_label(self) -> str:
        """LLM 判定结论的可读文本；未判定时返回空串。"""
        verdict = self.aaa_llm_verdict
        if not isinstance(verdict, dict) or not verdict:
            return ""
        verdict_is_aaa = verdict.get("is_aaa")
        confidence = verdict.get("confidence", "low")
        reasoning = verdict.get("reasoning", "")
        label = f"LLM 判定：{'是 3A' if verdict_is_aaa else '非 3A'}（置信度 {confidence}）"
        if reasoning:
            label += f"：{reasoning}"
        return label

    @property
    def aaa_source_label(self) -> str:
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
