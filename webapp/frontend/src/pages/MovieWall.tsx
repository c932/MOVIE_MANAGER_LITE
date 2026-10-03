// 电影墙主页面 — 三栏布局复刻桌面版
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { movieApi } from '../api/client';
import { useJobPoll } from '../hooks/useJobPoll';
import { JobProgress } from '../components/JobProgress';
import { MovieCard } from '../components/movie/MovieCard';
import { MovieDetail } from '../components/movie/MovieDetail';
import { MovieFilterSidebar } from '../components/movie/MovieFilterSidebar';
import { MovieSettingsDialog } from '../components/movie/MovieSettingsDialog';
import { useMovieStore } from '../stores/movieStore';
import type { MovieListItem } from '../types/api';

export default function MovieWall() {
  const store = useMovieStore();
  const [refreshJobId, setRefreshJobId] = useState<string | null>(null);
  const [scrapeJobId, setScrapeJobId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    movie: MovieListItem;
    x: number;
    y: number;
  } | null>(null);

  // 加载数据
  useEffect(() => {
    store.load();
  }, []);

  // 刷新进度
  const { job: refreshJob } = useJobPoll(
    movieApi,
    refreshJobId,
    800,
    useCallback(() => {
      store.load();
      setRefreshJobId(null);
    }, [store]),
  );

  // 刮削进度
  const { job: scrapeJob } = useJobPoll(
    movieApi,
    scrapeJobId,
    800,
    useCallback(() => {
      store.load();
      setScrapeJobId(null);
    }, [store]),
  );

  const movies = store.filtered();
  const selectedMovie = useMemo(
    () => store.movies.find((m) => m.id === store.selectedId) || null,
    [store.movies, store.selectedId],
  );

  const posterW = 200;
  const posterH = 300;
  const gridRef = useRef<HTMLDivElement>(null);

  const handleRefresh = async () => {
    const { job_id } = await movieApi.refresh(false);
    setRefreshJobId(job_id);
  };

  const handleScrape = async () => {
    if (!selectedMovie) {
      if (!movies.length) return;
      const ids = movies.slice(0, 5).map((m) => m.id);
      const { job_id } = await movieApi.scrape(ids);
      setScrapeJobId(job_id);
    } else {
      const { job_id } = await movieApi.scrape([selectedMovie.id]);
      setScrapeJobId(job_id);
    }
  };

  const handleSelect = (movie: MovieListItem) => {
    store.selectMovie(movie.id);
    setContextMenu(null);
  };

  const handleContextMenu = (movie: MovieListItem, x: number, y: number) => {
    setContextMenu({ movie, x, y });
  };

  const handleUpdate = (movie: MovieListItem) => {
    store.updateMovie(movie);
  };

  const handleDelete = (id: string) => {
    store.removeMovie(id);
    setContextMenu(null);
  };

  const handleSeriesClick = (setName: string) => {
    // TODO: series view
    alert(`系列: ${setName}`);
  };

  const handleReparse = async (id: string) => {
    try {
      const updated = await movieApi.reparse(id);
      store.updateMovie(updated);
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const handleEditFields = (movie: MovieListItem) => {
    // TODO: fields editor modal
    alert(`编辑属性: ${movie.title}`);
  };

  const job = refreshJob || scrapeJob;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左侧筛选 */}
      <aside className="flex w-64 shrink-0 flex-col border-r divider bg-ink-900">
        <div className="flex items-center justify-between border-b divider px-3 py-2">
          <span className="text-sm font-semibold text-ink-50">电影墙</span>
          <span className="text-2xs text-ink-400">{movies.length} 部</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <MovieFilterSidebar />
        </div>
      </aside>

      {/* 右侧主区域 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 工具栏 */}
        <div className="flex shrink-0 items-center gap-2 border-b divider bg-ink-850 px-3 py-2">
          {/* 排序 */}
          {(
            [
              ['default', '默认'],
              ['rating', '评分'],
              ['release', '上映'],
              ['added', '加入'],
              ['random', '随机'],
            ] as [string, string][]
          ).map(([mode, label]) => (
            <button
              key={mode}
              className={`btn ${store.sortMode === mode ? 'btn-active' : ''}`}
              onClick={() => store.setSortMode(mode as typeof store.sortMode)}
            >
              {label}
            </button>
          ))}

          <div className="h-5 w-px bg-ink-700" />

          {/* 海报缩放 */}
          <span className="text-2xs text-ink-400">缩放</span>
          <input
            type="range"
            min={50}
            max={200}
            value={store.posterScale}
            onChange={(e) => store.setPosterScale(parseInt(e.target.value))}
            className="w-20 accent-cinema-500"
          />

          <div className="h-5 w-px bg-ink-700" />

          <button className="btn" onClick={handleRefresh} title="增量刷新">
            🔄 刷新
          </button>
          <button className="btn" onClick={handleScrape} title="刮削豆瓣评分">
            🔍 刮削
          </button>
          <button className="btn" onClick={() => setSettingsOpen(true)} title="设置">
            ⚙ 设置
          </button>

          {/* 任务进度 */}
          <div className="ml-auto">
            <JobProgress
              job={job}
              onCancel={() => {
                movieApi.cancel(job?.id || '');
              }}
              accent="cinema"
            />
          </div>
        </div>

        {/* 详情面板 + 海报墙 */}
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 上方详情 */}
          <div className="shrink-0 border-b divider" style={{ maxHeight: '45vh' }}>
            <MovieDetail
              movie={selectedMovie}
              onUpdated={handleUpdate}
              onDeleted={handleDelete}
              onSeriesClick={handleSeriesClick}
              onRefreshPoster={() => {
                /* handled inside detail */
              }}
              onEditFields={handleEditFields}
            />
          </div>

          {/* 下方海报墙 */}
          <div className="flex min-h-0 flex-1 overflow-y-auto">
            <div
              ref={gridRef}
              className="flex flex-wrap content-start gap-3 p-3"
            >
              {movies.map((movie) => (
                <MovieCard
                  key={movie.id}
                  movie={movie}
                  width={posterW}
                  height={posterH}
                  scale={store.posterScale}
                  selected={movie.id === store.selectedId}
                  onSelect={handleSelect}
                  onContextMenu={handleContextMenu}
                />
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* 右键菜单 */}
      {contextMenu && (
        <div
          className="fixed z-50 min-w-[10rem] rounded-lg border border-ink-700 bg-ink-800 py-1 shadow-2xl ring-1 ring-black/40"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onMouseLeave={() => setContextMenu(null)}
        >
          <MenuItem onClick={() => store.selectMovie(contextMenu.movie.id)}>
            查看详情
          </MenuItem>
          <MenuItem onClick={() => handleReparse(contextMenu.movie.id)}>
            📝 更新 NFO
          </MenuItem>
          <MenuItem onClick={() => handleEditFields(contextMenu.movie)}>
            📝 属性
          </MenuItem>
          <div className="my-1 border-t divider" />
          <MenuItem onClick={() => handleUpdate(contextMenu.movie)}>
            🖼 更新海报
          </MenuItem>
          <MenuItem
            onClick={() => {
              navigator.clipboard.writeText(contextMenu.movie.video_path || '');
              setContextMenu(null);
            }}
          >
            📁 复制路径
          </MenuItem>
          <div className="my-1 border-t divider" />
          <MenuItem onClick={() => handleDelete(contextMenu.movie.id)} className="text-red-400">
            🗑 删除本地记录
          </MenuItem>
        </div>
      )}

      {/* 点击空白关闭菜单 */}
      {contextMenu && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setContextMenu(null)}
        />
      )}

      {/* 设置对话框 */}
      <MovieSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

function MenuItem({
  children,
  onClick,
  className = '',
}: {
  children: React.ReactNode;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      className={`flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-700 ${className}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
