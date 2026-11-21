// 电影详情面板 — 右侧上方，展示选中电影的完整信息
import { useState } from 'react';
import { CircleCheck, Eye, FilePenLine, Image, Star, Trash2 } from 'lucide-react';
import { ActionIcon } from '../ActionIcon';
import { movieApi } from '../../api/client';
import type { MovieListItem } from '../../types/api';
import type { SeriesMovie } from '../../types/api';
import { ratingOrder, ratingNames, ratingForSource, quarkSearchUrl } from '../../utils/movieDisplay';
import doubanIcon from '../../assets/douban-icon.png';
import doubanWordmark from '../../assets/douban-wordmark.png';
import tmdbLogo from '../../assets/tmdb-logo.svg';
import { LocalPlayback } from './LocalPlayback';
import { TechBadges } from './TechBadges';
import { BilibiliActions } from './BilibiliActions';
import { SeriesShortcuts } from './SeriesShortcuts';
import { useSeriesListing } from './useSeriesListing';

const ratingLogos = {douban: doubanWordmark, imdb: '/logo/imdb.png', tmdb: tmdbLogo};

interface Props {
  movie: MovieListItem | null;
  external?: Pick<MovieListItem, 'title' | 'original_title' | 'year' | 'premiered' | 'plot' | 'ratings' | 'genres' | 'douban_url'>
    & {poster_url: string; countries?: string[]; directors?: string[]; actors?: MovieListItem['actors']; enrichment_note?: string; set_name?: string; tmdb_id?: string};
  unreleased?: boolean;
  hideExternalActions?: boolean;
  posterFallback?: string;
  movies?: MovieListItem[];
  onUpdated?: (movie: MovieListItem) => void;
  onDeleted?: (id: string) => void;
  onSeriesClick?: (setName: string) => void;
  onSelectSeriesMovie?: (part: SeriesMovie) => void;
  onRefreshPoster?: (id: string) => void;
  onEditFields?: (movie: MovieListItem) => void;
}

export function MovieDetail({
  movie: local,
  external,
  unreleased = false,
  hideExternalActions = false,
  posterFallback = '',
  movies = [],
  onUpdated,
  onDeleted,
  onSeriesClick,
  onSelectSeriesMovie,
  onRefreshPoster,
  onEditFields,
}: Props) {
  const [posterVersion, setPosterVersion] = useState(0);
  const [ratingInput, setRatingInput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [failedPoster, setFailedPoster] = useState('');
  const seriesName = local?.set_name || external?.set_name || '';
  const {items: seriesItems} = useSeriesListing(seriesName, movies);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const movie = local ?? external;
  if (!movie) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-ink-400">
        选择一部电影查看详情
      </div>
    );
  }

  const localPoster = local?.has_poster ? `${movieApi.posterUrl(local.id, 280, 420, 'contain')}&v=${posterVersion}` : '';
  const remotePoster = external?.poster_url || posterFallback;
  const posterUrl = localPoster && localPoster !== failedPoster ? localPoster
    : remotePoster ? movieApi.proxyImageUrl(remotePoster, true) : '';

  const toggleWatched = async () => {
    if (local) onUpdated?.(await movieApi.setWatched(local.id, !local.watched));
  };

  const toggleFavorite = async () => {
    if (local) onUpdated?.(await movieApi.setFavorite(local.id, !local.favorite));
  };

  const submitRating = async () => {
    const r = parseFloat(ratingInput);
    if (isNaN(r) || r < 0 || r > 10) { setError('请输入 0–10 分'); return; }
    if (local) onUpdated?.(await movieApi.setRating(local.id, r));
    setRatingInput('');
  };

  const handleRefreshPoster = async () => {
    if (!local) return;
    await movieApi.invalidatePoster(local.id);
    setPosterVersion((v) => v + 1);
    onRefreshPoster?.(local.id);
  };

  return (
    <div className="flex h-full gap-4 overflow-y-auto p-4 max-sm:flex-col">
      {/* 左：海报 */}
      <div className="shrink-0">
        {posterUrl && posterUrl !== failedPoster ? (
          <img
            src={posterUrl}
            alt={movie.title}
            className="rounded-lg shadow-2xl ring-1 ring-ink-700"
            style={{ width: 'min(28vw, 220px)', aspectRatio: '2/3', objectFit: 'contain' }}
            draggable={false}
            onError={() => setFailedPoster(posterUrl)}
          />
        ) : (
          <div
            className="flex items-center justify-center rounded-lg bg-ink-800 text-sm text-ink-400 ring-1 ring-ink-700"
            style={{ width: 'min(28vw, 220px)', aspectRatio: '2/3' }}
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
          <h2 className="text-xl font-semibold text-ink-50">{movie.title}{unreleased && '（未上映）'}</h2>
          {movie.original_title && movie.original_title !== movie.title && (
            <p className="text-sm text-ink-300">{movie.original_title}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-300">
            {(movie.premiered || movie.year) && <span>{movie.premiered || movie.year}</span>}
            {local?.runtime && <span>{local.runtime} 分钟</span>}
            {local?.file_size && <span>{local.file_size}</span>}
            {!local && <span>未入库</span>}
          </div>
          {local && <div className="mt-3"><TechBadges resolution={local.resolution} hdrType={local.hdr_type} /></div>}
        </div>

        {/* 评分卡片 */}
        <div className="flex flex-wrap gap-2">
          {ratingOrder.map(source => {
            const value = ratingForSource(movie, source);
            return <div key={source} className="flex items-center gap-1.5 rounded-lg bg-ink-800 px-3 py-1.5">
              <img className="h-6 w-14 object-contain" alt={ratingNames[source]} src={ratingLogos[source]} />
              <span className="font-mono text-sm font-semibold text-gold">{value > 0 ? value.toFixed(1) : '—'}</span>
            </div>;
          })}
        </div>

        {/* 榜单排名 */}
        {local?.rank && (local.rank.douban_top250 || local.rank.imdb_top250) && (
          <div className="flex gap-2">
            {local.rank.douban_top250 && (
              <span className="rounded-full bg-cinema-800/40 px-2.5 py-1 text-xs text-cinema-400">
                豆瓣 Top250 #{local.rank.douban_top250}
              </span>
            )}
            {local.rank.imdb_top250 && (
              <span className="rounded-full bg-ink-700 px-2.5 py-1 text-xs text-gold">
                IMDb Top250 #{local.rank.imdb_top250}
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
          {movie.countries?.map((c) => (
            <span key={c} className="tag">
              {c}
            </span>
          ))}
        </div>

        {/* 简介 */}
        {(movie.plot || !local) && <p className="text-sm leading-relaxed text-ink-200">{movie.plot || '片源暂未提供简介。'}</p>}
        {external?.enrichment_note && <p role="status" className="text-xs text-amber-300">{external.enrichment_note}</p>}

        {/* 导演/演员 */}
        <div className="space-y-1 text-xs">
          {!!movie.directors?.length && (
            <div>
              <span className="text-ink-400">导演：</span>
              <span className="text-ink-200">{movie.directors.join(' / ')}</span>
            </div>
          )}
          {!!movie.actors?.length && (
            <div>
              <span className="text-ink-400">主演：</span>
              <span className="text-ink-200">
                {movie.actors.slice(0, 8).map((a) => a.name).join(' / ')}
              </span>
            </div>
          )}
        </div>

        {/* 系列电影 */}
        {!!seriesName && !!seriesItems.length && onSelectSeriesMovie && (
          <SeriesShortcuts seriesName={seriesName} items={seriesItems} currentId={local?.id || external?.tmdb_id || ''}
            onSelect={onSelectSeriesMovie} onSeriesClick={onSeriesClick} />
        )}

        {/* 按钮栏 */}
        <div className="movie-detail-actions mt-auto flex flex-wrap items-center gap-1.5 border-t divider pt-3">
          {local?.video_path && <LocalPlayback movie={local}/>}
          {!local && !hideExternalActions && <>
            <a className="btn" href={quarkSearchUrl(movie.title)} target="_blank" rel="noopener noreferrer">打开夸克盘搜</a>
            <BilibiliActions title={movie.title} originalTitle={movie.original_title} year={movie.year}/>
          </>}
          {local && <BilibiliActions title={movie.title} originalTitle={movie.original_title} year={movie.year}/>}
          {local && <>
          <button
            className={`btn ${local.watched ? 'btn-active' : ''}`}
            onClick={() => run(toggleWatched)} disabled={busy}
          >
            <ActionIcon icon={local.watched ? CircleCheck : Eye} /> {local.watched ? '已观看' : '标记观看'}
          </button>
          <button
            className={`btn ${local.favorite ? 'btn-active text-gold' : ''}`}
            onClick={() => run(toggleFavorite)} disabled={busy}
          >
            <ActionIcon icon={Star} className={local.favorite ? 'fill-current' : ''} /> {local.favorite ? '已收藏' : '收藏'}
          </button>

          {/* 评分输入 */}
          <div className="inline-flex shrink-0 items-center gap-1">
            <input
              className="input h-[34px] w-20 px-2 text-center tabular-nums"
              type="number"
              min={0}
              max={10}
              step={0.5}
              placeholder={local.user_rating > 0 ? local.user_rating.toFixed(1) : '评分'}
              value={ratingInput}
              onChange={(e) => setRatingInput(e.target.value)}
              aria-label="我的评分" onKeyDown={(e) => e.key === 'Enter' && run(submitRating)}
            />
            <button className="btn" disabled={busy} onClick={() => run(submitRating)} title="0-10 分">
              <ActionIcon icon={Star} /> 评分
            </button>
          </div>

          <button className="btn" disabled={busy} onClick={() => run(handleRefreshPoster)} title="刷新后端保存的海报副本">
            <ActionIcon icon={Image} /> 更新海报
          </button>
          <button className="btn" onClick={() => onEditFields?.(local)}>
            <ActionIcon icon={FilePenLine} /> 属性
          </button>
          </>}
          {movie.douban_url && (
            <a
              className="btn"
              href={movie.douban_url}
              target="_blank"
              rel="noreferrer"
            >
              <img className="action-icon rounded-sm" alt="" src={doubanIcon} /> 豆瓣
            </a>
          )}
          {local && <button
            className="btn text-red-400 hover:bg-red-900/30"
            onClick={() => onDeleted?.(local.id)}
          >
            <ActionIcon icon={Trash2} /> 删除
          </button>}
        </div>
        {local && <p className="break-all text-xs text-ink-400">文件：{local.video_path || '未记录'}</p>}
      </div>
    </div>
  );
}
