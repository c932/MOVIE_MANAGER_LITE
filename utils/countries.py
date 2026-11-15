"""本地国家地区名称规范化，不依赖在线翻译或 Qt。未知名称原样保留。"""
from __future__ import annotations


# TMDB 的 production_countries.name 不随 language 参数翻译。
_COUNTRIES = (
    ('US', '美国', 'United States of America', 'United States', 'USA'),
    ('GB', '英国', 'United Kingdom', 'UK', 'Great Britain'),
    ('CN', '中国大陆', 'China', 'Mainland China'),
    ('HK', '中国香港', 'Hong Kong'), ('TW', '中国台湾', 'Taiwan'),
    ('MO', '中国澳门', 'Macao', 'Macau'),
    ('AU', '澳大利亚', 'Australia'), ('MX', '墨西哥', 'Mexico'),
    ('ZA', '南非', 'South Africa'), ('CA', '加拿大', 'Canada'),
    ('FR', '法国', 'France'), ('DE', '德国', 'Germany'),
    ('JP', '日本', 'Japan'), ('KR', '韩国', 'South Korea', 'Korea, Republic of'),
    ('KP', '朝鲜', 'North Korea'), ('IN', '印度', 'India'),
    ('IT', '意大利', 'Italy'), ('ES', '西班牙', 'Spain'),
    ('RU', '俄罗斯', 'Russia', 'Russian Federation'),
    ('NZ', '新西兰', 'New Zealand'), ('IE', '爱尔兰', 'Ireland'),
    ('BE', '比利时', 'Belgium'), ('NL', '荷兰', 'Netherlands'),
    ('CH', '瑞士', 'Switzerland'), ('AT', '奥地利', 'Austria'),
    ('SE', '瑞典', 'Sweden'), ('NO', '挪威', 'Norway'),
    ('DK', '丹麦', 'Denmark'), ('FI', '芬兰', 'Finland'),
    ('IS', '冰岛', 'Iceland'), ('PL', '波兰', 'Poland'),
    ('CZ', '捷克', 'Czech Republic', 'Czechia'),
    ('HU', '匈牙利', 'Hungary'), ('RO', '罗马尼亚', 'Romania'),
    ('BG', '保加利亚', 'Bulgaria'), ('GR', '希腊', 'Greece'),
    ('PT', '葡萄牙', 'Portugal'), ('LU', '卢森堡', 'Luxembourg'),
    ('MT', '马耳他', 'Malta'), ('UA', '乌克兰', 'Ukraine'),
    ('RS', '塞尔维亚', 'Serbia'), ('HR', '克罗地亚', 'Croatia'),
    ('SK', '斯洛伐克', 'Slovakia'), ('SI', '斯洛文尼亚', 'Slovenia'),
    ('EE', '爱沙尼亚', 'Estonia'), ('LV', '拉脱维亚', 'Latvia'),
    ('LT', '立陶宛', 'Lithuania'), ('TR', '土耳其', 'Turkey', 'Türkiye'),
    ('TH', '泰国', 'Thailand'), ('SG', '新加坡', 'Singapore'),
    ('MY', '马来西亚', 'Malaysia'), ('ID', '印度尼西亚', 'Indonesia'),
    ('PH', '菲律宾', 'Philippines'), ('VN', '越南', 'Vietnam', 'Viet Nam'),
    ('KH', '柬埔寨', 'Cambodia'), ('MM', '缅甸', 'Myanmar'),
    ('NP', '尼泊尔', 'Nepal'), ('PK', '巴基斯坦', 'Pakistan'),
    ('BD', '孟加拉国', 'Bangladesh'), ('LK', '斯里兰卡', 'Sri Lanka'),
    ('IR', '伊朗', 'Iran', 'Iran, Islamic Republic of'),
    ('IL', '以色列', 'Israel'), ('AE', '阿联酋', 'United Arab Emirates'),
    ('SA', '沙特阿拉伯', 'Saudi Arabia'), ('QA', '卡塔尔', 'Qatar'),
    ('LB', '黎巴嫩', 'Lebanon'), ('JO', '约旦', 'Jordan'),
    ('EG', '埃及', 'Egypt'), ('MA', '摩洛哥', 'Morocco'),
    ('TN', '突尼斯', 'Tunisia'), ('NG', '尼日利亚', 'Nigeria'),
    ('KE', '肯尼亚', 'Kenya'), ('BR', '巴西', 'Brazil'),
    ('AR', '阿根廷', 'Argentina'), ('CL', '智利', 'Chile'),
    ('CO', '哥伦比亚', 'Colombia'), ('PE', '秘鲁', 'Peru'),
    ('VE', '委内瑞拉', 'Venezuela'), ('CU', '古巴', 'Cuba'),
    ('UY', '乌拉圭', 'Uruguay'), ('SU', '苏联', 'Soviet Union'),
    ('XC', '捷克斯洛伐克', 'Czechoslovakia'),
    ('XW', '西德', 'West Germany'), ('DD', '东德', 'East Germany'),
    ('YU', '南斯拉夫', 'Yugoslavia'),
)
_NAMES = {alias.casefold(): row[1] for row in _COUNTRIES for alias in (row[0], *row[2:])}


def localize_country(name: str, code: str = '') -> str:
    """优先按 ISO 代码转换；保留已有中文及未知名称。"""
    return _NAMES.get(code.strip().casefold(), _NAMES.get(name.strip().casefold(), name.strip()))


def localize_countries(names: list[str]) -> list[str]:
    return list(dict.fromkeys(localize_country(name) for name in names if name.strip()))
