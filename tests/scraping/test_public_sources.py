import json

from scraper import public_sources


def test_douban_public_search_parses_movie_card(monkeypatch):
    sample = """Title: 搜索: 大话西游

[![Image 1](https://img9.doubanio.com/poster.webp)](https://www.douban.com/link2/?url=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F1292213%2F)

### [电影][大话西游之大圣娶亲](https://www.douban.com/link2/?url=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F1292213%2F)

9.2(1737777人评价)原名:西遊記大結局之仙履奇緣 / 刘镇伟 / 周星驰 / 1995

至尊宝被月光宝盒带回到五百年前，遇见紫霞仙子。
"""
    monkeypatch.setattr(public_sources, "fetch_text", lambda *_args, **_kwargs: sample)
    result = public_sources.douban_public_search("大话西游", "1995")
    assert result is not None
    assert result.title == "大话西游之大圣娶亲"
    assert result.original_title == "西遊記大結局之仙履奇緣"
    assert result.rating == 9.2
    assert result.subject_id == "1292213"
    assert result.directors == ["刘镇伟"]
    assert result.actors == ["周星驰"]
    assert result.plot == "至尊宝被月光宝盒带回到五百年前，遇见紫霞仙子。"


def test_tmdb_public_details_parses_movie_json_ld(monkeypatch):
    data = {
        "@type": "Movie",
        "name": "大话西游之大圣娶亲",
        "description": "中文剧情",
        "datePublished": "1995-02-04",
        "genre": ["喜剧", "爱情"],
        "countryOfOrigin": [{"name": "中国香港"}],
        "director": [{"name": "刘镇伟"}],
        "actor": [{"name": "周星驰"}],
        "image": "https://image.tmdb.org/t/p/w500/poster.jpg",
        "sameAs": ["https://www.imdb.com/title/tt0114996"],
        "aggregateRating": {"ratingValue": 8.1, "ratingCount": 300},
    }
    page = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"
    monkeypatch.setattr(public_sources, "fetch_text", lambda *_args, **_kwargs: page)
    result = public_sources.tmdb_public_details("21835")
    assert result["title"] == "大话西游之大圣娶亲"
    assert result["plot"] == "中文剧情"
    assert result["genres"] == ["喜剧", "爱情"]
    assert result["actors"][0]["name"] == "周星驰"
    assert result["imdb_id"] == "tt0114996"
    assert result["tmdb_rating"] == 8.1
