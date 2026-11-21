import { Layers } from 'lucide-react';
import type { MovieListItem } from '../../types/api';
import { quarkSearchUrl } from '../../utils/movieDisplay';
import { ActionIcon } from '../ActionIcon';
import { BilibiliActions } from './BilibiliActions';
import { useSeriesListing } from './useSeriesListing';

export function SeriesShortcuts({ movie, movies, onSelect, onSeriesClick }: {
  movie: MovieListItem;
  movies: MovieListItem[];
  onSelect: (id: string) => void;
  onSeriesClick: (name: string) => void;
}) {
  const {items} = useSeriesListing(movie.set_name, movies);
  const members = items.length ? items : [{...movie, movie_id: movie.id}];
  return <section className="space-y-2" aria-label="系列各部">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold"><ActionIcon icon={Layers} />{movie.set_name}</h3>
      <button type="button" className="text-xs text-ink-300 hover:underline" onClick={() => onSeriesClick(movie.set_name)}>筛选此系列</button>
    </div>
    <ul className="flex flex-wrap gap-2">
      {members.map(part => <li key={part.movie_id || part.tmdb_id}>
        {part.movie_id === movie.id ? <span aria-current="true" className="btn btn-active border border-ink-600">{part.title}</span>
          : part.movie_id ? <button type="button" className="btn border divider" onClick={() => onSelect(part.movie_id!)}>{part.title}</button>
          : <div className="flex flex-wrap items-center gap-x-2 rounded-md border divider px-2 py-1.5 text-xs">
            <span>{part.title} <span className="text-ink-400">未入库</span></span>
            <a className="hover:underline" href={quarkSearchUrl(part.title)} target="_blank" rel="noopener noreferrer">夸克盘搜</a>
            <BilibiliActions playOnly title={part.title} originalTitle={part.original_title} year={part.year} />
          </div>}
      </li>)}
    </ul>
  </section>;
}
