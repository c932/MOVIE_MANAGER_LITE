from scraper import douban_ranking


def test_fetch_douban_top250_public_parses_entries(monkeypatch):
    sample = """Title: 豆瓣电影 Top 250

1.   _1_[![Image 1: 肖申克的救赎](https://img3.doubanio.com/poster.webp)](https://movie.douban.com/subject/1292052/)

导演: 弗兰克·德拉邦特 Frank Darabont 主演: 蒂姆·罗宾斯 Tim Robbins /...  
 1994/美国/犯罪 剧情

9.7 3366657人评价

希望让人自由。  
2.   _2_[![Image 2: 霸王别姬](https://img3.doubanio.com/poster.webp)](https://movie.douban.com/subject/1291546/)

导演: 陈凯歌 Kaige Chen 主演: 张国荣 Leslie Cheung / 张丰毅 Fengyi Zha...  
 1993/中国大陆 中国香港/剧情 爱情 同性

9.6 2467173人评价

风华绝代。  
"""
    monkeypatch.setattr("scraper.public_sources.fetch_text", lambda *_args, **_kwargs: sample)
    result = douban_ranking.fetch_douban_top250_public()
    assert len(result) == 2
    assert result[0].title == "肖申克的救赎"
    assert result[0].douban_id == "1292052"
    assert result[0].rating == 9.7
    assert result[0].plot == "希望让人自由。"
    assert result[0].directors == ["弗兰克·德拉邦特 Frank Darabont"]
    assert result[0].actors == ["蒂姆·罗宾斯 Tim Robbins"]
    assert result[0].genres == ["犯罪", "剧情"]
    assert result[0].countries == ["美国"]
