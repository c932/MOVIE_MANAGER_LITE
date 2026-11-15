import { useCallback, useEffect, useState } from 'react';
import { movieApi } from '../api/client';
import { useJobPoll } from '../hooks/useJobPoll';
import { JobProgress } from '../components/JobProgress';
import { Modal } from '../components/Modal';
import { MovieCard } from '../components/movie/MovieCard';
import { MovieDetail } from '../components/movie/MovieDetail';
import { MovieFilterSidebar } from '../components/movie/MovieFilterSidebar';
import { MovieSettingsDialog } from '../components/movie/MovieSettingsDialog';
import { LibraryBrowseDialog } from '../components/movie/LibraryBrowseDialog';
import { useMovieStore } from '../stores/movieStore';
import type { MovieListItem } from '../types/api';

export default function MovieWall() {
  const store = useMovieStore();
  const [jobId, setJobId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [browse, setBrowse] = useState<'series' | 'top250' | 'nowplaying' | null>(null);
  const [sourceAvailable, setSourceAvailable] = useState(false);
  const [nasConnected, setNasConnected] = useState(false);
  const [sourceLabel, setSourceLabel] = useState('正在检查 NAS 连接状态…');
  const [sidebar, setSidebar] = useState(false);
  const [detail, setDetail] = useState<MovieListItem | null>(null);
  const [properties, setProperties] = useState<MovieListItem | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [posterVersion, setPosterVersion] = useState(0);
  const [series, setSeries] = useState('');
  const [context, setContext] = useState<{ movie: MovieListItem; x: number; y: number } | null>(null);
  const load = store.load;
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
  const selected = (movie: MovieListItem) => { store.selectMovie(movie.id); setContext(null); };
  const refreshPoster = async (movie: MovieListItem) => {
    await movieApi.invalidatePoster(movie.id); setPosterVersion(value => value + 1); setMessage('已刷新后端海报副本');
  };
  const movies = store.filtered().filter(movie => !series || movie.set_name === series);
  return <div className="flex h-dvh overflow-hidden">
    <aside className={`${sidebar ? 'fixed inset-y-0 left-0 z-30 flex' : 'hidden'} w-60 shrink-0 flex-col border-r divider bg-ink-900 md:static md:flex`}>
      <div className="flex items-center justify-between border-b divider p-3"><strong>电影墙</strong><button className="btn md:hidden" onClick={() => setSidebar(false)}>关闭筛选</button></div>
      <div className="flex-1 overflow-y-auto"><MovieFilterSidebar /></div>
    </aside>
    <main className="flex min-w-0 flex-1 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-1 border-b divider bg-ink-850 p-2">
        <button className="btn md:hidden" onClick={() => setSidebar(true)}>筛选</button>
        {([['default', '默认'], ['rating', '评分↓'], ['release', '上映时间↓'], ['added', '加入时间↓'], ['random', '随机']] as const).map(([mode, label]) =>
          <button key={mode} className={`btn ${store.sortMode === mode ? 'btn-active' : ''}`} onClick={() => store.setSortMode(mode)}>{label}</button>)}
        <label className="flex items-center gap-2 px-2 text-xs text-ink-300">海报缩放<input aria-label="海报缩放" type="range" min="50" max="130" value={store.posterScale} onChange={e => store.setPosterScale(Number(e.target.value))} className="w-20" /></label>
        <button className="btn" onClick={() => setBrowse('series')}>系列电影</button>
        <button className="btn" onClick={() => setBrowse('top250')}>榜单对比</button>
        <button className="btn" onClick={() => setBrowse('nowplaying')}>新片推荐</button>
        <button className="btn" disabled={busy} onClick={() => run(async () => { await load(); setPosterVersion(value => value + 1); setMessage('已读取最新共享数据库'); })}>刷新数据库</button>
        <button className="btn" disabled={!sourceAvailable || busy || !!jobId} title={!sourceAvailable ? sourceLabel + '，请在设置中配置媒体库' : '扫描已选择的媒体库目录'} onClick={() => run(async () => { setJobId((await movieApi.refresh(false)).job_id); })}>扫描 NAS</button>
        <button className="btn" onClick={() => setSettingsOpen(true)}>设置</button>
        <JobProgress job={job} accent="cinema" onCancel={() => { if (job) movieApi.cancel(job.id).catch(e => setMessage((e as Error).message)); }} />
      </header>
      <div className="flex items-center justify-between gap-3 border-b divider px-3 py-2 text-xs text-ink-300">
        <span>NUC 共享电影库 · 共 {store.movies.length} 部 {series && ` / ${series}`}</span>
        {series && <button className="btn" onClick={() => setSeries('')}>退出系列筛选</button>}
        <span>{sourceLabel}</span>{!sourceAvailable && <button className="btn text-xs" onClick={() => setSettingsOpen(true)}>{nasConnected ? '选择媒体库目录' : '配置 NAS'}</button>}
      </div>
      {(message || store.error) && <div role={store.error ? 'alert' : 'status'} className="flex items-center justify-between gap-2 border-b divider px-3 py-2 text-sm"><span>{store.error || message}</span><button className="btn" onClick={() => { setMessage(''); if (store.error) load(); }}>{store.error ? '重试' : '关闭'}</button></div>}
      {detail && detail.id === store.selectedId ? <div className="max-h-[46dvh] shrink-0 overflow-auto border-b divider"><MovieDetail key={detail.id} movie={detail} onUpdated={updated} onDeleted={setDeleteId} onSeriesClick={setSeries} onRefreshPoster={() => setPosterVersion(value => value + 1)} onEditFields={setProperties} /></div>
        : store.selectedId && <p role="status" className="p-3 text-xs text-ink-300">正在读取完整电影资料…</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {store.loading && !store.movies.length && <p role="status" className="p-8">正在读取共享电影库…</p>}
        {!store.loading && !movies.length && <div className="p-10 text-center text-ink-300"><p>{store.movies.length ? '没有符合条件的电影，请调整搜索或筛选。' : '共享电影库为空。请在桌面设置中开启后端同步，选择仅上传导入已有电影库。'}</p>{!!store.movies.length && <button className="btn mt-3" onClick={() => { store.resetFilters(); setSeries(''); }}>清除筛选</button>}</div>}
        <div className="flex flex-wrap content-start gap-3 p-3">{movies.map(movie => <MovieCard key={`${movie.id}-${posterVersion}`} movie={movie} width={200} height={300} scale={store.posterScale} selected={movie.id === store.selectedId} onSelect={selected} onContextMenu={(movie, x, y) => setContext({ movie, x: Math.min(x, window.innerWidth - 220), y: Math.min(y, window.innerHeight - 320) })} />)}</div>
      </div>
      <footer className="shrink-0 border-t divider px-3 py-2 text-xs text-ink-400">显示 {movies.length} 部 · 网页与桌面共享资料，桌面可保留离线副本</footer>
    </main>
    {context && <><div className="fixed inset-0 z-40" onClick={() => setContext(null)} /><div role="menu" aria-label="电影操作" className="fixed z-50 w-52 rounded-lg border border-ink-700 bg-ink-800 p-1 shadow-2xl" style={{ left: Math.max(0, context.x), top: Math.max(0, context.y) }} onKeyDown={e => { if (e.key === 'Escape') setContext(null); }}>
      <MenuItem onClick={() => selected(context.movie)}>查看完整详情</MenuItem>
      <MenuItem onClick={() => { setProperties(context.movie); setContext(null); }}>属性</MenuItem>
      <MenuItem onClick={() => run(async () => { updated(await movieApi.setWatched(context.movie.id, !context.movie.watched)); })}>{context.movie.watched ? '标为未观看' : '标为已观看'}</MenuItem>
      <MenuItem onClick={() => run(async () => { updated(await movieApi.setFavorite(context.movie.id, !context.movie.favorite)); })}>{context.movie.favorite ? '取消收藏' : '收藏'}</MenuItem>
      <MenuItem onClick={() => run(() => refreshPoster(context.movie))}>刷新后端海报</MenuItem>
      <MenuItem disabled={!sourceAvailable} onClick={() => run(async () => { updated(await movieApi.reparse(context.movie.id)); })}>从 NAS 更新 NFO</MenuItem>
      <MenuItem onClick={() => run(async () => { if (!navigator.clipboard) throw new Error('当前浏览器不允许复制，请在属性中选中文件路径复制'); await navigator.clipboard.writeText(context.movie.video_path); setMessage('已复制视频路径'); })}>复制视频路径</MenuItem>
      <MenuItem onClick={() => { setDeleteId(context.movie.id); setContext(null); }}>从共享数据库删除…</MenuItem>
    </div></>}
    {properties && <Modal title={`电影属性 · ${properties.title}`} onClose={() => setProperties(null)}>
      <p className="mb-4 text-sm text-ink-300">{sourceAvailable ? 'NAS 目录已连接（只读），支持扫描与重新读取 NFO。观看、收藏和个人评分可在详情中修改；源文件编辑尚未开放。' : nasConnected ? 'NAS 共享已连接，请在设置中选择并保存需要扫描的媒体库目录。' : 'NAS 尚未连接，请在设置中填写登录并选择媒体库目录。共享资料仍可浏览，观看、收藏和个人评分可在详情中修改。'}</p>
      <dl className="space-y-3 break-all text-sm">{Object.entries({ 标题: properties.title, 原名: properties.original_title, 年份: properties.year, 上映日期: properties.premiered, 系列: properties.set_name, 国家地区: properties.countries.join(' / '), 导演: properties.directors.join(' / '), 类型: properties.genres.join(' / '), 视频: properties.video_path, NFO: properties.nfo_path, 海报: properties.poster_path, 分辨率: properties.resolution, HDR: properties.hdr_type }).map(([key, value]) => <div key={key}><dt className="text-ink-400">{key}</dt><dd className="select-text">{value || '未记录'}</dd></div>)}</dl>
    </Modal>}
    {deleteId && <Modal title="从共享数据库删除" onClose={() => !busy && setDeleteId(null)}><p>删除「{store.movies.find(movie => movie.id === deleteId)?.title}」的共享记录？同步下载的客户端也会收到删除；不会删除 NAS 上的文件。</p><div className="mt-5 flex justify-end gap-2"><button className="btn" disabled={busy} onClick={() => setDeleteId(null)}>取消</button><button className="btn bg-red-900/50" disabled={busy} onClick={() => run(async () => { await movieApi.delete(deleteId); store.removeMovie(deleteId); setDeleteId(null); setMessage('已从共享数据库删除'); })}>确认删除记录</button></div></Modal>}
    {browse && <LibraryBrowseDialog movies={store.movies} initial={browse} onSelect={store.selectMovie} onClose={() => setBrowse(null)} />}
    <MovieSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} onNasChanged={() => { refreshSources().catch(e => setMessage((e as Error).message)); }} />
  </div>;
}

function MenuItem({ children, onClick, disabled = false }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button role="menuitem" disabled={disabled} className="flex w-full items-center rounded px-3 py-2 text-left text-sm hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40" onClick={onClick} title={disabled ? '需要先在 NUC 挂载 NAS' : undefined}>{children}</button>;
}
