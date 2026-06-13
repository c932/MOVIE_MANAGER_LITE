"""
豆瓣电影排行榜抓取与本地库对比模块

功能：
- 抓取豆瓣 Top250 榜单
- 抓取豆瓣近期热门榜单
- 将榜单与本地电影库进行智能匹配对比
- 识别本地库缺失的电影
"""
import re
import html
import json
import logging
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

REQUEST_TIMEOUT = 15


@dataclass
class RankedMovie:
    """榜单电影数据结构"""
    title: str
    year: str
    rating: float
    douban_id: str
    rank: int
    source: str  # "top250" or "chart" or "imdb_top250"
    poster_url: str = ""
    premiered: str = ""  # 完整上映日期，如 "2025-11-27"


# ─────────────────── 匹配工具函数 ───────────────────

def _normalize_title(title: str) -> str:
    """标准化标题用于比较（去空格、去标点/括号/中点、小写、去重音符号）"""
    if not title:
        return ""
    import unicodedata
    t = title.lower()
    # 去除重音符号（é→e, ö→o, è→e 等），保留中日韩字符
    # NFD 分解后去掉 combining marks（Unicode category Mn/Mc/Me）
    decomposed = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in decomposed if unicodedata.category(c) not in ('Mn', 'Mc', 'Me'))
    t = re.sub(r'[\s\u3000]+', '', t)
    # 去除：冒号、中点（·・･）、逗号、括号（全/半角）、引号、撇号、方括号、连字符
    t = re.sub(r'[：:·\.\,\-\'\"・･（）()\[\]【】\u2018\u2019\u0027\u0060\u00b4]+', '', t)
    return t


# ─────────────────── IMDB 标题翻译表 ───────────────────
# key: IMDB 原始标题 (标准化后), value: [中文标题, 英文标题(如有)]
# 用于匹配非英文 IMDB 标题与本地中文库
_IMDB_TITLE_TRANSLATIONS = {
    # 日语 romaji → 中文
    "sentochihironokamikakushi": ["千与千寻", "spiritedaway"],
    "shichininnosamurai": ["七武士", "sevensofthesamurai"],
    "hotarunohaka": ["萤火虫之墓", "graveofthefireflies"],
    "mononokehime": ["幽灵公主", "princessmononoke"],
    "kiminonawa": ["你的名字", "yourname"],
    "haurunougokushiro": ["哈尔的移动城堡", "howlsmovingcastle"],
    "tonarinototoro": ["龙猫", "myneighbortotoro"],
    "rashomon": ["罗生门"],
    "yojinbo": ["用心棒"],
    "tokyomonogatari": ["东京物语", "tokyostory"],
    "tengokutojigoku": ["天国与地狱", "highandlow"],
    "ran": ["乱", "ran"],
    "seppuku": ["切腹", "harakiri"],
    "ikiru": ["生之欲", "tolive"],
    # 意大利语 → 中文
    "ilbuonoilbruttoilcattivo": ["黄金三镖客", "thegoodthebadandtheugly"],
    "lavitaebella": ["美丽人生", "lifeisbeautiful"],
    "nuovocinemaparadiso": ["天堂电影院", "cinemaparadiso"],
    "ladrìdibiciclette": ["偷自行车的人", "bicyclethieves"],
    "perqualchedollaroinpiu": ["黄昏双镖客", "forafewdollarsmore"],
    "labattagliadialgeri": ["阿尔及尔之战", "thebattleofalgiers"],
    # 韩语 → 中文
    "gisaengchung": ["寄生虫", "parasite"],
    "oldeuboi": ["老男孩", "oldboy"],
    "ahgassi": ["小姐", "thehandmaiden"],
    "salinuichueok": ["杀人回忆", "memoriesofmurder"],
    # 西班牙语/葡萄牙语 → 中文
    "cidadedeus": ["上帝之城", "cityofgod"],
    "ellaberintodelufauno": ["潘神的迷宫", "panslabyrinth"],
    "elsecretodesusojos": ["谜一样的双眼", "thesecretintheireyes"],
    "relatossalvajes": ["荒蛮故事", "wildtales"],
    # 德语 → 中文
    "meinestadtsuchteinenmorder": ["M就是凶手", "m"],
    "deruntergang": ["帝国的毁灭", "downfall"],
    # 法语 → 中文
    "lefabuleuxdestindameliepoulain": ["天使爱美丽", "amelie"],
    "leshaine": ["怒火青春", "hate"],
    "lesquatrecentscoups": ["四百击", "the400blows"],
    "lesalairedelapeur": ["恐惧的代价", "thewagesoffear"],
    "lapassiondejeannedarc": ["圣女贞德蒙难记", "thepassionofjoanofarc"],
    # 瑞典语 → 中文
    "smultronstallet": ["野草莓", "wildstrawberries"],
    "detsjundeinseglet": ["第七封印", "theseventhseal"],
    # 土耳其语 → 中文
    "babamveoglum": ["我的父亲我的儿子", "myfatherandmyson"],
    # 波斯语 → 中文
    "bachehayeaseman": ["小鞋子", "childrenofheaven"],
    "jadoiyenaderazsimin": ["一次别离", "aseparation"],
    # 印度语 → 中文
    "jaibhim": ["杰伊·比姆"],
    "taarezameenpar": ["地球上的星星", "likestarsonearth"],
    "dangal": ["摔跤吧！爸爸", "dangal"],
    # 俄语 → 中文
    "idiismotri": ["自己去看", "comeandsee"],
    # 阿拉伯语 → 中文
    "capharnaum": ["何以为家", "capernaum"],
    # 其他特殊标题
    "leon": ["这个杀手不太冷", "leon"],
    "wall·e": ["机器人总动员", "walle"],
    "psycho": ["惊魂记", "psycho"],
    "rearwindow": ["后窗", "rearwindow"],
    "citylights": ["城市之光", "citylights"],
    "amadeus": ["莫扎特传", "amadeus"],
    "sunsetblvd": ["日落大道", "sunsetboulevard"],
    "spidermannowayhome": ["蜘蛛侠：英雄无归", "spidermannowayhome"],
    "2001aspaceodyssey": ["2001太空漫游", "2001aspaceodyssey"],
    "citizenkane": ["公民凯恩", "citizenkane"],
    "vertigo": ["迷魂记"],
    "northbynorthwest": ["西北偏北", "northbynorthwest"],
    "singinintherain": ["雨中曲", "singin'intherain"],
    "taxidriver": ["出租车司机", "taxidriver"],
    "theapartment": ["公寓春光", "theapartment"],
    "metropolis": ["大都会", "metropolis"],
    "thething": ["怪形", "thething"],
    "ragingbull": ["愤怒的公牛", "ragingbull"],
    "chinatown": ["唐人街", "chinatown"],
    "hamilton": ["汉密尔顿", "hamilton"],
    "somelikeithot": ["热情似火", "somelikeithot"],
    "thegreatescape": ["大逃亡", "thegreatescape"],
    "theelephantman": ["象人", "theelephantman"],
    "thekid": ["寻子遇仙记", "thekid"],
    "thebridgeontheriverkwai": ["桂河大桥", "thebridgeontheriverkwai"],
    "thebiglebowski": ["谋杀绿脚趾", "thebiglebowski"],
    "prisoners": ["囚徒", "prisoners"],
    "fargo": ["冰血暴", "fargo"],
    "groundhogday": ["土拨鼠之日", "groundhogday"],
    "intothewild": ["荒野生存", "intothewild"],
    "jaws": ["大白鲨", "jaws"],
    "rocky": ["洛奇", "rocky"],
    "dialmformurder": ["电话谋杀案", "dialmformurder"],
    "deadpoetssociety": ["死亡诗社", "deadpoetssociety"],
    "thehelp": ["相助", "thehelp"],
    "platoon": ["野战排", "platoon"],
    "theexorcist": ["驱魔人", "theexorcist"],
    "standbyme": ["伴我同行", "standbyme"],
    "thewizardofoz": ["绿野仙踪", "thewizardofoz"],
    "hotelrwanda": ["卢旺达饭店", "hotelrwanda"],
    "thedeerhunter": ["猎鹿人", "thedeerhunter"],
    "beforesunrise": ["爱在黎明破晓前", "beforesunrise"],
    "beforesunset": ["爱在日落黄昏时", "beforesunset"],
    "allabouteve": ["彗星美人", "allabouteve"],
    "thetreasureofthesierramadre": ["碧血金沙", "thetreasureofthesierramadre"],
    "benhur": ["宾虚", "benhur"],
    "gandhi": ["甘地传", "gandhi"],
    "judgmentatnuremberg": ["纽伦堡大审判", "judgmentatnuremberg"],
    "thegoldrush": ["淘金记", "thegoldrush"],
    "theirongiant": ["钢铁巨人", "theirongiant"],
    "theincredibles": ["超人总动员", "theincredibles"],
    "coolhandluke": ["铁窗喋血", "coolhandluke"],
    "inthenameofthefather": ["因父之名", "inthenameofthefather"],
    "thethirdman": ["第三人", "thethirdman"],
    "barrylyndon": ["巴里·林登", "barrylyndon"],
    "network": ["电视台风云", "network"],
    "onthewaterfront": ["码头风云", "onthewaterfront"],
    "aladdin": ["阿拉丁", "aladdin"],
    "thegeneral": ["将军号", "thegeneral"],
    "klaus": ["克劳斯：圣诞节的秘密", "klaus"],
    "lifeofbrian": ["万世魔星", "lifeofbrian"],
    "rebecca": ["蝴蝶梦"],
    "persona": ["假面"],
    "mrsmithgoestowashington": ["史密斯先生到华盛顿", "mrsmithgoestowashington"],
    "ithappenedonenight": ["一夜风流", "ithappenedonenight"],
    "thegrapesofwrath": ["愤怒的葡萄", "thegrapesofwrath"],
    "tobeornottobe": ["你逃我也逃", "tobeornottobe"],
    "dersuuzala": ["德尔苏·乌扎拉", "dersuuzala"],
    "patherpanchali": ["大地之歌", "patherpanchali"],
    "thebestyearsofourlives": ["黄金时代", "thebestyearsofourlives"],
    "sherlockjr": ["福尔摩斯二世", "sherlockjr"],
    "doubleindemnity": ["双重赔偿", "doubleindemnity"],
    "montypythonandtheholygrail": ["巨蟒与圣杯", "montypythonandtheholygrail"],
}


def _get_title_aliases(imdb_title: str) -> list:
    """获取 IMDB 标题的所有别名（中文+英文），用于匹配"""
    norm = _normalize_title(imdb_title)
    if not norm:
        return []
    aliases = _IMDB_TITLE_TRANSLATIONS.get(norm, [])
    return aliases


def _title_contains(a: str, b: str) -> bool:
    """子串包含匹配，要求较短标题至少 2 个字符且长度比 ≥ 50%（防止短串误匹配）

    例: "ran"(3) 在 "legrandbleu"(11) 中 → 3/11=27% < 50% → 拒绝 ✓
        "千与千寻"(4) 在 "千与千寻之神隐"(7) 中 → 4/7=57% ≥ 50% → 允许 ✓
    """
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 2:
        return False  # 单字符标题不允许子串匹配
    if len(longer) > 0 and len(shorter) / len(longer) < 0.5:
        return False  # 短串占比太低，防止如 "ran" 在 "legrandbleu" 中误匹配
    return shorter in longer


def _find_local_match(ranked, local_movies: list):
    """查找与榜单电影匹配的本地电影，返回匹配的 Movie 对象或 None"""
    r_norm = _normalize_title(ranked.title)
    r_year = ranked.year
    r_douban_id = ranked.douban_id if getattr(ranked, 'source', '') != 'imdb_top250' else ""
    # 获取翻译表中的别名（中文+英文）
    aliases = _get_title_aliases(ranked.title)
    alias_norms = [_normalize_title(a) for a in aliases if a]

    for movie in local_movies:
        # 豆瓣 ID 匹配（最可靠）
        if r_douban_id and hasattr(movie, 'douban_url') and movie.douban_url:
            if r_douban_id in movie.douban_url:
                return movie

        m_title = _normalize_title(movie.title)
        m_orig = _normalize_title(movie.original_title) if movie.original_title else ""

        # 标题匹配（区分精确匹配与模糊匹配）
        title_match = False
        exact_match = False
        # 精确匹配优先
        if r_norm and m_title and r_norm == m_title:
            title_match = True
            exact_match = True
        elif r_norm and m_orig and r_norm == m_orig:
            title_match = True
            exact_match = True
        # 子串匹配（要求较短标题至少 2 字符）
        elif r_norm and m_title and _title_contains(r_norm, m_title):
            title_match = True
        elif r_norm and m_orig and _title_contains(r_norm, m_orig):
            title_match = True
        # 翻译别名匹配
        if not title_match:
            for an in alias_norms:
                if an and m_title and an == m_title:
                    title_match = True
                    exact_match = True
                    break
                if an and m_orig and an == m_orig:
                    title_match = True
                    exact_match = True
                    break
                if an and m_title and _title_contains(an, m_title):
                    title_match = True
                    break
                if an and m_orig and _title_contains(an, m_orig):
                    title_match = True
                    break
        if not title_match:
            continue

        # 年份匹配（允许 3 年误差，IMDB 的 datePublished 常为国际发行年份）
        if r_year and movie.year:
            try:
                if abs(int(r_year) - int(movie.year[:4])) <= 3:
                    return movie
            except (ValueError, TypeError):
                return movie  # 无法比较年份时默认匹配
        elif not r_year and not movie.year:
            return movie  # 双方都没有年份信息时接受匹配
        elif exact_match:
            # 精确标题匹配时，即使一方缺少年份也接受
            return movie
        # 非精确匹配 + 一方有年份另一方没有 → 拒绝匹配

    return None


def _fuzzy_match(ranked: RankedMovie, local_movies: list) -> bool:
    """模糊匹配榜单电影与本地电影（返回布尔值）"""
    return _find_local_match(ranked, local_movies) is not None


# ─────────────────── 网页抓取函数 ───────────────────

def _fetch_url(url: str) -> str:
    """通用 URL 请求"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='replace')
    except urllib.error.URLError as e:
        logger.error(f"网络请求失败 {url}: {e}")
        raise


def _clean_html(text: str) -> str:
    """去除 HTML 标签并解码实体"""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return text.strip()


# ─────────────────── 榜单缓存 ───────────────────

_CACHE_PATH = None  # 延迟初始化


def _get_cache_path():
    """获取榜单缓存文件路径"""
    global _CACHE_PATH
    if _CACHE_PATH is None:
        from utils.app_paths import resolve_data_file
        _CACHE_PATH = resolve_data_file("douban_ranking_cache.json")
    return _CACHE_PATH


def save_ranking_cache(top250: List[RankedMovie], chart: List[RankedMovie],
                       imdb_top250: List[RankedMovie] = None) -> bool:
    """将抓取的榜单数据保存到本地缓存（合并模式，不会覆盖其他来源的已有数据）"""
    try:
        from datetime import datetime
        path = _get_cache_path()

        # 加载现有缓存用于合并
        existing = {}
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        data = {
            "timestamp": datetime.now().isoformat(),
        }

        # 合并 top250：有新数据则覆盖，无新数据则保留旧缓存
        if top250:
            data["top250"] = [_movie_to_dict(m) for m in top250]
        else:
            data["top250"] = existing.get("top250", [])

        # 合并 chart
        if chart:
            data["chart"] = [_movie_to_dict(m) for m in chart]
        else:
            data["chart"] = existing.get("chart", [])

        # 合并 imdb_top250
        if imdb_top250 is not None:
            data["imdb_top250"] = [_movie_to_dict(m) for m in imdb_top250]
        else:
            data["imdb_top250"] = existing.get("imdb_top250", [])

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        imdb_count = len(data.get("imdb_top250", []))
        imdb_info = f", IMDB {imdb_count} 部" if imdb_count else ""
        logger.info(f"榜单缓存已保存: Top250 {len(data['top250'])} 部, 热门 {len(data['chart'])} 部{imdb_info} -> {path}")
        return True
    except Exception as e:
        logger.error(f"保存榜单缓存失败: {e}")
        return False


def load_ranking_cache() -> Tuple[List[RankedMovie], List[RankedMovie]]:
    """从本地缓存加载豆瓣榜单数据，失败返回空列表"""
    try:
        path = _get_cache_path()
        if not path.exists():
            return [], []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        top250 = [_dict_to_movie(d, 'top250') for d in data.get('top250', [])]
        chart = [_dict_to_movie(d, 'chart') for d in data.get('chart', [])]
        logger.info(f"从缓存加载榜单: Top250 {len(top250)} 部, 热门 {len(chart)} 部")
        return top250, chart
    except Exception as e:
        logger.error(f"加载榜单缓存失败: {e}")
        return [], []


def load_imdb_cache() -> List[RankedMovie]:
    """从本地缓存加载 IMDB Top250 数据，失败返回空列表"""
    try:
        path = _get_cache_path()
        if not path.exists():
            return []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        imdb = [_dict_to_movie(d, 'imdb_top250') for d in data.get('imdb_top250', [])]
        logger.info(f"从缓存加载 IMDB Top250: {len(imdb)} 部")
        return imdb
    except Exception as e:
        logger.error(f"加载 IMDB 缓存失败: {e}")
        return []


def get_top250_rank_lookup() -> dict:
    """
    构建豆瓣 Top250 排名查询表，供卡片/详情展示角标用。

    Returns:
        dict: { normalized_title: {"rank": int, "total": 250, "source": "douban", "douban_id": str}, ... }
    """
    top250, _ = load_ranking_cache()
    lookup = {}
    for m in top250:
        key = _normalize_title(m.title)
        if key:
            lookup[key] = {"rank": m.rank, "total": len(top250) or 250, "source": "douban", "douban_id": m.douban_id}
        if m.year and key:
            lookup[f"{key}_{m.year}"] = lookup[key]
    return lookup


def get_imdb_top250_rank_lookup() -> dict:
    """
    构建 IMDB Top250 排名查询表，供卡片/详情展示角标用。

    Returns:
        dict: { normalized_title: {"rank": int, "total": 250, "source": "imdb", "imdb_id": str}, ... }
    """
    imdb_movies = load_imdb_cache()
    lookup = {}
    for m in imdb_movies:
        key = _normalize_title(m.title)
        if key:
            lookup[key] = {"rank": m.rank, "total": len(imdb_movies) or 250, "source": "imdb", "imdb_id": m.douban_id}
        if m.year and key:
            lookup[f"{key}_{m.year}"] = lookup[key]
    return lookup


def _movie_to_dict(m: RankedMovie) -> dict:
    return {
        "title": m.title, "year": m.year, "rating": m.rating,
        "douban_id": m.douban_id, "rank": m.rank, "source": m.source,
        "poster_url": m.poster_url, "premiered": m.premiered,
    }


def _dict_to_movie(d: dict, source: str = "top250") -> RankedMovie:
    return RankedMovie(
        title=d.get("title", ""), year=d.get("year", ""),
        rating=float(d.get("rating", 0) or 0), douban_id=d.get("douban_id", ""),
        rank=int(d.get("rank", 0)), source=d.get("source", source),
        poster_url=d.get("poster_url", ""),
        premiered=d.get("premiered", ""),
    )


def fetch_douban_top250(cached_movies: List[RankedMovie] = None) -> List[RankedMovie]:
    """
    抓取豆瓣 Top250 榜单（共 10 页，每页 25 部）

    页面 URL: https://movie.douban.com/top250?start={n}

    cached_movies: 缓存中已有的电影列表，用于合并 premiered 日期（增量更新）
    """
    all_movies: List[RankedMovie] = []

    for page in range(10):
        start = page * 25
        url = f'https://movie.douban.com/top250?start={start}'
        try:
            content = _fetch_url(url)
        except Exception as e:
            logger.error(f"抓取豆瓣 Top250 第{page+1}页失败: {e}")
            continue

        # 每个条目在 <li> 中，包含:
        #   <em>排名</em>
        #   <a href="https://movie.douban.com/subject/{id}/">
        #     <span class="title">片名</span>
        #   </a>
        #   <span class="rating_num">评分</span>
        #   <p>...年份...<br>...</p>

        items = re.findall(
            r'<em[^>]*>\s*(\d+)\s*</em>.*?'
            r'<div\s+class="info">.*?'
            r'<a\s+href="(https?://movie\.douban\.com/subject/\d+/?)".*?>'
            r'(.*?)</a>.*?'
            r'<span\s+class="rating_num"[^>]*>([\d.]+)</span>',
            content, re.DOTALL
        )

        # 构建缓存查询表：douban_id -> RankedMovie（用于合并 premiered 日期）
        cached_lookup = {}
        if cached_movies:
            cached_lookup = {m.douban_id: m for m in cached_movies if m.douban_id and m.source == 'top250'}

        for rank_str, douban_url, title_html, rating_str in items:
            douban_id = re.search(r'/subject/(\d+)', douban_url)
            if not douban_id:
                continue

            # 提取第一个 <span class="title"> 的内容（中文名）
            first_title = re.search(r'<span\s+class="title">([^<]+)</span>', title_html)
            if first_title:
                title = html.unescape(first_title.group(1).strip())
            else:
                title = _clean_html(title_html)

            try:
                rating = float(rating_str)
            except ValueError:
                rating = 0.0

            # 从 <p> 标签中提取年份
            year = ""
            p_match = re.search(
                r'<em>' + re.escape(rank_str) + r'</em>.*?<p>(.*?)</p>',
                content, re.DOTALL
            )
            if p_match:
                year_match = re.search(r'(\d{4})', p_match.group(1))
                if year_match:
                    year = year_match.group(1)

            # 合并缓存的 premiered 日期
            did = douban_id.group(1)
            cached_premiered = ""
            if did in cached_lookup:
                cached_premiered = cached_lookup[did].premiered or ""

            all_movies.append(RankedMovie(
                title=title,
                year=year,
                rating=rating,
                douban_id=did,
                rank=int(rank_str),
                source='top250',
                premiered=cached_premiered,
            ))

    return all_movies


# ─────────────────── douban-cli 工具函数 ───────────────────

_DOUBAN_CLI_MIN_RATING = 7.0  # 豆瓣热门最低评分筛选


def _run_douban_cli(*args: str, timeout: int = 30) -> Optional[dict | list]:
    """调用 douban-cli 并返回解析后的 JSON，失败返回 None"""
    import subprocess
    import shutil
    # 在 Windows 上需要找到 npx 的完整路径（.CMD 文件）
    npx_path = shutil.which("npx") or "npx"
    cmd = [npx_path, "--yes", "@marvae24/douban-cli"] + list(args) + ["--json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        stdout = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
        stderr = result.stderr.decode('utf-8', errors='replace') if isinstance(result.stderr, bytes) else result.stderr
        if result.returncode != 0:
            logger.warning(f"douban-cli 命令失败 ({result.returncode}): {' '.join(args)} {stderr.strip()}")
            return None
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        logger.warning(f"douban-cli 命令超时 ({timeout}s): {' '.join(args)}")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"douban-cli 命令异常: {e}")
        return None


def _parse_pubdate(pubdate_list: list) -> str:
    """从 douban-cli 的 pubdate 字段提取日期，如 '2025-11-27(中国台湾)' → '2025-11-27'"""
    if not pubdate_list:
        return ""
    for entry in pubdate_list:
        m = re.match(r'(\d{4}-\d{2}-\d{2})', str(entry))
        if m:
            return m.group(1)
    return ""


def _fetch_movie_detail(douban_id: str) -> dict:
    """获取单部电影详情（用于并发调用）"""
    detail = _run_douban_cli("movie", douban_id, timeout=20)
    return {"douban_id": douban_id, "detail": detail}


def fetch_douban_chart(cached_movies: List[RankedMovie] = None) -> List[RankedMovie]:
    """
    抓取豆瓣最新热门电影（评分 ≥ 7.0）

    数据源：douban-cli hot（对应 movie.douban.com/explore 最新电影）
    筛选逻辑：客户端过滤评分 ≥ 7.0，并发获取每部电影详情以提取上映日期。

    cached_movies: 缓存中已有的电影列表，用于跳过详情获取（增量更新）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 第一步：获取热门电影列表
    hot_data = _run_douban_cli("hot", "--limit", "50", timeout=30)
    if not hot_data or not isinstance(hot_data, list):
        logger.error("douban-cli hot 返回数据为空")
        return []

    # 第二步：筛选评分 ≥ 7.0 的电影
    candidates = []
    for item in hot_data:
        if not isinstance(item, dict):
            continue
        try:
            rating = float(item.get("rate", 0) or 0)
        except (ValueError, TypeError):
            continue
        if rating < _DOUBAN_CLI_MIN_RATING:
            continue
        candidates.append(item)

    logger.info(f"豆瓣热门: {len(hot_data)} 部中筛选出 {len(candidates)} 部（≥{_DOUBAN_CLI_MIN_RATING}分）")

    if not candidates:
        return []

    # 构建缓存查询表：douban_id -> RankedMovie
    cached_lookup = {}
    if cached_movies:
        cached_lookup = {m.douban_id: m for m in cached_movies if m.douban_id and m.source == 'chart'}

    # 第三步：仅获取缓存中没有的新电影详情
    all_ids = [str(item.get("id", "")) for item in candidates if item.get("id")]
    new_ids = [did for did in all_ids if did and did not in cached_lookup]

    details = {}
    if new_ids:
        logger.info(f"豆瓣热门: {len(new_ids)}/{len(all_ids)} 部为新电影，获取详情")
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_movie_detail, did): did for did in new_ids}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result.get("detail"):
                        details[result["douban_id"]] = result["detail"]
                except Exception as e:
                    logger.warning(f"获取电影详情失败: {e}")
    else:
        logger.info(f"豆瓣热门: 全部 {len(all_ids)} 部均在缓存中，跳过详情获取")

    # 第四步：构建 RankedMovie 列表
    all_movies: List[RankedMovie] = []
    for rank, item in enumerate(candidates, 1):
        douban_id = str(item.get("id", ""))
        title = str(item.get("title", "")).strip()
        if not title or not douban_id:
            continue

        try:
            rating = float(item.get("rate", 0) or 0)
        except (ValueError, TypeError):
            rating = 0.0

        poster_url = str(item.get("cover", ""))

        # 优先使用缓存数据（保留 premiered/year，更新 rating/rank）
        if douban_id in cached_lookup:
            cached = cached_lookup[douban_id]
            all_movies.append(RankedMovie(
                title=title,
                year=cached.year,
                rating=rating,  # 更新评分
                douban_id=douban_id,
                rank=rank,      # 更新排名
                source='chart',
                poster_url=poster_url or cached.poster_url,
                premiered=cached.premiered,
            ))
            continue

        # 从详情中提取上映日期和年份
        detail = details.get(douban_id, {})
        premiered = _parse_pubdate(detail.get("pubdate", []))
        year = str(detail.get("year", "")) if detail else ""
        # 从 premiered 日期中提取年份作为降级
        if not year and premiered and len(premiered) >= 4:
            year = premiered[:4]
        # 再降级：从 hot 列表的 year 字段提取
        if not year:
            year = str(item.get("year", ""))

        all_movies.append(RankedMovie(
            title=title,
            year=year,
            rating=rating,
            douban_id=douban_id,
            rank=rank,
            source='chart',
            poster_url=poster_url,
            premiered=premiered,
        ))

    logger.info(f"豆瓣热门抓取完成: {len(all_movies)} 部电影")
    return all_movies


# ─────────────────── IMDB Top250 抓取 ───────────────────

# GitHub 镜像源 - 详细版（包含投票数，用于 IMDB 加权公式排序）
_IMDB_TOP250_DETAILED_URLS = [
    "https://raw.githubusercontent.com/movie-monk-b0t/top250/master/top250.json",
    "https://raw.githubusercontent.com/movie-monk-b0t/top250/main/top250.json",
]
# GitHub 镜像源 - 精简版（无投票数，作为备选）
_IMDB_TOP250_MIN_URLS = [
    "https://raw.githubusercontent.com/movie-monk-b0t/top250/master/top250_min.json",
    "https://raw.githubusercontent.com/movie-monk-b0t/top250/main/top250_min.json",
]

# IMDB 加权公式参数 (Bayesian rating)
_IMDB_M = 25000   # 最低票数门槛
_IMDB_C = 7.0     # 全库平均评分


def _imdb_weighted_rating(rating: float, votes: int) -> float:
    """IMDB 加权评分公式: WR = (v/(v+m))*R + (m/(v+m))*C"""
    return (votes / (votes + _IMDB_M)) * rating + (_IMDB_M / (votes + _IMDB_M)) * _IMDB_C


def _fix_imdb_title(title: str) -> str:
    """修复 IMDB 标题中的 HTML 实体编码"""
    # &apos; → ', &amp; → &, &#39; → '
    title = title.replace('&apos;', "'").replace('&amp;', '&').replace('&#39;', "'")
    title = html.unescape(title)
    return title


def fetch_imdb_top250(cached_movies: List[RankedMovie] = None) -> List[RankedMovie]:
    """
    抓取 IMDB Top250 榜单

    优先使用详细版 JSON（含投票数），通过 IMDB 加权公式计算真实排名。
    加权公式: WR = (v/(v+m))*R + (m/(v+m))*C，其中 m=25000, C=7.0。

    cached_movies: 缓存中已有的电影列表，用于合并 premiered 日期（增量更新）
    """
    all_movies: List[RankedMovie] = []

    # 构建缓存查询表：imdb_id -> RankedMovie（用于合并 premiered 日期）
    cached_lookup = {}
    if cached_movies:
        cached_lookup = {m.douban_id: m for m in cached_movies if m.douban_id and m.source == 'imdb_top250'}

    # 方案 1: 详细版 JSON（含投票数，可精确排序）
    for url in _IMDB_TOP250_DETAILED_URLS:
        try:
            content = _fetch_url(url)
            data = json.loads(content)
            if not isinstance(data, list):
                continue

            parsed = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get('name', '')).strip()
                if not name:
                    continue
                name = _fix_imdb_title(name)

                # 从 datePublished 提取年份
                date_pub = str(item.get('datePublished', ''))
                year = date_pub[:4] if len(date_pub) >= 4 else ""

                # 评分和投票数
                ar = item.get('aggregateRating', {})
                try:
                    rating = float(ar.get('ratingValue', 0) or 0)
                except (ValueError, TypeError):
                    rating = 0.0
                try:
                    votes = int(ar.get('ratingCount', 0) or 0)
                except (ValueError, TypeError):
                    votes = 0

                # IMDB ID
                imdb_url = str(item.get('url', ''))
                imdb_id_match = re.search(r'/title/(tt\d+)', imdb_url)
                imdb_id = imdb_id_match.group(1) if imdb_id_match else ""

                wr = _imdb_weighted_rating(rating, votes)
                parsed.append((name, year, rating, votes, imdb_id, wr))

            if parsed:
                # 按加权评分降序排列（还原真实 IMDB 排名）
                parsed.sort(key=lambda x: -x[5])
                for rank, (name, year, rating, votes, imdb_id, wr) in enumerate(parsed, 1):
                    all_movies.append(RankedMovie(
                        title=name, year=year, rating=rating,
                        douban_id=imdb_id, rank=rank, source='imdb_top250',
                        premiered=cached_lookup[imdb_id].premiered if imdb_id in cached_lookup else "",
                    ))
                logger.info(f"IMDB Top250 抓取完成: {len(all_movies)} 部电影 (详细版, 加权排序)")
                return all_movies

        except Exception as e:
            logger.warning(f"IMDB Top250 详细版 {url} 抓取失败: {e}")
            continue

    # 方案 2: 精简版 JSON（无投票数，按评分排序）
    for url in _IMDB_TOP250_MIN_URLS:
        try:
            content = _fetch_url(url)
            data = json.loads(content)
            if not isinstance(data, list):
                continue

            parsed = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get('name', '')).strip()
                if not name:
                    continue
                name = _fix_imdb_title(name)
                year = str(item.get('year', ''))
                try:
                    rating = float(item.get('rating', 0) or 0)
                except (ValueError, TypeError):
                    rating = 0.0
                imdb_url = str(item.get('imdb_url', ''))
                imdb_id_match = re.search(r'/title/(tt\d+)', imdb_url)
                imdb_id = imdb_id_match.group(1) if imdb_id_match else ""
                parsed.append((name, year, rating, imdb_id))

            if parsed:
                parsed.sort(key=lambda x: (-x[2], x[0]))
                for rank, (name, year, rating, imdb_id) in enumerate(parsed, 1):
                    all_movies.append(RankedMovie(
                        title=name, year=year, rating=rating,
                        douban_id=imdb_id, rank=rank, source='imdb_top250',
                        premiered=cached_lookup[imdb_id].premiered if imdb_id in cached_lookup else "",
                    ))
                logger.info(f"IMDB Top250 抓取完成: {len(all_movies)} 部电影 (精简版, 评分排序)")
                return all_movies

        except Exception as e:
            logger.warning(f"IMDB Top250 精简版 {url} 抓取失败: {e}")
            continue

    if not all_movies:
        logger.error("IMDB Top250 所有数据源均失败")
    return all_movies


# ─────────────────── 对比函数 ───────────────────

def compare_with_local(ranked_movies: List[RankedMovie],
                       local_movies: list) -> Tuple[List[RankedMovie], List[RankedMovie]]:
    """
    将榜单电影与本地库对比

    Args:
        ranked_movies: 榜单电影列表
        local_movies: 本地电影列表 (List[Movie])

    Returns:
        (owned_movies, missing_movies): 本地已有 / 本地缺失
    """
    owned: List[RankedMovie] = []
    missing: List[RankedMovie] = []

    for rm in ranked_movies:
        if _fuzzy_match(rm, local_movies):
            owned.append(rm)
        else:
            missing.append(rm)

    return owned, missing


# ─────────────────── 后台工作线程 ───────────────────

class RankingFetcher(QThread):
    """
    后台抓取排行榜并对比本地库

    信号:
        progress(str)          - 进度日志
        finished(list, list)   - 完成: (owned, missing)
        error(str)             - 错误信息
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, list)
    error = pyqtSignal(str)

    def __init__(self, local_movies: list, sources: list = None,
                 use_cache: bool = True, parent=None):
        super().__init__(parent)
        self._local_movies = local_movies
        self._sources = sources or ['top250', 'chart']
        self._use_cache = use_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        all_ranked: List[RankedMovie] = []
        top250: List[RankedMovie] = []
        chart: List[RankedMovie] = []
        imdb_top250: List[RankedMovie] = []

        try:
            # 优先从缓存加载（仅在 use_cache=True 且缓存存在时）
            if self._use_cache:
                cached_top250, cached_chart = load_ranking_cache()
                cached_imdb = load_imdb_cache() if 'imdb_top250' in self._sources else []
                if cached_top250 or cached_chart or cached_imdb:
                    self.progress.emit("从本地缓存加载榜单数据...")
                    if 'top250' in self._sources and cached_top250:
                        top250 = cached_top250
                        self.progress.emit(f"  豆瓣Top250: {len(top250)} 部电影（缓存）")
                        all_ranked.extend(top250)
                    if 'chart' in self._sources and cached_chart:
                        chart = cached_chart
                        self.progress.emit(f"  豆瓣热门: {len(chart)} 部电影（缓存）")
                        all_ranked.extend(chart)
                    if 'imdb_top250' in self._sources and cached_imdb:
                        imdb_top250 = cached_imdb
                        self.progress.emit(f"  IMDB Top250: {len(imdb_top250)} 部电影（缓存）")
                        all_ranked.extend(imdb_top250)
                    if all_ranked:
                        self.progress.emit(f"榜单合计: {len(all_ranked)} 部电影")
                        self.progress.emit("正在与本地电影库对比...")
                        owned, missing = compare_with_local(all_ranked, self._local_movies)
                        self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")
                        self.finished.emit(owned, missing)
                        return

            # 缓存不可用或强制刷新：从网络抓取（增量模式）
            # 加载旧缓存用于增量对比（已有电影跳过详情获取，仅更新评分/排名）
            all_cached: List[RankedMovie] = []
            if not self._use_cache:
                cached_top250_old, cached_chart_old = load_ranking_cache()
                cached_imdb_old = load_imdb_cache() if 'imdb_top250' in self._sources else []
                all_cached = cached_top250_old + cached_chart_old + cached_imdb_old

            if 'top250' in self._sources:
                self.progress.emit("正在抓取豆瓣 Top250 榜单...")
                top250 = fetch_douban_top250(cached_movies=all_cached)
                self.progress.emit(f"  Top250 获取完成: {len(top250)} 部电影")
                all_ranked.extend(top250)

                if self._cancelled:
                    return

            if 'chart' in self._sources:
                self.progress.emit("正在抓取豆瓣近期热门榜单...")
                chart = fetch_douban_chart(cached_movies=all_cached)
                self.progress.emit(f"  热门榜单获取完成: {len(chart)} 部电影")
                all_ranked.extend(chart)

                if self._cancelled:
                    return

            if 'imdb_top250' in self._sources:
                self.progress.emit("正在抓取 IMDB Top250 榜单...")
                imdb_top250 = fetch_imdb_top250(cached_movies=all_cached)
                self.progress.emit(f"  IMDB Top250 获取完成: {len(imdb_top250)} 部电影")
                all_ranked.extend(imdb_top250)

                if self._cancelled:
                    return

            # 保存到缓存
            if top250 or chart:
                save_ranking_cache(top250, chart, imdb_top250 if imdb_top250 else None)
            elif imdb_top250:
                # 只有 IMDB 数据时也保存（合并到现有缓存）
                save_ranking_cache([], [], imdb_top250)

            self.progress.emit(f"榜单合计: {len(all_ranked)} 部电影")
            self.progress.emit("正在与本地电影库对比...")

            owned, missing = compare_with_local(all_ranked, self._local_movies)
            self.progress.emit(f"对比完成: 本地已有 {len(owned)} 部, 缺失 {len(missing)} 部")

            self.finished.emit(owned, missing)

        except Exception as e:
            logger.exception("抓取榜单失败")
            self.error.emit(str(e))
