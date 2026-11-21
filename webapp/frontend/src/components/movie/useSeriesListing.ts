import { useEffect, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieListItem, SeriesListing, SeriesMovie } from '../../types/api';
import { preferredRating } from '../../utils/movieDisplay';

export function localSeriesMovie(movie: MovieListItem): SeriesMovie {
  const rating = preferredRating(movie);
  return {title: movie.title, original_title: movie.original_title, year: movie.year,
    premiered: movie.premiered, tmdb_id: movie.tmdb_id, rating: rating.value, rating_source: rating.source,
    poster_url: '', movie_id: movie.id, plot: movie.plot};
}

export function useSeriesListing(name: string, movies: MovieListItem[]) {
  const [result, setResult] = useState<{name: string; listing?: SeriesListing} | null>(null);
  useEffect(() => {
    if (!name) return;
    let active = true;
    movieApi.series(name).then(
      listing => { if (active) setResult({name, listing}); },
      () => { if (active) setResult({name}); },
    );
    return () => { active = false; };
  }, [name]);

  const current = result?.name === name ? result : null;
  const items = current?.listing?.items ?? movies.filter(movie => name && movie.set_name === name)
    .sort((a, b) => (a.premiered || a.year || '9999').localeCompare(b.premiered || b.year || '9999'))
    .map(localSeriesMovie);
  return {items, source: current?.listing?.source, loading: !!name && !current};
}
