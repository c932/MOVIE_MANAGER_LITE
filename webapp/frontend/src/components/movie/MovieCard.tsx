// 电影海报卡片 — 暗色放映厅风格
import { memo, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieListItem } from '../../types/api';

interface Props {
  movie: MovieListItem;
  width: number;
  height: number;
  scale: number;
  selected: boolean;
  onSelect: (movie: MovieListItem) => void;
  onContextMenu: (movie: MovieListItem, x: number, y: number) => void;
}

export const MovieCard = memo(function MovieCard({
  movie,
  width,
  height,
  scale,
  selected,
  onSelect,
  onContextMenu,
}: Props) {
  const [imgFailed, setImgFailed] = useState(false);
  const w = Math.round(width * (scale / 100));
  const h = Math.round(height * (scale / 100));

  const showImage = movie.has_poster && !imgFailed;

  return (
    <div
      className="poster-card relative cursor-pointer select-none"
      style={{ width: w, height: h }}
      onClick={() => onSelect(movie)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(movie, e.clientX, e.clientY);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(movie)}
    >
      <div
        className={`relative h-full w-full overflow-hidden rounded-lg bg-ink-800 ${
          selected ? 'ring-2 ring-cinema-500' : 'ring-1 ring-ink-700'
        }`}
      >
        {showImage ? (
          <img
            src={movieApi.posterUrl(movie.id, w, h, 'cover')}
            alt={movie.title}
            loading="lazy"
            className="h-full w-full object-cover"
            onError={() => setImgFailed(true)}
            draggable={false}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center p-2 text-center text-xs text-ink-400">
            {movie.title}
          </div>
        )}

        {/* 顶部评分 */}
        {movie.rating > 0 && (
          <span className="rating-badge absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs text-gold backdrop-blur-sm">
            {movie.rating.toFixed(1)}
          </span>
        )}

        {/* 底部标题条 */}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/50 to-transparent px-2 pb-1.5 pt-6">
          <div className="truncate text-xs font-medium text-ink-50">
            {movie.title}
          </div>
          <div className="flex items-center gap-1.5">
            {movie.year && (
              <span className="font-mono text-2xs text-ink-300">{movie.year}</span>
            )}
            {movie.resolution && (
              <span className="rounded bg-white/10 px-1 font-mono text-2xs text-ink-200">
                {movie.resolution}
              </span>
            )}
          </div>
        </div>

        {/* 收藏角标 */}
        {movie.favorite && (
          <span className="absolute right-1.5 top-1.5 text-sm text-gold" title="已收藏">
            ★
          </span>
        )}
        {/* 已观看角标 */}
        {movie.watched && (
          <span className="absolute bottom-1.5 right-1.5 text-2xs text-green-400">
            ✓
          </span>
        )}
      </div>
    </div>
  );
});