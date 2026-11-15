import type { MovieListItem } from '../types/api';
export const ratingOrder = ['douban', 'imdb', 'tmdb'] as const;
export const ratingNames = { douban: '豆瓣', imdb: 'IMDb', tmdb: 'TMDB' };
export function preferredRating(movie: MovieListItem) {
  for (const source of ratingOrder) {
    const value = Number(movie.ratings?.[source] || 0);
    if (value > 0 && value <= 10) return { source, value };
  }
  if ((ratingOrder as readonly string[]).includes(movie.rating_source) && movie.rating > 0 && movie.rating <= 10)
    return {source: movie.rating_source, value: movie.rating};
  return { source: '', value: 0 };
}
export function localPlayUrl(movie: MovieListItem) {
  return `moviewall://play?path=${encodeURIComponent(movie.video_path)}`;
}
