import { Layers } from 'lucide-react';
import type { SeriesMovie } from '../../types/api';
import { ActionIcon } from '../ActionIcon';

export function SeriesShortcuts({ seriesName, items, currentId, onSelect, onSeriesClick }: {
  seriesName: string;
  items: SeriesMovie[];
  currentId: string;
  onSelect: (part: SeriesMovie) => void;
  onSeriesClick?: (name: string) => void;
}) {
  return <section className="space-y-2" aria-label="系列各部">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold"><ActionIcon icon={Layers} />{seriesName}</h3>
      {onSeriesClick && <button type="button" className="text-xs text-ink-300 hover:underline" onClick={() => onSeriesClick(seriesName)}>筛选此系列</button>}
    </div>
    <ul className="flex flex-wrap gap-2">
      {items.map(part => {
        const active = part.movie_id === currentId || part.tmdb_id === currentId;
        return <li key={part.movie_id || part.tmdb_id}>
          <button type="button" aria-current={active ? 'true' : undefined}
            className={`btn border divider ${active ? 'btn-active' : ''}`}
            onClick={() => onSelect(part)}>
            {part.title}{!part.movie_id && <span className="ml-1 text-xs text-ink-400">未入库</span>}
          </button>
        </li>;
      })}
    </ul>
  </section>;
}
