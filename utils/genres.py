"""旧 NFO/不同来源的类型名称归并；不依赖 Qt。"""
import re

_NAMES = {
    'action': '动作', 'adventure': '冒险', 'animation': '动画', 'comedy': '喜剧',
    'crime': '犯罪', 'documentary': '纪录片', 'drama': '剧情', 'family': '家庭',
    'fantasy': '奇幻', 'history': '历史', 'horror': '恐怖', 'music': '音乐',
    'mystery': '悬疑', 'romance': '爱情', 'science fiction': '科幻', 'sci-fi': '科幻',
    'science-fiction': '科幻', 'scifi': '科幻', 'tv movie': '电视电影', 'thriller': '惊悚',
    'war': '战争', 'western': '西部', 'biography': '传记', 'sport': '运动',
    'sports': '运动', 'musical': '歌舞', 'short': '短片', 'film-noir': '黑色电影',
    'reality-tv': '真人秀', 'reality': '真人秀', 'talk-show': '脱口秀', 'talk': '脱口秀',
    'news': '新闻', 'adult': '成人', 'kids': '儿童', 'soap': '肥皂剧',
    'action & adventure': '动作/冒险', 'sci-fi & fantasy': '科幻/奇幻', 'war & politics': '战争/政治',
    '记录片': '纪录片', '紀錄片': '纪录片', '動作': '动作', '冒險': '冒险', '動畫': '动画',
    '喜劇': '喜剧', '戰爭': '战争', '驚悚': '惊悚', '懸疑': '悬疑', '愛情': '爱情',
}


def localize_genres(values: list[str]) -> list[str]:
    result = []
    for raw in values or []:
        value = str(raw).strip()
        for genre in re.split(r'[/、|]', _NAMES.get(value.casefold(), value)):
            genre = _NAMES.get(genre.strip().casefold(), genre.strip())
            if genre and genre not in result:
                result.append(genre)
    return result


def preferred_rating(movie) -> tuple[float, str]:
    for source in ('douban', 'imdb', 'tmdb'):
        try:
            value = float(movie.ratings.get(source, 0))
        except (ValueError, TypeError):
            continue
        if 0 < value <= 10:
            return value, source
    if movie.rating_source in {'douban', 'imdb', 'tmdb'} and 0 < float(movie.rating or 0) <= 10:
        return float(movie.rating), movie.rating_source
    return 0., ''
