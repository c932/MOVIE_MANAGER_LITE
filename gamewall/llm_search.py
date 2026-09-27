"""
LLM 驱动的 Steam 搜索匹配

用 LLM 推断游戏的 Steam 英文名 / appid，再经 Steam 公开 API 验证并拉取
详情、评价与海报字段。LLM 直接给出的 appid 不被信任——必须经
fetch_appdetails 验证商店页存在，或经 match_appid 搜索命中后才采信。
"""
import json
import logging
import urllib.error
import urllib.request

from gamewall import steam_client

logger = logging.getLogger(__name__)

_SUGGEST_PROMPT = """你是一位资深游戏编辑，熟悉 Steam 商店。请根据以下游戏信息，推断它在 Steam 上的官方英文名和 appid。

游戏信息：
- 中文名：{title_cn}
- 英文名（若有）：{title_en}
- 开发商：{developer}

请返回 JSON（只返回 JSON，不要其他文字）：
{{
  "english_title": "Steam 商店官方英文名",
  "appid": 数字（不确定时填 0，不要编造）
}}"""


def _build_suggest_prompt(game) -> str:
    return _SUGGEST_PROMPT.format(
        title_cn=(getattr(game, "title_cn", "") or getattr(game, "raw_name", "") or "未知"),
        title_en=(getattr(game, "title_en", "") or "未知"),
        developer=(getattr(game, "developer", "") or "未知"),
    )


def _call_llm_json(prompt: str, base_url: str, api_key: str, model: str,
                   timeout: float) -> dict | None:
    """调用 OpenAI 兼容 chat/completions，返回解析后的 dict 或 None。"""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位专业的游戏编辑，只返回 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 128,
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
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        result = json.loads(content)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"LLM 响应解析失败: {e} | raw={content[:200]}")
        return None


def suggest_steam_match(game, base_url: str, api_key: str, model: str,
                        timeout: float = 30.0) -> dict | None:
    """让 LLM 推断 Steam 英文名与 appid 猜测。

    Returns:
        {"english_title": str, "appid": int} | None
    """
    result = _call_llm_json(_build_suggest_prompt(game), base_url, api_key, model, timeout)
    if not result:
        return None
    english_title = str(result.get("english_title", "")).strip()
    try:
        appid = int(result.get("appid") or 0)
    except (TypeError, ValueError):
        appid = 0
    if not english_title and appid <= 0:
        return None
    return {"english_title": english_title, "appid": max(appid, 0)}


def llm_match_and_fetch(game, base_url: str, api_key: str, model: str,
                        timeout: float = 30.0) -> tuple:
    """LLM 辅助匹配 Steam 并拉取详情/评价，返回可直接 merge 的字段。

    Returns:
        (fields, err)：fields 含 steam_appid/steam_name/description/header_image/
        评分等；err 非空表示整体失败。
    """
    suggestion = suggest_steam_match(game, base_url, api_key, model, timeout)
    if not suggestion:
        return {}, "LLM 未给出有效建议（检查 LLM 配置或网络）"

    appid = 0
    steam_name = ""

    # 1) LLM 猜的 appid：必须用 appdetails 验证商店页存在
    if suggestion["appid"] > 0:
        fields, err = steam_client.fetch_appdetails(suggestion["appid"])
        if err is None or err == "":
            if fields:  # success=true 且有数据 → 采信
                appid = suggestion["appid"]
                steam_name = fields.get("steam_name", "")

    # 2) 验证失败/无 appid：用 LLM 给的英文名走搜索匹配
    if not appid:
        en = suggestion["english_title"]
        if en:
            matched, name, _ = steam_client.match_appid([en, getattr(game, "title_cn", "")])
            if matched:
                appid = matched
                steam_name = name
    if not appid:
        return {}, f"无法验证 LLM 建议（英文名：{suggestion['english_title'] or '无'}）"

    # 3) 命中后拉全量详情 + 评价
    fields = {"steam_appid": appid}
    if steam_name:
        fields["steam_name"] = steam_name
    details, err = steam_client.fetch_appdetails(appid)
    if err:
        return fields, f"详情拉取失败：{err}"
    fields.update(details or {})
    reviews, err = steam_client.fetch_appreviews(appid)
    if err:
        return fields, f"评价拉取失败：{err}"
    fields.update(reviews or {})
    return fields, ""
