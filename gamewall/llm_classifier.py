"""
LLM 驱动的 3A 游戏分类器

通过调用 OpenAI 兼容 API，结合游戏元数据（名称、开发商、发行商、类型、
评分、评价数、体积等）综合判定是否为 3A 大作。结果以结构化 JSON 返回，
由主线程合并为可追溯证据。

配置项（config.json）：
  llm_enabled: bool        是否启用 LLM 3A 判定
  llm_base_url: str        API 端点（默认 https://api.openai.com/v1）
  llm_api_key: str         API Key
  llm_model: str           模型名（默认 gpt-4o-mini）
"""
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """你是一位资深游戏编辑。请根据以下游戏信息，判断它是否属于"3A 大作"（AAA级游戏）。

3A 大作的典型特征：
- 由知名大型开发商/发行商制作发行
- 开发预算高、制作规模大（通常 50GB+ 或开放世界/复杂系统）
- 媒体评分高（Metacritic 80+）
- 玩家评价高、评价数量大（Steam 好评率 80%+、评价数 5 万+）
- 跨多平台发行

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
  "is_aaa": true或false,
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
    调用 LLM API 判定游戏是否为 3A。

    Returns:
        {"is_aaa": bool, "confidence": str, "score": int, "reasoning": str} | None
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
        if not isinstance(result, dict) or "is_aaa" not in result:
            return None
        return {
            "is_aaa": bool(result.get("is_aaa")),
            "confidence": str(result.get("confidence", "low")),
            "score": int(result.get("score", 0)),
            "reasoning": str(result.get("reasoning", "")),
        }
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        logger.warning(f"LLM 响应解析失败: {e} | raw={content[:200]}")
        return None


def result_to_evidence(result: dict, model: str) -> dict:
    """将 LLM 判定结果转为与 aaa_classifier 兼容的证据格式。"""
    if not result or not isinstance(result, dict):
        return {}
    score = result.get("score", 0)
    is_aaa = result.get("is_aaa", False)
    confidence = result.get("confidence", "low")
    reasoning = result.get("reasoning", "")

    # 将 LLM 分数映射到规则系统的证据结构
    evidence = {}
    source = f"LLM 判定（{model}，置信度 {confidence}）"

    if is_aaa:
        # LLM 判定为 3A：至少让分数达到 AAA 阈值 55
        evidence["llm_aaa_verdict"] = {
            "confirmed": True,
            "sources": [f"{source}：{reasoning}"],
        }
        evidence["llm_aaa_score"] = {
            "value": float(score),
            "sources": [source],
        }
    else:
        evidence["llm_aaa_verdict"] = {
            "confirmed": False,
            "sources": [f"{source}：{reasoning}"],
        }

    return evidence