import { useEffect, useMemo, useState } from 'react';
import { movieApi } from '../../api/client';
import type { AnnualResponse, MovieListItem, RankingItem, NewMovieItem, SeriesMovie, SeriesListing } from '../../types/api';
import { quarkSearchUrl } from '../../utils/movieDisplay';
import { Modal } from '../Modal';
import { FloatingMovieDetail } from './FloatingMovieDetail';
import { MovieDetail } from './MovieDetail';
import { BilibiliActions } from './BilibiliActions';
import { LocalPlayback } from './LocalPlayback';
import { localSeriesMovie } from './useSeriesListing';

type Kind = 'series' | 'top250' | 'imdb_top250' | 'chart' | 'nowplaying' | 'coming' | 'annual';
type Item = RankingItem | NewMovieItem;
type BrowseItem = Item | SeriesMovie;
type Result = {key: string; rows: Item[]; annual?: AnnualResponse; fetched: number; error: string; refreshing: boolean};
const latestYear = new Date().getFullYear() - 1;
const tabs: [Kind, string][] = [['series', '系列电影'], ['top250', '豆瓣 Top250'], ['imdb_top250', 'IMDb Top250'], ['chart', '豆瓣热门'], ['annual', '豆瓣年度榜单'], ['nowplaying', '正在上映'], ['coming', '即将上映']];
const shanghaiDate = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'});

function releaseDate(row: BrowseItem) {
  return ('release_date' in row ? row.release_date : row.premiered) || '';
}

function isUnreleased(row: BrowseItem, kind: Kind, today: string) {
  const date = releaseDate(row);
  if (/^\d{4}-\d{2}-\d{2}$/.test(date)) return date > today;
  return kind === 'coming' || row.year > today.slice(0, 4);
}

function BrowsePoster({row}: {row: BrowseItem}) {
  const [failed, setFailed] = useState<Set<string>>(() => new Set());
  const localUrl = row.movie_id ? movieApi.posterUrl(row.movie_id, 240, 360) : '';
  const remoteUrl = row.poster_url ? movieApi.proxyImageUrl(row.poster_url, true) : '';
  const source = [localUrl, remoteUrl].find(url => url && !failed.has(url)) || '';
  return <span className="flex h-36 w-24 shrink-0 items-center justify-center overflow-hidden rounded bg-ink-800 text-xs text-ink-400">
    {source
      ? <img className="h-full w-full object-cover" src={source} alt="" loading="lazy" decoding="async" onError={() => setFailed(current => new Set(current).add(source))} />
      : '暂无海报'}
  </span>;
}

function MissingMovie({row, unreleased, onClose}: {row: BrowseItem; unreleased: boolean; onClose: () => void}) {
  const source = 'tmdb_id' in row ? 'tmdb' : ('rating_source' in row && row.rating_source) || 'douban';
  return <FloatingMovieDetail title={`${row.title} · 电影简介`} onClose={onClose}>
    <MovieDetail movie={null} unreleased={unreleased} external={{
      title: row.title, original_title: 'original_title' in row ? row.original_title : '',
      year: row.year, premiered: releaseDate(row), plot: row.plot || '',
      ratings: {[source]: row.rating}, genres: 'genre' in row ? row.genre.split(' / ').filter(Boolean) : [],
      douban_url: 'douban_url' in row ? row.douban_url || '' : '', poster_url: row.poster_url,
    }} />
  </FloatingMovieDetail>;
}

export function LibraryBrowseDialog({ movies, initial, onClose, onUpdated, onDeleted, onSeriesClick, onRefreshPoster, onEditFields }: {
  movies: MovieListItem[]; initial: Kind; onClose: () => void;
  onUpdated?: (movie: MovieListItem) => void;
  onDeleted?: (id: string) => void;
  onSeriesClick?: (name: string) => void;
  onRefreshPoster?: (id: string) => void;
  onEditFields?: (movie: MovieListItem) => void;
}) {
  const [kind, setKind] = useState<Kind>(initial);
  const [today] = useState(() => shanghaiDate.format(new Date()));
  const [seriesQuery, setSeriesQuery] = useState('');
  const [seriesFilter, setSeriesFilter] = useState('all');
  const [seriesCatalog, setSeriesCatalog] = useState<SeriesListing[] | null>(null);
  const [year, setYear] = useState(latestYear);
  const [category, setCategory] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [missing, setMissing] = useState<BrowseItem | null>(null);
  const [owned, setOwned] = useState<MovieListItem | null>(null);
  const [ownedRow, setOwnedRow] = useState<BrowseItem | null>(null);
  const [detailError, setDetailError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const localGroups = useMemo(() => {
    if (kind !== 'series') return [];
    const groups = new Map<string, SeriesMovie[]>();
    for (const movie of movies) if (movie.set_name) {
      if (!groups.has(movie.set_name)) groups.set(movie.set_name, []);
      groups.get(movie.set_name)!.push(localSeriesMovie(movie));
    }
    return Array.from(groups, ([name, items]): SeriesListing => ({name, source: 'local', items: items.sort(
      (a, b) => (a.premiered || a.year || '9999').localeCompare(b.premiered || b.year || '9999'),
    )}));
  }, [kind, movies]);
  useEffect(() => {
    if (kind !== 'series') return;
    let active = true;
    movieApi.allSeries().then(({groups}) => { if (active) setSeriesCatalog(groups); },
      () => { if (active) setSeriesCatalog(null); });
    return () => { active = false; };
  }, [kind]);
  const moviesById = useMemo(() => new Map(movies.map(movie => [movie.id, movie])), [movies]);
  const ownedId = ownedRow?.movie_id;
  const plot = ownedRow?.plot;
  useEffect(() => {
    if (!ownedId) return;
    let active = true;
    movieApi.detail(ownedId).then(movie => {
      if (active) setOwned({...movie, plot: movie.plot || plot || ''});
    }, () => { if (active) setDetailError('暂时无法读取本地电影详情。'); });
    return () => { active = false; };
  }, [ownedId, plot]);
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
        if (!refresh) {
          if (kind === 'chart' || isNew) return;
          const ttl = kind === 'annual' ? 7 * 86400 : 86400;
          if (cached.fetched && Date.now() / 1000 - cached.fetched < ttl) return;
        }
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
  const query = seriesQuery.trim().toLocaleLowerCase();
  const groups = (seriesCatalog ?? localGroups)
    .map(group => ({...group, items: group.items.filter(row => {
      const matchesText = !query || [group.name, row.title, row.original_title, row.year].some(text => text.toLocaleLowerCase().includes(query));
      return matchesText && (seriesFilter === 'all' || (seriesFilter === 'owned' && !!row.movie_id)
        || (seriesFilter === 'missing' && !row.movie_id) || (seriesFilter === 'unreleased' && isUnreleased(row, 'series', today)));
    })})).filter(group => group.items.length).sort((a, b) => a.name.localeCompare(b.name, 'zh'));
  function select(row: BrowseItem) {
    if (row.movie_id) {
      const local = moviesById.get(row.movie_id);
      setDetailError('');
      setOwned(local ? {...local, plot: row.plot || local.plot} : null);
      setOwnedRow(row);
      return;
    }
    setMissing(row);
  }

  function cards(items: BrowseItem[]) {
    return <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">{items.map((row, index) => {
      const seriesRow = 'tmdb_id' in row;
      const local = seriesRow && row.movie_id ? moviesById.get(row.movie_id) : undefined;
      const upcoming = isUnreleased(row, kind, today);
      return <article key={seriesRow ? row.movie_id || row.tmdb_id : `${row.movie_id || row.title}-${index}-${row.poster_url}`}
        aria-label={row.title} className="relative flex gap-4 rounded border-b divider p-3 transition-colors hover:bg-ink-800">
        <BrowsePoster row={row} />
        <div className="min-w-0">
          <button type="button" onClick={() => select(row)} aria-label={`${row.title}，查看简介`}
            className="block text-left font-semibold after:absolute after:inset-0 after:rounded focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-cinema-400">
            {'rank' in row ? `${row.rank}. ` : ''}{row.title}{upcoming && <span className="ml-1 text-xs font-normal text-amber-300">（未上映）</span>}
          </button>
          <p className="my-3 text-xs text-ink-300">{upcoming ? releaseDate(row) || row.year : row.year} {row.rating ? `评分 ${row.rating.toFixed(1)}` : ''}</p>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-300 [&_a]:relative [&_a]:z-[1]">
            {row.movie_id ? <>
              <span className="whitespace-nowrap text-cinema-400">已入库 · 查看简介</span>
              {local?.video_path && <LocalPlayback movie={local} compact />}
            </> : <>
              <span className="whitespace-nowrap text-ink-400">{seriesRow ? '未入库 · 查看简介' : '查看简介'}</span>
              <a className="whitespace-nowrap hover:underline focus-visible:underline" href={quarkSearchUrl(row.title)} target="_blank" rel="noopener noreferrer">夸克盘搜</a>
            </>}
            <BilibiliActions playOnly title={row.title} originalTitle={'original_title' in row ? row.original_title : ''} year={row.year} />
          </div>
        </div>
      </article>;
    })}</div>;
  }
  return <>
    <Modal title="系列、榜单与新片" wide onClose={onClose}>
      <div className="mb-4 flex flex-wrap gap-2">{tabs.map(([value, label]) => <button key={value} className={`btn ${kind === value ? 'btn-active' : ''}`} aria-pressed={kind === value} onClick={() => {setKind(value); setRefresh(0);}}>{label}</button>)}</div>
      {kind === 'series' && <div className="mb-4 flex flex-wrap items-center gap-3">
        <input className="input min-w-0" aria-label="搜索系列或电影" placeholder="搜索系列或电影…" type="search" value={seriesQuery} onChange={event => setSeriesQuery(event.target.value)} />
        <label className="flex items-center gap-2 text-sm">片单状态 <select className="input" value={seriesFilter} onChange={event => setSeriesFilter(event.target.value)}>
          <option value="all">全部电影</option><option value="owned">已入库</option><option value="missing">未入库</option><option value="unreleased">未上映</option>
        </select></label>
        <p role="status" className="text-xs text-ink-300">{groups.length} 个系列 · {groups.reduce((count, group) => count + group.items.length, 0)} 部电影</p>
      </div>}
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
      {kind === 'series' ? <div className="space-y-6">{groups.length ? groups.map(group => (
        <section key={group.name} aria-label={group.name}>
          <h3 className="mb-2 text-base font-semibold">{group.name} <span className="text-xs font-normal text-ink-400">{group.items.length} 部</span></h3>
          {cards(group.items)}
        </section>
      )) : <p className="text-sm text-ink-300">没有符合条件的系列电影。</p>}</div> : cards(rows)}
      {kind !== 'series' && current && !current.refreshing && !current.error && !rows.length && <p className="p-6 text-ink-300">暂无榜单资料，请点击“刷新榜单”。</p>}
    </Modal>
    {missing && <MissingMovie row={missing} unreleased={isUnreleased(missing, kind, today)} onClose={() => setMissing(null)} />}
    {ownedRow && <FloatingMovieDetail title={`${owned?.title || ownedRow.title} · 电影详情`} onClose={() => setOwnedRow(null)}>
      {owned ? <MovieDetail key={owned.id} movie={owned} movies={movies} posterFallback={ownedRow.poster_url}
        unreleased={isUnreleased(ownedRow, kind, today)}
        onUpdated={movie => { setOwned(movie); onUpdated?.(movie); }}
        onDeleted={id => { setOwnedRow(null); onDeleted?.(id); }}
        onSeriesClick={name => { setOwnedRow(null); onSeriesClick?.(name); onClose(); }}
        onSelectSeriesMovie={id => { const movie = moviesById.get(id); if (movie) select(localSeriesMovie(movie)); }}
        onRefreshPoster={id => onRefreshPoster?.(id)}
        onEditFields={movie => { setOwnedRow(null); onEditFields?.(movie); }} />
        : <p className="p-4 text-sm" role={detailError ? 'alert' : 'status'}>{detailError || '正在读取本地电影详情…'}</p>}
    </FloatingMovieDetail>}
  </>;
}
