import {useCallback,useEffect,useMemo,useState} from 'react';
import {Modal} from '../Modal';
import {JobProgress} from '../JobProgress';
import {scrapeApi} from '../../api/scrape';
import type {ScrapeRow} from '../../api/scrape';
import type {MovieListItem} from '../../types/api';
import {movieApi} from '../../api/client';
import {useScrapeTask} from '../../hooks/useScrapeTask';
import {TechBadges} from './TechBadges';
import {SearchScrapeDialog} from './SearchScrapeDialog';
import {MetadataEditor} from './MetadataEditor';
import {ScrapeSettingsDialog} from './ScrapeSettingsDialog';
import {ratingNames,ratingOrder} from '../../utils/movieDisplay';

interface Props {onClose:()=>void;onSaved:(movie:MovieListItem)=>void;onSettings:()=>void}
const filename=(path:string)=>path.split(/[\\/]/).pop()||'';
export function ScrapeManager({onClose,onSaved,onSettings}:Props) {
  const [rows,setRows]=useState<ScrapeRow[]>([]);
  const [query,setQuery]=useState('');
  const [mode,setMode]=useState('all');
  const [selected,setSelected]=useState<string[]>([]);
  const [current,setCurrent]=useState('');
  const [searchRows,setSearchRows]=useState<ScrapeRow[]|null>(null);
  const [edit,setEdit]=useState<ScrapeRow|null>(null);
  const [settings,setSettings]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [sort,setSort]=useState('title');
  const [ascending,setAscending]=useState(true);
  const task=useScrapeTask();
  const reload=useCallback(async()=>{const value=await scrapeApi.rows();setRows(value.rows);},[]);
  useEffect(()=>{let active=true;scrapeApi.rows().then(value=>{if(active){setRows(value.rows);setCurrent(value.rows[0]?.id||'');}}).catch(e=>{if(active)setError((e as Error).message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[]);
  const filtered=useMemo(()=>rows.filter(row=>{
    const m=row.movie;
    if(mode==='new'&&!row.is_new)return false;
    if(mode==='douban'&&(m.ratings.douban>0&&m.douban_url||row.is_new))return false;
    return !query||[m.title,m.original_title,m.video_path].some(value=>value.toLowerCase().includes(query.toLowerCase()));
  }).sort((a,b)=>{const value=(row:ScrapeRow)=>['douban','imdb','tmdb'].includes(sort)?row.movie.ratings[sort]||0:(row.movie as unknown as Record<string,string>)[sort]||'';const av=value(a),bv=value(b);return (typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'zh-CN'))*(ascending?1:-1);}),[rows,mode,query,sort,ascending]);
  const active=rows.find(row=>row.id===current);
  const saved=(movie:MovieListItem)=>{onSaved(movie);reload().catch(e=>setError((e as Error).message));};
  async function scan(){const result=await task.run(()=>scrapeApi.scan());if(result)await reload();}
  function select(id:string,checked:boolean){setSelected(values=>checked?[...values.filter(value=>value!==id),id]:values.filter(value=>value!==id));setCurrent(id);}
  function sortBy(key:string){if(sort===key)setAscending(!ascending);else{setSort(key);setAscending(true);}}
  const allChecked=!!filtered.length&&filtered.every(row=>selected.includes(row.id));
  return <Modal title="电影资料管理" wide onClose={()=>!task.busy&&onClose()}>
    <header className="mb-3 flex flex-wrap gap-2"><button className="btn btn-primary" disabled={task.busy} onClick={scan}>更新媒体库（扫描 NAS）</button><button className="btn border divider" disabled={!active||task.busy} onClick={()=>setSearchRows(selected.length>1?filtered.filter(row=>selected.includes(row.id)):active?[active,...filtered.filter(row=>row.id!==active.id)]:[])}>搜索&刮削</button><button className="btn border divider" disabled={!active||task.busy} onClick={()=>active&&setEdit(active)}>编辑</button><button className="btn" disabled={task.busy} onClick={()=>setSettings(true)}>刮削设置</button><button className="btn" disabled={task.busy} onClick={onSettings}>NAS 与媒体库设置</button></header>
    <div className="mb-3 flex flex-wrap gap-2"><label className="flex min-w-48 flex-1 items-center gap-2 text-xs">搜索<input className="input w-full" placeholder="标题、原名或文件名…" value={query} onChange={e=>setQuery(e.target.value)}/></label>{query&&<button className="btn" aria-label="清空管理列表搜索" onClick={()=>setQuery('')}>清空</button>}<label className="text-xs">显示<select className="input ml-2" value={mode} onChange={e=>setMode(e.target.value)}><option value="all">全部电影</option><option value="new">新增 / 待刮削</option><option value="douban">仅缺豆瓣评分和链接</option></select></label></div>
    {(error||task.error)&&<p role="alert" className="mb-3 text-red-400">{error||task.error}<button className="btn" onClick={()=>{setError('');reload().catch(e=>setError((e as Error).message));}}>重新读取列表</button></p>}
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(280px,1fr)]"><section className="min-w-0"><div className="h-[58dvh] overflow-auto rounded border divider"><table className="w-max min-w-full border-collapse text-left text-xs"><thead className="sticky top-0 z-10 bg-ink-800"><tr><th className="p-2"><input aria-label="选择当前筛选的全部电影" type="checkbox" checked={allChecked} onChange={e=>setSelected(e.target.checked?filtered.map(row=>row.id):[])}/></th>{[['title','标题'],['year','年份'],['premiered','上映日期'],['video_path','文件名'],['douban','豆瓣'],['imdb','IMDb'],['tmdb','TMDB'],['resolution','分辨率'],['hdr_type','HDR']].map(([key,label])=><th className="p-2" key={key} aria-sort={sort===key?(ascending?'ascending':'descending'):'none'}><button onClick={()=>sortBy(key)} className="whitespace-nowrap">{label}{sort===key?(ascending?' ↑':' ↓'):''}</button></th>)}{['新增','海报','字幕','刮削状态'].map(label=><th key={label} className="whitespace-nowrap p-2">{label}</th>)}</tr></thead><tbody>{filtered.map(row=><tr key={row.id} className={`border-t divider ${current===row.id?'bg-cinema-950/50':'hover:bg-ink-800'}`}><td className="p-2"><input type="checkbox" checked={selected.includes(row.id)} aria-label={`选择 ${row.movie.title}`} onChange={e=>select(row.id,e.target.checked)}/></td><td className="max-w-48 truncate p-2" title={row.movie.title}><button className="text-sky-300 hover:underline" onClick={()=>setCurrent(row.id)} onDoubleClick={()=>setSearchRows([row])}>{row.movie.title||filename(row.movie.video_path)}</button></td><td className="p-2">{row.movie.year||'—'}</td><td className="p-2">{row.movie.premiered||'—'}</td><td className="max-w-56 truncate p-2" title={row.movie.video_path}>{filename(row.movie.video_path)}</td>{ratingOrder.map(source=><td className="p-2 font-mono" key={source}>{row.movie.ratings[source]?.toFixed(1)||'—'}</td>)}<td className="p-2">{row.movie.resolution||'—'}</td><td className="p-2">{row.movie.hdr_type||'—'}</td><td className="p-2">{row.is_new?'是':'否'}</td><td className="p-2">{row.poster_exists==null?'未知':row.poster_exists?'✓':'×'}</td><td className="p-2">{row.subtitle_count??'未知'}</td><td className="whitespace-nowrap p-2" title={row.error}>{row.status}</td></tr>)}</tbody></table>{!filtered.length&&<p role="status" className="p-5 text-sm text-ink-300">{loading?'正在恢复管理列表…':rows.length?'没有符合筛选条件的电影。':'管理列表为空，请更新媒体库或配置 NAS 目录。'}</p>}</div></section>
    <aside className="h-[58dvh] overflow-y-auto">{active?<><h3 className="text-xl font-semibold">{active.movie.title}</h3><p className="mb-3 text-sm text-ink-300">{active.movie.original_title}</p><div className="flex gap-3">{active.movie.has_poster&&<img className="h-56 w-36 object-contain" alt={active.movie.title+' 海报'} src={movieApi.posterUrl(active.movie_id,360,540,'contain')}/>}<dl className="space-y-2 text-sm">{[['年份',active.movie.year],['上映日期',active.movie.premiered],['片长',active.movie.runtime],['类型',active.movie.genres.join(' / ')],['国家 / 地区',active.movie.countries.join(' / ')],['系列',active.movie.set_name]].map(([label,value])=><div key={label}><dt className="text-ink-400">{label}</dt><dd>{value||'—'}</dd></div>)}</dl></div><div className="my-3"><TechBadges resolution={active.movie.resolution} hdrType={active.movie.hdr_type}/></div><div className="my-3 flex gap-3">{ratingOrder.map(source=><div key={source} className="rounded bg-ink-800 px-2 py-1 text-center"><span className="text-xs text-ink-300">{ratingNames[source]}</span><p className="text-lg text-gold">{active.movie.ratings[source]?.toFixed(1)||'—'}</p></div>)}</div><h4 className="mb-2 font-semibold">剧情简介</h4><p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-300">{active.movie.plot||'尚无简介'}</p><h4 className="mb-2 mt-4 font-semibold">演职人员</h4><p className="text-sm text-ink-300">导演：{active.movie.directors.join(' / ')||'未取得'}</p><p className="text-sm text-ink-300">{active.movie.actors.map(actor=>actor.name+(actor.role?' · '+actor.role:'')).join(' / ')}</p><h4 className="mb-2 mt-4 font-semibold">视频文件</h4><p className="break-all text-xs text-ink-300">{active.movie.video_path}</p>{active.error&&<p role="alert" className="mt-3 text-sm text-amber-200">{active.error}</p>}</>:<p className="text-sm text-ink-300">选择一部电影查看详细资料。</p>}</aside></div>
    <footer className="mt-3 flex flex-wrap items-center gap-3 border-t divider pt-3 text-xs"><span>{filtered.length} / {rows.length} 部 · 已选 {selected.length} 部</span><span>已恢复保存列表，只有点击更新媒体库才扫描 NAS。</span><JobProgress job={task.job} accent="cinema" onCancel={task.cancel}/>{task.job?.message&&<p className="w-full break-all select-text">{task.job.message}</p>}</footer>
    {searchRows&&<SearchScrapeDialog rows={searchRows} onClose={()=>setSearchRows(null)} onSaved={saved}/>}
    {edit&&<MetadataEditor row={edit} onClose={()=>setEdit(null)} onSaved={saved}/>}
    {settings&&<ScrapeSettingsDialog onClose={()=>setSettings(false)}/>}
  </Modal>;
}
