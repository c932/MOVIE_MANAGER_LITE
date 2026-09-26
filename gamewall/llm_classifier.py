"""
LLM 驱动的游戏五档分类器

通过调用 OpenAI 兼容 API，结合游戏元数据（名称、开发商、发行商、类型、
评分、评价数、体积等）将游戏归入五档：3A / 2A / 精品小众 / 普通游戏 / 避坑。

配置项（config.json）：
  llm_enabled: bool        是否启用 LLM 判定
  llm_base_url: str        API 端点（默认 https://api.openai.com/v1）
  llm_api_key: str         API Key
  llm_model: str           模型名（默认 gpt-4o-mini）
"""
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# 五档分类（前端筛选、缓存持久化保持一致）
TIER_3A = "3A"
TIER_2A = "2A"
TIER_NICHE = "精品小众"
TIER_NORMAL = "普通游戏"
TIER_AVOID = "避坑"
TIER_VALUES = (TIER_3A, TIER_2A, TIER_NICHE, TIER_NORMAL, TIER_AVOID)

_PROMPT_TEMPLATE = """你是一位资深游戏编辑。请根据以下游戏信息，将这款游戏归入五档分类之一。

五档定义：
- 3A：知名大型开发商/发行商，高预算大规模制作（50GB+ 或开放世界/复杂系统），媒体评分高（Metacritic 80+），Steam 好评率高且评价量大（5 万+）。体育年货大作（NBA2K、FIFA/EA FC 等）、知名即时战略（家园、英雄连、星际争霸等）、育碧/EA/动视/2K/Rockstar/万代南梦宫/Capcom/索尼/微软等大厂新作，即使类型相对小众也通常属于 3A。
- 2A：中等规模商业制作，预算体量低于 3A，但质量口碑不错。
- 精品小众：制作精良但受众较窄的中型/独立作品，口碑好（Steam 好评 85%+），但评价量不大。
- 普通游戏：质量口碑中等的普通商业游戏。
- 避坑：口碑差（好评率或媒体评分低）、存在严重问题不建议购买。

重要：不要因为游戏类型（体育、RTS、模拟经营、格斗等）相对小众就低估其制作体量。大厂高预算的知名系列新作应判为 3A 或 2A，而不是普通游戏。

游戏信息：
- 名称：{title}
- 开发商：{developer}
- 发行商：{publishers}
- 类型：{genres}
- Steam 好评率：{steam_pct}%
- Steam 评价总数：{steam_reviews}
- Metacritic 评分：{metacritic}
- 游戏体积：{size}
- 平台：{platforms}

请返回 JSON（只返回 JSON，不要其他文字）：
{{
  "tier": "3A/2A/精品小众/普通游戏/避坑",
  "confidence": "high/medium/low",
  "score": 0-100的整数,
  "reasoning": "简短理由（1-2句中文）"
}}"""


def _build_prompt(game) -> str:
    """从 Game 对象构建 LLM 判定 prompt。"""
    title = game.display_title()
    developer = getattr(game, "developer", "") or "未知"
    publishers = "、".join(getattr(game, "publishers", []) or []) or "未知"
    genres = "、".join(getattr(game, "genres", []) or []) or "未知"
    steam_pct = f"{game.steam_positive_pct:.0f}" if getattr(game, "steam_positive_pct", 0) > 0 else "暂无"
    steam_reviews = str(game.steam_review_total) if getattr(game, "steam_review_total", 0) > 0 else "暂无"
    metacritic = f"{game.metacritic:.0f}" if getattr(game, "metacritic", 0) > 0 else "暂无"
    size = getattr(game, "size_text", "") or "未知"
    platforms = "、".join(getattr(game, "platforms", []) or []) or "未知"

    return _PROMPT_TEMPLATE.format(
        title=title,
        developer=developer,
        publishers=publishers,
        genres=genres,
        steam_pct=steam_pct,
        steam_reviews=steam_reviews,
        metacritic=metacritic,
        size=size,
        platforms=platforms,
    )


def classify_with_llm(game, base_url: str, api_key: str, model: str,
                      timeout: float = 30.0) -> dict | None:
    """
    调用 LLM API 将游戏归入五档分类。

    Returns:
        {"tier", "is_aaa", "confidence", "score", "reasoning"} | None
        其中 is_aaa 为 tier=="3A" 的派生值，兼容既有 3A 筛选逻辑。
    """
    prompt = _build_prompt(game)
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位专业的游戏编辑，只返回 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }).encode("utf-8")

    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning(f"LLM API HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        logger.warning(f"LLM API 调用失败: {e}")
        return None

    try:
        content = body["choices"][0]["message"]["content"].strip()
        # 移除可能的 markdown 代码块包裹
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        result = json.loads(content)
        if not isinstance(result, dict):
            return None
        tier = str(result.get("tier", "")).strip()
        if tier not in TIER_VALUES:
            return None
        return {
            "tier": tier,
            "is_aaa": tier == TIER_3A,
            "confidence": str(result.get("confidence", "low")),
            "score": int(result.get("score", 0)),
            "reasoning": str(result.get("reasoning", "")),
        }
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        logger.warning(f"LLM 响应解析失败: {e} | raw={content[:200]}")
        return None
