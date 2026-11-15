// 电影海报卡片 — 暗色放映厅风格
import { memo, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieListItem } from '../../types/api';
import { preferredRating, ratingNames } from '../../utils/movieDisplay';
import { TechBadges } from './TechBadges';

interface Props {
  movie: MovieListItem;
  width: number;
  height: number;
  scale: number;
  selected: boolean;
  posterVersion?: number;
  onSelect: (movie: MovieListItem) => void;
  onContextMenu: (movie: MovieListItem, x: number, y: number) => void;
}

export const MovieCard = memo(function MovieCard({
  movie,
  width,
  height,
  scale,
  selected,
  posterVersion = 0,
  onSelect,
  onContextMenu,
}: Props) {
  const [failedUrl, setFailedUrl] = useState('');
  const w = Math.round(width * (scale / 100));
  const h = Math.round(height * (scale / 100));

  const posterUrl = `${movieApi.posterUrl(movie.id, w, h, 'cover')}&v=${posterVersion}`;
  const showImage = movie.has_poster && failedUrl !== posterUrl;
  const score = preferredRating(movie);

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
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(movie); } }}
    >
      <div
        className={`relative h-full w-full overflow-hidden rounded-lg bg-ink-800 ${
          selected ? 'ring-2 ring-cinema-500' : 'ring-1 ring-ink-700'
        }`}
      >
        {showImage ? (
          <img
            src={posterUrl}
            alt={movie.title}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
            onError={() => setFailedUrl(posterUrl)}
            draggable={false}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center p-2 text-center text-xs text-ink-400">
            {movie.title}
          </div>
        )}

        {/* 顶部评分 */}
        {score.value > 0 && (
          <span title={ratingNames[score.source as keyof typeof ratingNames]} className="rating-badge absolute left-1.5 top-1.5 rounded bg-black/75 px-1.5 py-0.5 text-xs text-gold">
            ★ {score.value.toFixed(1)}
          </span>
        )}

        {/* 底部标题条 */}
        <div className="absolute inset-x-0 bottom-0 bg-black/75 px-2 py-2">
          <div className="truncate text-xs font-medium text-ink-50">
            {movie.title}
          </div>
          <div className="flex items-center gap-1.5">
            {movie.year && (
              <span className="font-mono text-2xs text-ink-300">{movie.year}</span>
            )}
            <TechBadges resolution={movie.resolution} hdrType={movie.hdr_type} compact />
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
