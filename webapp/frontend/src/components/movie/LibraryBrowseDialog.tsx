import { useEffect, useState } from 'react';
import { movieApi } from '../../api/client';
import type { AnnualResponse, MovieListItem, RankingItem, NewMovieItem } from '../../types/api';
import { Modal } from '../Modal';
import { FloatingMovieDetail } from './FloatingMovieDetail';
import { MovieDetail } from './MovieDetail';
import { BilibiliActions } from './BilibiliActions';

type Kind = 'series' | 'top250' | 'imdb_top250' | 'chart' | 'nowplaying' | 'coming' | 'annual';
type Item = RankingItem | NewMovieItem;
type Result = {key: string; rows: Item[]; annual?: AnnualResponse; fetched: number; error: string; refreshing: boolean};
const latestYear = new Date().getFullYear() - 1;
const tabs: [Kind, string][] = [['series', '系列电影'], ['top250', '豆瓣 Top250'], ['imdb_top250', 'IMDb Top250'], ['chart', '豆瓣热门'], ['annual', '豆瓣年度榜单'], ['nowplaying', '正在上映'], ['coming', '即将上映']];

function BrowsePoster({row}: {row: Item}) {
  const [failed, setFailed] = useState<Set<string>>(() => new Set());
  const localUrl = row.movie_id ? movieApi.posterUrl(row.movie_id, 240, 360) : '';
  const remoteUrl = row.poster_url ? movieApi.proxyImageUrl(row.poster_url) : '';
  const source = [localUrl, remoteUrl].find(url => url && !failed.has(url)) || '';
  return <span className="flex h-36 w-24 shrink-0 items-center justify-center overflow-hidden rounded bg-ink-800 text-xs text-ink-400">
    {source
      ? <img className="h-full w-full object-cover" src={source} alt="" loading="lazy" decoding="async" onError={() => setFailed(current => new Set(current).add(source))} />
      : '暂无海报'}
  </span>;
}

function MissingMovie({row, onClose}: {row: Item; onClose: () => void}) {
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState({plot: '', error: '', loading: true});
  const did = row.douban_id || row.douban_url?.match(/subject\/(\d+)/)?.[1];
  useEffect(() => {
    let active = true;
    async function load() {
      setDetail({plot: '', error: '', loading: true});
      if (!did) {setDetail({plot: '', error: '该榜单暂无豆瓣条目，无法读取简介。', loading: false}); return;}
      try {
        const {job_id} = await movieApi.subject(did);
        while (active) {
          const job = await movieApi.get(job_id);
          if (!active) return;
          if (job.status === 'done') {setDetail({plot: (job.result as {plot: string}).plot, error: '', loading: false}); return;}
          if (job.status === 'error' || job.status === 'cancelled') throw new Error(job.error || '简介读取已取消');
          await new Promise(resolve => setTimeout(resolve, 600));
        }
      } catch(e) {if (active) setDetail({plot: '', error: (e as Error).message, loading: false});}
    }
    void load();
    return () => {active = false;};
  }, [did, attempt]);
  return <Modal title={`${row.title} · 电影简介`} onClose={onClose}>
    <div className="flex gap-5"><BrowsePoster row={row} /><div><h3 className="text-xl font-semibold">{row.title}</h3><p className="my-2 text-ink-300">{row.year} {row.rating ? `豆瓣 ${row.rating.toFixed(1)}` : ''}</p><p className="text-sm text-ink-400">尚未收录到媒体库</p></div></div>
    <div className="my-6 min-h-24 max-w-prose whitespace-pre-line leading-relaxed">
      {detail.loading && <p role="status">正在读取电影简介…</p>}
      {detail.error && <div role="alert"><p>{detail.error}</p>{did && <button className="btn mt-3" onClick={() => setAttempt(value => value + 1)}>重试简介</button>}</div>}
      {detail.plot}
    </div>
    <div className="flex flex-wrap gap-3"><a className="btn btn-active" href={`https://www.zhongchuangwl.com/s/${encodeURIComponent(row.title)}/`} target="_blank" rel="noopener noreferrer">打开夸克盘搜</a>
      <BilibiliActions title={row.title} year={row.year}/>
      {did && <a className="btn" href={`https://movie.douban.com/subject/${did}/`} target="_blank" rel="noopener noreferrer">豆瓣条目</a>}</div>
  </Modal>;
}

export function LibraryBrowseDialog({ movies, initial, onSelect, onClose, onUpdated, onDeleted, onSeriesClick, onRefreshPoster, onEditFields }: {
  movies: MovieListItem[]; initial: Kind; onSelect: (id: string) => void; onClose: () => void;
  onUpdated?: (movie: MovieListItem) => void;
  onDeleted?: (id: string) => void;
  onSeriesClick?: (name: string) => void;
  onRefreshPoster?: (id: string) => void;
  onEditFields?: (movie: MovieListItem) => void;
}) {
  const [kind, setKind] = useState<Kind>(initial);
  const [year, setYear] = useState(latestYear);
  const [category, setCategory] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [missing, setMissing] = useState<Item | null>(null);
  const [owned, setOwned] = useState<MovieListItem | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const key = `${kind}-${year}`;
  const current = result?.key === key ? result : null;
  useEffect(() => {
    let active = true;
    if (kind === 'series') return;
    const isNew = kind === 'nowplaying' || kind === 'coming';
    async function read(): Promise<Result> {
      if (kind === 'annual') {
        const data = await movieApi.annual(year);
        return {key, rows: [], annual: data, fetched: data.fetched_at, error: '', refreshing: false};
      }
      const data = await (isNew ? movieApi.newMovies(kind as 'nowplaying' | 'coming') : movieApi.rankings(kind as 'top250' | 'chart' | 'imdb_top250'));
      return {key, rows: data.items, fetched: data.fetched_at, error: '', refreshing: false};
    }
    async function load() {
      let cached: Result = {key, rows: [], fetched: 0, error: '', refreshing: false};
      try {
        cached = await read();
        if (!active) return;
        setResult(cached);
        const ttl = kind === 'annual' ? 7 * 86400 : kind === 'chart' || isNew ? 6 * 3600 : 86400;
        if (!refresh && cached.fetched && Date.now() / 1000 - cached.fetched < ttl) return;
        setResult({...cached, refreshing: true});
        const started = kind === 'annual' ? await movieApi.refreshAnnual(year) : isNew ? await movieApi.fetchNewMovies([kind], false) : await movieApi.fetchRankings([kind], false);
        while (active) {
          const job = await movieApi.get(started.job_id);
          if (!active) return;
          if (job.status === 'done') {const updated = await read(); if (active) setResult(updated); return;}
          if (job.status === 'error' || job.status === 'cancelled') throw new Error(job.error || '刷新已取消');
          await new Promise(resolve => setTimeout(resolve, 800));
        }
      } catch(e) {if (active) setResult({...cached, error: (e as Error).message, refreshing: false});}
    }
    void load();
    return () => {active = false;};
  }, [kind, year, key, refresh]);
  const categories = current?.annual?.categories || [];
  const selectedCategory = categories.find(item => item.id === category) || categories[0];
  const rows = kind === 'annual' ? selectedCategory?.items || [] : current?.rows || [];
  const groups = new Map<string, MovieListItem[]>();
  for (const movie of movies) if (movie.set_name) groups.set(movie.set_name, [...(groups.get(movie.set_name) || []), movie]);
  function select(row: Item) {
    if (row.movie_id) {
      const local = movies.find(movie => movie.id === row.movie_id);
      if (local) { setOwned(local); return; }
      onSelect(row.movie_id);
      onClose();
      return;
    }
    setMissing(row);
  }
  return <>
    <Modal title="系列、榜单与新片" wide onClose={onClose}>
      <div className="mb-4 flex flex-wrap gap-2">{tabs.map(([value, label]) => <button key={value} className={`btn ${kind === value ? 'btn-active' : ''}`} aria-pressed={kind === value} onClick={() => {setKind(value); setRefresh(0);}}>{label}</button>)}</div>
      {kind === 'annual' && <div className="mb-4 flex flex-wrap items-center gap-3">
        <label>年度 <select className="input" aria-label="榜单年度" value={year} onChange={e => {setYear(Number(e.target.value)); setCategory(''); setRefresh(0);}}>{Array.from({length: Math.max(1, latestYear - 2018)}, (_, i) => latestYear - i).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        {!!categories.length && <label>分类 <select className="input max-w-full" aria-label="年度电影分类" value={selectedCategory?.id || ''} onChange={e => setCategory(e.target.value)}>{categories.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
        <a className="btn text-sm" target="_blank" rel="noopener noreferrer" href={`https://movie.douban.com/annual/${year}/`}>豆瓣年度原榜</a>
      </div>}
      {kind !== 'series' && <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-300">
        <span>{current?.fetched ? `更新于 ${new Date(current.fetched * 1000).toLocaleString('zh-CN')}` : '尚无缓存'}{current?.refreshing ? ' · 正在获取最新榜单…' : ''}</span>
        <button className="btn" disabled={!current || current.refreshing} onClick={() => setRefresh(value => value + 1)}>刷新榜单</button>
      </div>}
      {current?.error && <p role="alert" className="mb-4 text-red-400">{current.error}{rows.length ? ' 当前显示上次成功获取的榜单。' : ''}</p>}
      {kind !== 'series' && !current && <p role="status">正在加载榜单…</p>}
      {kind === 'series' ? <div className="space-y-5">{groups.size ? [...groups].sort(([a], [b]) => a.localeCompare(b, 'zh')).map(([name, members]) =>
        <section key={name}><h3 className="mb-2 font-semibold">{name}（{members.length} 部）</h3><div className="flex flex-wrap gap-2">
          {members.sort((a, b) => a.year.localeCompare(b.year)).map(movie => <button className="btn border divider" key={movie.id} onClick={() => {onSelect(movie.id); onClose();}}>{movie.title} {movie.year}</button>)}
        </div></section>) : <p>暂无系列资料，同步或刮削包含系列的电影后即可显示。</p>}</div>
        : <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">{rows.map((row, index) => <button key={`${row.movie_id || row.douban_id || row.title}-${index}-${row.poster_url}`} onClick={() => select(row)} className="flex gap-4 rounded border-b divider p-3 text-left transition-colors hover:bg-ink-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cinema-400" aria-label={`${row.title}，查看简介`}>
          <BrowsePoster row={row} /><span className="min-w-0"><span className="block font-semibold">{'rank' in row ? `${row.rank}. ` : ''}{row.title}</span><span className="my-3 block text-xs text-ink-300">{row.year} {row.rating ? `评分 ${row.rating.toFixed(1)}` : ''}</span>
            <span className={`text-xs ${row.movie_id ? 'text-cinema-400' : 'text-ink-400'}`}>{row.movie_id ? '已入库 · 查看简介' : '查看简介 · 夸克盘搜'}</span></span>
        </button>)}</div>}
      {kind !== 'series' && current && !current.refreshing && !current.error && !rows.length && <p className="p-6 text-ink-300">暂无榜单资料，请点击“刷新榜单”。</p>}
    </Modal>
    {missing && <MissingMovie key={missing.douban_id || missing.title} row={missing} onClose={() => setMissing(null)} />}
    {owned && <FloatingMovieDetail title={`${owned.title} · 电影详情`} onClose={() => setOwned(null)}>
      <MovieDetail movie={owned}
        onUpdated={movie => { setOwned(movie); onUpdated?.(movie); }}
        onDeleted={id => { setOwned(null); onDeleted?.(id); }}
        onSeriesClick={name => { setOwned(null); onSeriesClick?.(name); onClose(); }}
        onRefreshPoster={id => onRefreshPoster?.(id)}
        onEditFields={movie => { setOwned(null); onEditFields?.(movie); }} />
    </FloatingMovieDetail>}
  </>;
}
