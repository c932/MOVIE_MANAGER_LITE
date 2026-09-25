"""
游戏名称工具
标题归一化、中英文名切分、名称匹配
"""
import difflib
import re
import unicodedata


def normalize_name(title: str) -> str:
    """
    标准化游戏名用于比较（去空格、去标点/括号/中点、小写、去重音符号）
    与电影库 scraper/douban_ranking._normalize_title 同一套规则
    """
    if not title:
        return ""
    t = str(title).lower()
    # 去除重音符号（é→e 等），保留中日韩字符
    decomposed = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in decomposed if unicodedata.category(c) not in ('Mn', 'Mc', 'Me'))
    t = re.sub(r'[\s\u3000]+', '', t)
    # 去除：冒号、中点（·・･）、逗号、句点、括号（全/半角）、引号、撇号、方括号、连字符
    t = re.sub(r'[：:·\.\,\-\'\"・･（）()\[\]【】\u2018\u2019\u0027\u0060\u00b4]+', '', t)
    return t


def split_title(raw_name: str) -> tuple:
    """
    按「首个 / 或 ／」切分为 (中文名, 英文名)
    无分隔符时英文名留空（英文名可能自带 /，如 Fate/Stay Night）
    """
    if not raw_name:
        return "", ""
    raw = str(raw_name).strip()
    for sep in ('/', '／'):
        idx = raw.find(sep)
        if idx > 0:
            cn = raw[:idx].strip()
            en = raw[idx + 1:].strip()
            if cn and en:
                return cn, en
    return raw, ""


class SteamNameIndex:
    """
    Steam 应用名索引：为数千次查询预建结构，避免逐次全量扫描
    exact: {归一化名: appid}
    keys: [(归一化名, appid)] 子串扫描用
    buckets: {前2字符: [(归一化名, appid)]} 模糊匹配用
    """

    def __init__(self, name_to_appid: dict):
        self.exact = {}
        self.keys = []
        self.buckets = {}
        for name, appid in name_to_appid.items():
            key = normalize_name(name)
            if not key or len(key) < 2:
                continue
            if key in self.exact:
                continue  # 同名应用保留第一个（Steam 数据源顺序通常主作为先）
            self.exact[key] = appid
            self.keys.append((key, appid))
            self.buckets.setdefault(key[:2], []).append((key, appid))

    def find_best_match(self, query_names, min_ratio: float = 0.85) -> int:
        """
        返回最佳匹配 appid（未匹配返回 0）
        规则：精确相等 → 长度比≥0.6 的子串包含（多个命中取显著最优）→ 前2字符桶内 difflib 模糊
        """
        best_id, best_score = 0, 0.0
        for qname in query_names:
            nq = normalize_name(qname)
            if not nq or len(nq) < 2:
                continue
            # 1) 精确
            if nq in self.exact:
                return self.exact[nq]
            # 2) 子串包含（长度比约束，防短名误匹配）
            matches = []
            for key, appid in self.keys:
                if len(key) < 3:
                    continue
                ratio = len(nq) / len(key) if len(nq) <= len(key) else len(key) / len(nq)
                if ratio < 0.6:
                    continue
                if nq in key or key in nq:
                    matches.append((appid, ratio))
            if len(matches) == 1:
                return matches[0][0]
            if len(matches) > 1:
                matches.sort(key=lambda m: -m[1])
                if matches[0][1] - matches[1][1] > 0.15:
                    return matches[0][0]
            # 3) 模糊：仅在前 2 字符桶内做 difflib（全量扫描太慢）
            candidates = self.buckets.get(nq[:2], [])
            if len(nq) >= 4:
                candidates += self.buckets.get(nq[2:4], [])
            for key, appid in candidates:
                if abs(len(key) - len(nq)) > max(len(nq) // 3, 3):
                    continue
                score = difflib.SequenceMatcher(None, nq, key).ratio()
                if score > best_score:
                    best_score, best_id = score, appid
        return best_id if best_score >= min_ratio else 0
