import type { MovieListItem } from '../types/api';
export const ratingOrder = ['douban', 'imdb', 'tmdb'] as const;
export const ratingNames = { douban: '豆瓣', imdb: 'IMDb', tmdb: 'TMDB' };

export function ratingForSource(movie: Pick<MovieListItem, 'ratings'>, source: typeof ratingOrder[number]) {
  const score = Number(movie.ratings?.[source]);
  if (score > 0 && score <= 10) return score;
  if (source === 'tmdb') {
    // 兼容旧 NFO 中 tinyMediaManager 使用的评分来源名。
    const legacyScore = Number(movie.ratings?.themoviedb);
    if (legacyScore > 0 && legacyScore <= 10) return legacyScore;
  }
  return 0;
}

export function preferredRating(movie: MovieListItem) {
  for (const source of ratingOrder) {
    const value = ratingForSource(movie, source);
    if (value > 0) return { source, value };
  }
  if ((ratingOrder as readonly string[]).includes(movie.rating_source) && movie.rating > 0 && movie.rating <= 10)
    return {source: movie.rating_source, value: movie.rating};
  return { source: '', value: 0 };
}
export function localPlayUrl(movie: MovieListItem) {
  return `moviewall://play?path=${encodeURIComponent(movie.video_path)}`;
}

export function quarkSearchUrl(title: string) {
  return `https://www.zhongchuangwl.com/s/${encodeURIComponent(title)}/`;
}
