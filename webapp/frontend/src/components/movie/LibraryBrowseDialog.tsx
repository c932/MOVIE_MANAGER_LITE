import { useEffect, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieListItem, RankingItem, NewMovieItem } from '../../types/api';
import { Modal } from '../Modal';

type Kind = 'series' | 'top250' | 'imdb_top250' | 'chart' | 'nowplaying' | 'coming';
export function LibraryBrowseDialog({ movies, initial, onSelect, onClose }: {
  movies: MovieListItem[]; initial: Kind; onSelect: (id: string) => void; onClose: () => void;
}) {
  const [kind, setKind] = useState<Kind>(initial);
  const [result, setResult] = useState<{ kind: Kind; rows: (RankingItem | NewMovieItem)[]; error: string } | null>(null);
  const rows = result?.kind === kind ? result.rows : [];
  const error = result?.kind === kind ? result.error : '';
  const loading = kind !== 'series' && result?.kind !== kind;
  useEffect(() => {
    let active = true;
    if (kind === 'series') return;
    const request = kind === 'nowplaying' || kind === 'coming' ? movieApi.newMovies(kind) : movieApi.rankings(kind);
    request.then(data => { if (active) setResult({ kind, rows: data.items, error: '' }); })
      .catch(e => { if (active) setResult({ kind, rows: [], error: (e as Error).message }); });
    return () => { active = false; };
  }, [kind]);
  const groups = new Map<string, MovieListItem[]>();
  for (const movie of movies) if (movie.set_name) groups.set(movie.set_name, [...(groups.get(movie.set_name) || []), movie]);
  return <Modal title="系列、榜单与新片" wide onClose={onClose}>
    <div className="mb-4 flex flex-wrap gap-2">
      {([['series', '系列电影'], ['top250', '豆瓣 Top250'], ['imdb_top250', 'IMDb Top250'], ['chart', '豆瓣热门'], ['nowplaying', '正在上映'], ['coming', '即将上映']] as [Kind, string][]).map(([value, label]) =>
        <button key={value} className={`btn ${kind === value ? 'btn-active' : ''}`} onClick={() => setKind(value)}>{label}</button>)}
    </div>
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {loading && <p role="status">正在加载…</p>}
    {kind === 'series' ? <div className="space-y-5">{groups.size ? [...groups].sort(([a], [b]) => a.localeCompare(b, 'zh')).map(([name, members]) =>
      <section key={name}><h3 className="mb-2 font-semibold">{name}（{members.length} 部）</h3><div className="flex flex-wrap gap-2">
        {members.sort((a, b) => a.year.localeCompare(b.year)).map(movie => <button className="btn border divider" key={movie.id} onClick={() => { onSelect(movie.id); onClose(); }}>{movie.title} {movie.year}</button>)}
      </div></section>) : <p>暂无系列资料，桌面同步包含系列的电影后即可显示。</p>}</div>
      : <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">{rows.map((row, index) => <article key={`${row.title}-${index}`} className="flex gap-3 border-b divider p-3">
        {row.poster_url && <img className="h-24 w-16 object-cover" src={movieApi.proxyImageUrl(row.poster_url)} alt="" loading="lazy" />}
        <div><h3>{'rank' in row ? `${row.rank}. ` : ''}{row.title}</h3><p className="my-2 text-xs text-ink-300">{row.year} {row.rating ? `评分 ${row.rating.toFixed(1)}` : ''}</p>
          {row.movie_id ? <button className="btn" onClick={() => { onSelect(row.movie_id!); onClose(); }}>查看本库电影</button> : <span className="text-xs text-ink-400">尚未收录</span>}</div>
      </article>)}</div>}
    {!loading && !error && kind !== 'series' && !rows.length && <p className="p-6 text-ink-300">暂无缓存榜单。可先从桌面更新榜单，后续配置抓取来源。</p>}
  </Modal>;
}
