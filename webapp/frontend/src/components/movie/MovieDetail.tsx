// 电影详情面板 — 右侧上方，展示选中电影的完整信息
import { useState } from 'react';
import { CircleCheck, Eye, ExternalLink, FilePenLine, Image, Layers, Star, StarHalf, Trash2 } from 'lucide-react';
import { ActionIcon } from '../ActionIcon';
import { movieApi } from '../../api/client';
import type { MovieListItem } from '../../types/api';
import { ratingOrder, ratingNames } from '../../utils/movieDisplay';
import { LocalPlayback } from './LocalPlayback';
import { TechBadges } from './TechBadges';
import { BilibiliActions } from './BilibiliActions';

interface Props {
  movie: MovieListItem | null;
  onUpdated: (movie: MovieListItem) => void;
  onDeleted: (id: string) => void;
  onSeriesClick: (setName: string) => void;
  onRefreshPoster: (id: string) => void;
  onEditFields: (movie: MovieListItem) => void;
}

export function MovieDetail({
  movie,
  onUpdated,
  onDeleted,
  onSeriesClick,
  onRefreshPoster,
  onEditFields,
}: Props) {
  const [posterVersion, setPosterVersion] = useState(0);
  const [ratingInput, setRatingInput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  if (!movie) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-ink-400">
        选择一部电影查看详情
      </div>
    );
  }

  const posterW = 280;
  const posterH = 420;
  const posterUrl = movie.has_poster
    ? `${movieApi.posterUrl(movie.id, posterW, posterH, 'contain')}&v=${posterVersion}`
    : null;

  const toggleWatched = async () => {
    const updated = await movieApi.setWatched(movie.id, !movie.watched);
    onUpdated(updated);
  };

  const toggleFavorite = async () => {
    const updated = await movieApi.setFavorite(movie.id, !movie.favorite);
    onUpdated(updated);
  };

  const submitRating = async () => {
    const r = parseFloat(ratingInput);
    if (isNaN(r) || r < 0 || r > 10) { setError('请输入 0–10 分'); return; }
    const updated = await movieApi.setRating(movie.id, r);
    onUpdated(updated);
    setRatingInput('');
  };

  const handleRefreshPoster = async () => {
    await movieApi.invalidatePoster(movie.id);
    setPosterVersion((v) => v + 1);
    onRefreshPoster(movie.id);
  };

  const handleDelete = async () => {
    onDeleted(movie.id);
  };

  const ratingSources = ratingOrder.map(source => ({label: ratingNames[source], value: Number(movie.ratings?.[source] || 0)}));

  return (
    <div className="flex h-full gap-4 overflow-y-auto p-4 max-sm:flex-col">
      {/* 左：海报 */}
      <div className="shrink-0">
        {posterUrl ? (
          <img
            src={posterUrl}
            alt={movie.title}
            className="rounded-lg shadow-2xl ring-1 ring-ink-700"
            style={{ width: 'min(28vw, 220px)', aspectRatio: '2/3', objectFit: 'contain' }}
            draggable={false}
          />
        ) : (
          <div
            className="flex items-center justify-center rounded-lg bg-ink-800 text-sm text-ink-400 ring-1 ring-ink-700"
            style={{ width: posterW, height: posterH }}
          >
            无海报
          </div>
        )}
      </div>

      {/* 右：信息 */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {error && <p role="alert" className="text-red-400">{error}</p>}
        {/* 标题 */}
        <div>
          <h2 className="text-xl font-semibold text-ink-50">{movie.title}</h2>
          {movie.original_title && movie.original_title !== movie.title && (
            <p className="text-sm text-ink-300">{movie.original_title}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-300">
            {movie.year && <span>{movie.year}</span>}
            {movie.runtime && <span>{movie.runtime} 分钟</span>}
            {movie.file_size && <span>{movie.file_size}</span>}
          </div>
          <div className="mt-3"><TechBadges resolution={movie.resolution} hdrType={movie.hdr_type} /></div>
        </div>

        {/* 评分卡片 */}
        {ratingSources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {ratingSources.map((r) => (
              <div
                key={r.label}
                className="flex items-center gap-1.5 rounded-lg bg-ink-800 px-3 py-1.5"
              >
                {['TMDB', 'IMDb', '豆瓣'].includes(r.label) ? <img className="h-5 w-14 object-contain" alt={r.label} src={`/logo/${r.label === '豆瓣' ? 'douban.png' : r.label === 'IMDb' ? 'imdb.png' : 'tmdb.jpg'}`} /> : <span className="text-2xs text-ink-300">{r.label}</span>}
                <span className="font-mono text-sm font-semibold text-gold">
                  {r.value > 0 ? r.value.toFixed(1) : '—'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 榜单排名 */}
        {movie.rank && (movie.rank.douban_top250 || movie.rank.imdb_top250) && (
          <div className="flex gap-2">
            {movie.rank.douban_top250 && (
              <span className="rounded-full bg-cinema-800/40 px-2.5 py-1 text-xs text-cinema-400">
                豆瓣 Top250 #{movie.rank.douban_top250}
              </span>
            )}
            {movie.rank.imdb_top250 && (
              <span className="rounded-full bg-ink-700 px-2.5 py-1 text-xs text-gold">
                IMDb Top250 #{movie.rank.imdb_top250}
              </span>
            )}
          </div>
        )}

        {/* 标签行 */}
        <div className="flex flex-wrap gap-1.5">
          {movie.genres.map((g) => (
            <span key={g} className="tag">
              {g}
            </span>
          ))}
          {movie.countries.map((c) => (
            <span key={c} className="tag">
              {c}
            </span>
          ))}
        </div>

        {/* 简介 */}
        {movie.plot && (
          <p className="text-sm leading-relaxed text-ink-200">{movie.plot}</p>
        )}

        {/* 导演/演员 */}
        <div className="space-y-1 text-xs">
          {movie.directors.length > 0 && (
            <div>
              <span className="text-ink-400">导演：</span>
              <span className="text-ink-200">{movie.directors.join(' / ')}</span>
            </div>
          )}
          {movie.actors.length > 0 && (
            <div>
              <span className="text-ink-400">主演：</span>
              <span className="text-ink-200">
                {movie.actors.slice(0, 8).map((a) => a.name).join(' / ')}
              </span>
            </div>
          )}
        </div>

        {/* 系列电影 */}
        {movie.set_name && (
          <button
            className="btn w-fit"
            onClick={() => onSeriesClick(movie.set_name)}
          >
            <ActionIcon icon={Layers} /> 系列：{movie.set_name}
          </button>
        )}

        {/* 按钮栏 */}
        <div className="movie-detail-actions mt-auto flex flex-wrap items-center gap-1.5 border-t divider pt-3">
          {movie.video_path && <LocalPlayback movie={movie}/>}
          <BilibiliActions title={movie.title} originalTitle={movie.original_title} year={movie.year}/>
          <button
            className={`btn ${movie.watched ? 'btn-active' : ''}`}
            onClick={() => run(toggleWatched)} disabled={busy}
          >
            <ActionIcon icon={movie.watched ? CircleCheck : Eye} /> {movie.watched ? '已观看' : '标记观看'}
          </button>
          <button
            className={`btn ${movie.favorite ? 'btn-active text-gold' : ''}`}
            onClick={() => run(toggleFavorite)} disabled={busy}
          >
            <ActionIcon icon={Star} className={movie.favorite ? 'fill-current' : ''} /> {movie.favorite ? '已收藏' : '收藏'}
          </button>

          {/* 评分输入 */}
          <div className="flex items-center gap-1">
            <input
              className="input w-16 py-1 text-center"
              type="number"
              min={0}
              max={10}
              step={0.5}
              placeholder={movie.user_rating > 0 ? movie.user_rating.toFixed(1) : '评分'}
              value={ratingInput}
              onChange={(e) => setRatingInput(e.target.value)}
              aria-label="我的评分" onKeyDown={(e) => e.key === 'Enter' && run(submitRating)}
            />
            <button className="btn" disabled={busy} onClick={() => run(submitRating)} title="0-10 分">
              <ActionIcon icon={StarHalf} /> 评分
            </button>
          </div>

          <button className="btn" disabled={busy} onClick={() => run(handleRefreshPoster)} title="刷新后端保存的海报副本">
            <ActionIcon icon={Image} /> 更新海报
          </button>
          <button className="btn" onClick={() => onEditFields(movie)}>
            <ActionIcon icon={FilePenLine} /> 属性
          </button>
          {movie.douban_url && (
            <a
              className="btn"
              href={movie.douban_url}
              target="_blank"
              rel="noreferrer"
            >
              <ActionIcon icon={ExternalLink} className="text-emerald-400" /> 豆瓣
            </a>
          )}
          <button
            className="btn text-red-400 hover:bg-red-900/30"
            onClick={handleDelete}
          >
            <ActionIcon icon={Trash2} /> 删除
          </button>
        </div>
        <p className="break-all text-xs text-ink-400">文件：{movie.video_path || '未记录'}</p>
      </div>
    </div>
  );
}
