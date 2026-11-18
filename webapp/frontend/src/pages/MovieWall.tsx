import { useCallback, useEffect, useMemo, useState } from 'react';
import { movieApi } from '../api/client';
import { useJobPoll } from '../hooks/useJobPoll';
import { JobProgress } from '../components/JobProgress';
import { Modal } from '../components/Modal';
import { VirtualPosterGrid } from '../components/movie/VirtualPosterGrid';
import { MovieDetail } from '../components/movie/MovieDetail';
import { FloatingMovieDetail } from '../components/movie/FloatingMovieDetail';
import { MovieFilterSidebar } from '../components/movie/MovieFilterSidebar';
import { MovieSettingsDialog } from '../components/movie/MovieSettingsDialog';
import { LibraryBrowseDialog } from '../components/movie/LibraryBrowseDialog';
import { ScrapeManager } from '../components/movie/ScrapeManager';
import { SearchScrapeDialog } from '../components/movie/SearchScrapeDialog';
import { scrapeApi } from '../api/scrape';
import type { ScrapeRow } from '../api/scrape';
import { LocalPlayback } from '../components/movie/LocalPlayback';
import { filterMovies, useMovieStore } from '../stores/movieStore';
import type { MovieListItem } from '../types/api';

type ViewMode = 'normal' | 'wall' | 'fullscreen';

export default function MovieWall() {
  const store = useMovieStore();
  const [jobId, setJobId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const [searchRows, setSearchRows] = useState<ScrapeRow[]|null>(null);
  const [browse, setBrowse] = useState<'series' | 'top250' | 'nowplaying' | null>(null);
  const [sourceAvailable, setSourceAvailable] = useState(false);
  const [nasConnected, setNasConnected] = useState(false);
  const [sourceLabel, setSourceLabel] = useState('正在检查 NAS 连接状态…');
  const [sidebar, setSidebar] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('normal');
  const [overlayOpen, setOverlayOpen] = useState(false);
  const [detail, setDetail] = useState<MovieListItem | null>(null);
  const [properties, setProperties] = useState<MovieListItem | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [posterVersion, setPosterVersion] = useState(0);
  const [series, setSeries] = useState('');
  const [context, setContext] = useState<{ movie: MovieListItem; x: number; y: number } | null>(null);
  const load = store.load;
  useEffect(() => {
    const changed = () => {
      if (!document.fullscreenElement) setViewMode(current => current === 'fullscreen' ? 'wall' : current);
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  const changeMode = async (next: ViewMode) => {
    setOverlayOpen(false);
    if (next !== 'fullscreen' && document.fullscreenElement) {
      try { await document.exitFullscreen(); } catch { /* browser may already be exiting */ }
    }
    setViewMode(next);
    if (next === 'fullscreen') {
      try { if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen(); }
      catch { setMessage('已进入沉浸海报墙；浏览器未允许系统全屏。'); }
    }
  };
  const refreshSources = useCallback(() => movieApi.systemInfo().then(info => {
    setSourceAvailable(info.source_available);
    setNasConnected(info.nas_connected);
    setSourceLabel(info.source_available ? 'NAS 已连接 · 媒体库可扫描' : info.nas_connected && !info.nas_configured ? 'NAS 已连接 · 尚未选择并保存媒体库目录' : info.nas_configured ? '媒体库所需的 NAS 共享未全部连接 · 使用已同步资料和海报' : 'NAS 未连接 · 使用已同步资料和海报');
  }), []);
  useEffect(() => {
    load();
    refreshSources().catch(e => setMessage((e as Error).message));
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') load(); }, 60000);
    return () => window.clearInterval(timer);
  }, [load, refreshSources]);
  useEffect(() => {
    let active = true;
    if (!store.selectedId) return;
    movieApi.detail(store.selectedId).then(movie => { if (active) setDetail(movie); })
      .catch(e => { if (active) setMessage((e as Error).message); });
    return () => { active = false; };
  }, [store.selectedId, store.movies]);
  const { job } = useJobPoll(movieApi, jobId, 800, useCallback(() => { load(); setJobId(null); }, [load]));
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setMessage(''); setContext(null);
    try { await work(); } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  };
  const updated = (movie: MovieListItem) => { store.updateMovie(movie); setDetail(movie); };
  const selectMovie = store.selectMovie;
  const selected = useCallback((movie: MovieListItem) => {
    selectMovie(movie.id);
    setContext(null);
    setOverlayOpen(viewMode !== 'normal');
  }, [selectMovie, viewMode]);
  const openDetails = useCallback((movie: MovieListItem) => {
    selectMovie(movie.id);
    setContext(null);
    setOverlayOpen(true);
  }, [selectMovie]);
  const openContext = useCallback((movie: MovieListItem, x: number, y: number) => setContext({movie, x:Math.min(x,window.innerWidth-220), y:Math.min(y,window.innerHeight-320)}), []);
  const refreshPoster = async (movie: MovieListItem) => {
    await movieApi.invalidatePoster(movie.id); setPosterVersion(value => value + 1); setMessage('已刷新后端海报副本');
  };
  const {movies: allMovies, search, searchDuplicate, selectedGenres, selectedCountries, selectedYears,
    selectedTags, minRating, watchFilter, favoriteFilter, sortMode} = store;
  const movies = useMemo(() => filterMovies({movies:allMovies, search, searchDuplicate, selectedGenres, selectedCountries, selectedYears, selectedTags, minRating, watchFilter, favoriteFilter, sortMode}).filter(movie => !series || movie.set_name === series),
    [allMovies, search, searchDuplicate, selectedGenres, selectedCountries, selectedYears, selectedTags,
      minRating, watchFilter, favoriteFilter, sortMode, series]);
  useEffect(() => {
    if (viewMode !== 'normal' || !movies.length) return;
    if (!store.selectedId || !movies.some(movie => movie.id === store.selectedId)) selectMovie(movies[0].id);
  }, [movies, selectMovie, store.selectedId, viewMode]);
  const activeMovie = detail?.id === store.selectedId
    ? detail
    : movies.find(movie => movie.id === store.selectedId)
      || store.movies.find(movie => movie.id === store.selectedId)
      || null;
  const openScrape = async (movie: MovieListItem) => {
    const workspace = await scrapeApi.rows();
    const selected = workspace.rows.find(row => row.movie_id === movie.id);
    if (!selected) throw new Error('未找到该电影，请在电影资料管理中更新媒体库。');
    const others = movies.filter(item=>item.id!==movie.id).flatMap(item=>workspace.rows.filter(row=>row.movie_id===item.id));
    store.selectMovie(null); setSearchRows([selected,...others]);
  };
  const scrapeSaved = (movie: MovieListItem) => { updated(movie); setPosterVersion(value=>value+1); };
  return <div className="movie-wall-shell flex h-dvh overflow-hidden" data-view-mode={viewMode}>
    <aside data-testid="filter-sidebar" data-visible={viewMode !== 'fullscreen'} aria-hidden={viewMode === 'fullscreen'} inert={viewMode === 'fullscreen'}
      className={`mode-sidebar shrink-0 flex-col border-r divider bg-ink-900 ${sidebar ? 'fixed inset-y-0 left-0 z-30 flex md:static' : 'hidden md:flex'}`}>
      <div className="flex items-center justify-between border-b divider p-3"><strong>电影墙</strong><button className="btn md:hidden" onClick={() => setSidebar(false)}>关闭筛选</button></div>
      <div className="flex-1 overflow-y-auto"><MovieFilterSidebar /></div>
    </aside>
    <main className="flex min-w-0 flex-1 flex-col">
      <header data-visible={viewMode !== 'fullscreen'} inert={viewMode === 'fullscreen'} className="mode-chrome flex shrink-0 flex-wrap items-center gap-1 border-b divider bg-ink-850 p-2">
        <button className="btn md:hidden" onClick={() => setSidebar(true)}>筛选</button>
        <div className="mode-switch mr-1" role="group" aria-label="电影墙显示模式">
          {([['normal', '正常'], ['wall', '海报墙'], ['fullscreen', '全屏海报墙']] as const).map(([mode, label]) =>
            <button key={mode} aria-pressed={viewMode === mode} className={viewMode === mode ? 'active' : ''} onClick={() => changeMode(mode)}>{label}</button>)}
        </div>
        {([['default', '默认'], ['rating', '评分↓'], ['release', '上映时间↓'], ['added', '加入时间↓'], ['random', '随机']] as const).map(([mode, label]) =>
          <button key={mode} className={`btn ${store.sortMode === mode ? 'btn-active' : ''}`} onClick={() => store.setSortMode(mode)}>{label}</button>)}
        <label className="flex items-center gap-2 px-2 text-xs text-ink-300">海报缩放<input aria-label="海报缩放" type="range" min="50" max="130" value={store.posterScale} onChange={e => store.setPosterScale(Number(e.target.value))} className="w-20" /></label>
        <button className="btn" onClick={() => setBrowse('series')}>系列电影</button>
        <button className="btn" onClick={() => setBrowse('top250')}>榜单对比</button>
        <button className="btn" onClick={() => setBrowse('nowplaying')}>新片推荐</button>
        <button className="btn" onClick={()=>setManagerOpen(true)}>搜索&刮削</button>
        <button className="btn" disabled={busy} onClick={() => run(async () => { await load(); setPosterVersion(value => value + 1); setMessage('已读取最新共享数据库'); })}>刷新数据库</button>
        <button className="btn" disabled={!sourceAvailable || busy || !!jobId} title={!sourceAvailable ? sourceLabel + '，请在设置中配置媒体库' : '扫描已选择的媒体库目录'} onClick={() => run(async () => { setJobId((await movieApi.refresh(false)).job_id); })}>扫描 NAS</button>
        <button className="btn" onClick={() => setSettingsOpen(true)}>设置</button>
        <JobProgress job={job} accent="cinema" onCancel={() => { if (job) movieApi.cancel(job.id).catch(e => setMessage((e as Error).message)); }} />
      </header>
      {viewMode === 'fullscreen' && <button className="fixed right-4 top-3 z-30 rounded-lg border border-white/20 bg-black/75 px-4 py-2 text-sm text-white backdrop-blur" onClick={() => changeMode('wall')}>退出全屏</button>}
      <div data-visible={viewMode !== 'fullscreen'} inert={viewMode === 'fullscreen'} className="mode-status flex items-center justify-between gap-3 border-b divider px-3 py-2 text-xs text-ink-300">
        <span>NUC 共享电影库 · 共 {store.movies.length} 部 {series && ` / ${series}`}</span>
        {series && <button className="btn" onClick={() => setSeries('')}>退出系列筛选</button>}
        <span>{sourceLabel}</span>{!sourceAvailable && <button className="btn text-xs" onClick={() => setSettingsOpen(true)}>{nasConnected ? '选择媒体库目录' : '配置 NAS'}</button>}
      </div>
      {(message || store.error) && <div role={store.error ? 'alert' : 'status'} className="flex items-center justify-between gap-2 border-b divider px-3 py-2 text-sm"><span>{store.error || message}</span><button className="btn" onClick={() => { setMessage(''); if (store.error) load(); }}>{store.error ? '重试' : '关闭'}</button></div>}
      <section data-testid="movie-intro" data-visible={viewMode === 'normal'} aria-hidden={viewMode !== 'normal'} inert={viewMode !== 'normal'} className="movie-intro border-b divider bg-ink-850/70">
        <div className="movie-intro-inner">
          {activeMovie
            ? <MovieDetail key={activeMovie.id} movie={activeMovie} onUpdated={updated} onDeleted={setDeleteId} onSeriesClick={name => { setSeries(name); selectMovie(null); setOverlayOpen(false); }} onRefreshPoster={() => setPosterVersion(value => value + 1)} onEditFields={setProperties} />
            : <p className="p-8 text-sm text-ink-300" role="status">{store.loading ? '正在读取电影资料…' : '选择一部电影查看简介'}</p>}
        </div>
      </section>
      <VirtualPosterGrid movies={movies} scale={store.posterScale} selectedId={store.selectedId} posterVersion={posterVersion} onSelect={selected} onContextMenu={openContext}>
        {store.loading && !store.movies.length && <p role="status" className="p-8">正在读取共享电影库…</p>}
        {!store.loading && !movies.length && <div className="p-10 text-center text-ink-300"><p>{store.movies.length ? '没有符合条件的电影，请调整搜索或筛选。' : '共享电影库为空。请在桌面设置中开启后端同步，选择仅上传导入已有电影库。'}</p>{!!store.movies.length && <button className="btn mt-3" onClick={() => { store.resetFilters(); setSeries(''); }}>清除筛选</button>}</div>}
      </VirtualPosterGrid>
      <footer data-visible={viewMode !== 'fullscreen'} inert={viewMode === 'fullscreen'} className="mode-status shrink-0 border-t divider px-3 py-2 text-xs text-ink-400">显示 {movies.length} 部 · 网页与桌面共享资料，桌面可保留离线副本</footer>
    </main>
    {viewMode !== 'normal' && overlayOpen && store.selectedId && (() => {
      return <FloatingMovieDetail title={activeMovie?.title || '电影详情'} onClose={() => setOverlayOpen(false)}>{activeMovie ? <MovieDetail key={activeMovie.id} movie={activeMovie} onUpdated={updated} onDeleted={setDeleteId} onSeriesClick={name => { setSeries(name); selectMovie(null); setOverlayOpen(false); }} onRefreshPoster={() => setPosterVersion(value => value + 1)} onEditFields={setProperties} /> : <p className="p-8" role="status">正在读取电影资料…</p>}</FloatingMovieDetail>;
    })()}
    {context && <><div className="fixed inset-0 z-40" onClick={() => setContext(null)} /><div role="menu" aria-label="电影操作" className="fixed z-50 w-52 rounded-lg border border-ink-700 bg-ink-800 p-1 shadow-2xl" style={{ left: Math.max(0, context.x), top: Math.max(0, context.y) }} onKeyDown={e => { if (e.key === 'Escape') setContext(null); }}>
      <MenuItem onClick={() => openDetails(context.movie)}>查看完整详情</MenuItem>
      <LocalPlayback movie={context.movie} menu/>
      <MenuItem onClick={()=>run(()=>openScrape(context.movie))}>搜索匹配 / 刮削电影</MenuItem>
      <MenuItem onClick={() => { setProperties(context.movie); setContext(null); }}>属性</MenuItem>
      <MenuItem onClick={() => run(async () => { updated(await movieApi.setWatched(context.movie.id, !context.movie.watched)); })}>{context.movie.watched ? '标为未观看' : '标为已观看'}</MenuItem>
      <MenuItem onClick={() => run(async () => { updated(await movieApi.setFavorite(context.movie.id, !context.movie.favorite)); })}>{context.movie.favorite ? '取消收藏' : '收藏'}</MenuItem>
      <MenuItem onClick={() => run(() => refreshPoster(context.movie))}>刷新后端海报</MenuItem>
      <MenuItem disabled={!sourceAvailable} onClick={() => run(async () => { updated(await movieApi.reparse(context.movie.id)); })}>从 NAS 更新 NFO</MenuItem>
      <MenuItem onClick={() => run(async () => { if (!navigator.clipboard) throw new Error('当前浏览器不允许复制，请在属性中选中文件路径复制'); await navigator.clipboard.writeText(context.movie.video_path); setMessage('已复制视频路径'); })}>复制视频路径</MenuItem>
      <MenuItem onClick={() => { setDeleteId(context.movie.id); setContext(null); }}>从共享数据库删除…</MenuItem>
    </div></>}
    {properties && <Modal title={`电影属性 · ${properties.title}`} onClose={() => setProperties(null)}>
      <p className="mb-4 text-sm text-ink-300">{sourceAvailable ? 'NAS 目录已连接。可在电影资料管理中编辑或刮削；保存源文件需在 NAS 设置中开启写入权限。' : nasConnected ? 'NAS 共享已连接，请在设置中选择并保存需要扫描的媒体库目录。' : 'NAS 尚未连接，请在设置中填写登录并选择媒体库目录。共享资料仍可浏览，观看、收藏和个人评分可在详情中修改。'}</p>
      <dl className="space-y-3 break-all text-sm">{Object.entries({ 标题: properties.title, 原名: properties.original_title, 年份: properties.year, 上映日期: properties.premiered, 系列: properties.set_name, 国家地区: properties.countries.join(' / '), 导演: properties.directors.join(' / '), 类型: properties.genres.join(' / '), 视频: properties.video_path, NFO: properties.nfo_path, 海报: properties.poster_path, 分辨率: properties.resolution, HDR: properties.hdr_type }).map(([key, value]) => <div key={key}><dt className="text-ink-400">{key}</dt><dd className="select-text">{value || '未记录'}</dd></div>)}</dl>
    </Modal>}
    {deleteId && <Modal title="从共享数据库删除" onClose={() => !busy && setDeleteId(null)}><p>删除「{store.movies.find(movie => movie.id === deleteId)?.title}」的共享记录？同步下载的客户端也会收到删除；不会删除 NAS 上的文件。</p><div className="mt-5 flex justify-end gap-2"><button className="btn" disabled={busy} onClick={() => setDeleteId(null)}>取消</button><button className="btn bg-red-900/50" disabled={busy} onClick={() => run(async () => { await movieApi.delete(deleteId); store.removeMovie(deleteId); setDeleteId(null); setMessage('已从共享数据库删除'); })}>确认删除记录</button></div></Modal>}
    {browse && <LibraryBrowseDialog movies={store.movies} initial={browse} onSelect={store.selectMovie} onClose={() => setBrowse(null)}
      onUpdated={updated} onDeleted={setDeleteId} onSeriesClick={name => { setSeries(name); setBrowse(null); }}
      onRefreshPoster={() => setPosterVersion(value => value + 1)} onEditFields={setProperties} />}
    {managerOpen&&<ScrapeManager onClose={()=>setManagerOpen(false)} onSaved={scrapeSaved} onSettings={()=>setSettingsOpen(true)}/>}
    {searchRows&&<SearchScrapeDialog rows={searchRows} onClose={()=>setSearchRows(null)} onSaved={scrapeSaved}/>}
    <MovieSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} onNasChanged={() => { refreshSources().catch(e => setMessage((e as Error).message)); }} />
  </div>;
}

function MenuItem({ children, onClick, disabled = false }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button role="menuitem" disabled={disabled} className="flex w-full items-center rounded px-3 py-2 text-left text-sm hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40" onClick={onClick} title={disabled ? '需要先在 NUC 挂载 NAS' : undefined}>{children}</button>;
}
