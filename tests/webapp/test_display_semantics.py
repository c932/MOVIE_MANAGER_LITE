from models.movie import Movie
from utils.genres import localize_genres
from movie_service.store import movie_to_dto


def test_genres_merge_and_rating_priority():
    assert localize_genres(['Action', '动作', 'Science Fiction', '科幻', 'TV Movie']) == ['动作', '科幻', '电视电影']
    movie = Movie(genres=['Drama', '剧情', 'Adventure'], ratings={'tmdb': 9, 'imdb': 8, 'douban': 7}, rating=9, rating_source='tmdb')
    data = movie_to_dto(movie)
    assert data['genres'] == ['剧情', '冒险']
    assert data['rating'] == 7 and data['rating_source'] == 'douban'
    movie.ratings.pop('douban')
    assert movie_to_dto(movie)['rating'] == 8
