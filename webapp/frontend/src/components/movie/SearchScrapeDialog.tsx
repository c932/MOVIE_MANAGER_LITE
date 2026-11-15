import {useId,useRef,useState} from 'react';
import {Modal} from '../Modal';
import {JobProgress} from '../JobProgress';
import {movieApi} from '../../api/client';
import {scrapeApi,writeFields} from '../../api/scrape';
import type {Candidate,Draft,ScrapeRow} from '../../api/scrape';
import type {MovieListItem} from '../../types/api';
import {useScrapeTask} from '../../hooks/useScrapeTask';
import {ratingOrder,ratingNames} from '../../utils/movieDisplay';
import {ScrapeSettingsDialog} from './ScrapeSettingsDialog';

interface Props {rows:ScrapeRow[]; initial?:number; onClose:()=>void; onSaved:(movie:MovieListItem)=>void}
export function SearchScrapeDialog({rows,initial=0,onClose,onSaved}:Props) {
  const plotId=useId();
  const [index,setIndex]=useState(initial);
  const [source,setSource]=useState('douban');
  const [query,setQuery]=useState(rows[initial]?.movie.original_title||rows[initial]?.movie.title||'');
  const [year,setYear]=useState(rows[initial]?.movie.year||'');
  const [page,setPage]=useState(1);
  const [candidates,setCandidates]=useState<Candidate[]>([]);
  const [searched,setSearched]=useState(false);
  const [draft,setDraft]=useState<Draft|null>(null);
  const [title,setTitle]=useState('');
  const [plot,setPlot]=useState('');
  const [plotSource,setPlotSource]=useState('douban');
  const [poster,setPoster]=useState<number|null>(null);
  const [fields,setFields]=useState(writeFields.map(([key])=>key));
  const [overwrite,setOverwrite]=useState(false);
  const [metadataOnly,setMetadataOnly]=useState(false);
  const [rebuild,setRebuild]=useState(false);
  const [identity,setIdentity]=useState(false);
  const [settings,setSettings]=useState(false);
  const [discard,setDiscard]=useState(false);
  const [batchSaving,setBatchSaving]=useState(false);
  const batchStop=useRef(false);
  const [message,setMessage]=useState('');
  const [confirmed,setConfirmed] = useState(new Map<string,Draft>());
  const remember=(value:Draft)=>setConfirmed(old=>new Map(old).set(value.target_id,value));
  const forget=(id:string)=>setConfirmed(old=>{const next=new Map(old);next.delete(id);return next;});
  const task=useScrapeTask();
  const row=rows[index];
  if(!row)return null;
  const applyDraft=(value:Draft)=>{setDraft(value);setTitle(value.fields.title||'');setPlot(value.fields.plot||'');setPlotSource(value.plot_source);setPoster(value.poster_index===undefined?(value.artwork.length?0:null):value.poster_index);setRebuild(false);setIdentity(false);};
  async function search(nextPage=1){
    if(!query.trim()) {task.setError('请输入片名、来源 ID 或电影链接');return;}
    setMessage('');setSearched(false);setCandidates([]);setPage(nextPage);
    const result=await task.run<Candidate[]>(()=>scrapeApi.search(source,query,year,nextPage));
    if(result){setCandidates(result);setSearched(true);}
  }
  async function preview(candidate:Candidate){
    setMessage('');
    const previous=draft?.confirmed?draft.session:confirmed.get(row.id)?.session;
    const result=await task.run<Draft>(()=>scrapeApi.preview(row.id,candidate.token,previous));
    if(result)applyDraft(result);
  }
  function navigate(next:number){
    if(task.busy||next<0||next>=rows.length)return;
    if(draft?.confirmed)remember(draft);
    setIndex(next);setCandidates([]);setSearched(false);setMessage('');setPage(1);task.setError('');
    const target=rows[next];
    setQuery(target.movie.original_title||target.movie.title);setYear(target.movie.year);
    const old=confirmed.get(target.id);
    if(old)applyDraft(old);else{setDraft(null);setTitle('');setPlot('');}
  }
  const confirmOptions=()=>({title,plot,plot_source:plotSource,poster_index:poster,rebuild_nfo:rebuild});
  async function confirm(){
    if(!draft)return;
    const result=await task.run<Draft>(()=>scrapeApi.confirm(draft.session,confirmOptions()));
    if(result){setDraft(result);remember(result);setMessage('已确认匹配，检查写入字段后保存。');}
  }
  async function save(){
    if(!draft?.confirmed)return;
    const result=await task.run<MovieListItem>(()=>scrapeApi.save(draft.session,{selected_fields:fields,overwrite,metadata_only:metadataOnly,replace_identity_ack:identity}));
    if(result){onSaved(result);forget(row.id);setDraft(null);setMessage('保存成功，已更新共享数据库、系列与海报。');}
  }
  async function saveConfirmed(){
    const entries=[...confirmed.values()];
    batchStop.current=false;setBatchSaving(true);
    for(const entry of entries){
      if(batchStop.current)break;
      const result=await task.run<MovieListItem>(()=>scrapeApi.save(entry.session,{selected_fields:fields,overwrite,metadata_only:metadataOnly,replace_identity_ack:false}));
      if(!result)break;
      onSaved(result);forget(entry.target_id);
      if(entry.target_id===row.id)setDraft(null);
    }
    setBatchSaving(false);setMessage('批量保存结束；已成功保存的电影会保留。');
  }
  const close=()=>{if(task.busy||batchSaving)return;if(draft||confirmed.size)setDiscard(true);else onClose();};
  function invalidate(){if(draft){setDraft({...draft,confirmed:false});forget(row.id);}}
  return <Modal title={`搜索电影与刮削 · ${index+1}/${rows.length} · ${row.movie.title}`} wide onClose={close}>
    <div className="mb-3 flex flex-wrap items-center gap-2"><button className="btn border divider" disabled={task.busy||index===0} onClick={()=>navigate(index-1)}>上一部</button><button className="btn border divider" disabled={task.busy||index===rows.length-1} onClick={()=>navigate(index+1)}>下一部 / 跳过</button><span className="min-w-0 flex-1 truncate text-xs text-ink-300" title={row.movie.video_path}>{row.movie.video_path}</span><button className="btn" disabled={task.busy} onClick={()=>setSettings(true)}>刮削设置</button></div>
    <form noValidate onSubmit={e=>{e.preventDefault();search();}} className="mb-3 flex flex-wrap gap-2"><fieldset disabled={task.busy} className="contents">
      <label className="text-xs">搜索来源<select className="input ml-2" value={source} onChange={e=>{setSource(e.target.value);setCandidates([]);setSearched(false);setPage(1);}}><option value="douban">豆瓣</option><option value="tmdb">TMDB</option></select></label>
      <label className="flex min-w-44 flex-1 items-center gap-2 text-xs">片名<input className="input w-full" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      {!!query&&<button type="button" className="btn" aria-label="清空刮削搜索" onClick={()=>{setQuery('');setCandidates([]);setSearched(false);}}>清空</button>}
      <label className="flex items-center gap-2 text-xs">年份<input className="input w-20" value={year} maxLength={4} inputMode="numeric" onChange={e=>setYear(e.target.value.replace(/\D/g,''))}/></label><button className="btn btn-primary" type="submit">搜索</button>
    </fieldset></form>
    <p className="mb-3 text-xs text-ink-300">选择候选 → 预览详情 → 确认匹配 → 保存。自动补充可核验的三站评分；有歧义时可确认后手动匹配另一来源。</p>
    {task.error&&<p role="alert" className="mb-3 text-red-400">{task.error}</p>}{message&&<p role="status" className="mb-3 text-green-300">{message}</p>}
    <div className="grid gap-4 md:grid-cols-[minmax(230px,0.8fr)_minmax(0,1.5fr)]">
      <section className="min-w-0"><h3 className="mb-2 font-semibold">搜索候选</h3><div className="h-96 overflow-auto rounded border divider"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-ink-800"><tr><th className="p-2">标题</th><th>年份</th><th>来源 ID</th></tr></thead><tbody>{candidates.map(candidate=><tr key={candidate.token} className="border-t divider"><td className="p-2"><button className="w-full text-left text-sky-300 hover:underline" disabled={task.busy} onClick={()=>preview(candidate)}>{candidate.title}</button><p className="text-ink-400">{candidate.original_title}</p></td><td>{candidate.year}</td><td>{candidate.id}</td></tr>)}</tbody></table>{!candidates.length&&<p role="status" className="p-4 text-sm text-ink-300">{task.busy?'正在取得候选或电影资料…':searched?'未找到候选，请更换片名、年份或来源。':'请搜索并选择候选。'}</p>}</div><div className="mt-2 flex items-center justify-between"><button className="btn" disabled={task.busy||page===1} onClick={()=>search(page-1)}>上一页</button><span className="text-xs">第 {page} 页</span><button className="btn" disabled={task.busy||!candidates.length} onClick={()=>search(page+1)}>下一页</button></div></section>
      <section className="min-w-0"><h3 className="mb-2 font-semibold">详情与写入预览</h3>{!draft?<p className="p-4 text-sm text-ink-300">候选仅供预览，确认匹配后才能保存。</p>:<fieldset disabled={task.busy} className="space-y-3">
        <div className="flex gap-3">{draft.artwork[poster??0]&&<img className="h-44 w-28 object-contain" alt="候选海报" src={movieApi.proxyImageUrl(draft.artwork[poster??0].preview_url||draft.artwork[poster??0].url)}/>}<div className="min-w-0 flex-1"><label className="block text-xs">标题<input className="input mt-1 w-full" value={title} onChange={e=>{setTitle(e.target.value);invalidate();}}/></label><p className="my-2 text-xs text-ink-300">{draft.fields.original_title} · {draft.fields.year}<br/>系列：{draft.fields.set_name||'未取得'}</p><div className="flex flex-wrap gap-3">{ratingOrder.map(key=><span key={key} className="text-sm">{ratingNames[key]}：{draft.fields.ratings?.[key]?.toFixed(1)||'—'}</span>)}</div></div></div>
        <div className="text-xs"><label htmlFor={plotId}>简介来源</label><select id={plotId} className="input ml-2" value={plotSource} onChange={e=>{setPlotSource(e.target.value);setPlot(draft.source_plots[e.target.value]||draft.fields.plot||'');invalidate();}}>{draft.sources.map(item=><option key={item} value={item}>{item==='douban'?'豆瓣':'TMDB'}</option>)}</select><label className="mt-2 block" htmlFor={plotId+'-text'}>剧情简介</label><textarea id={plotId+'-text'} className="input mt-2 h-40 w-full resize-none" value={plot} onChange={e=>{setPlot(e.target.value);invalidate();}}/></div>
        <label className="block text-xs">海报<select className="input mt-1 w-full" value={poster??''} onChange={e=>{setPoster(e.target.value===''?null:Number(e.target.value));invalidate();}}><option value="">不选择新海报</option>{draft.artwork.map((art,i)=><option key={i} value={i}>{art.source} / {art.language||'未标语言'} / {art.width||'?'} × {art.height||'?'}</option>)}</select></label>
        {draft.warnings.length>0&&<div className="max-h-28 overflow-auto rounded border border-amber-600/40 p-2 text-xs text-amber-200">{draft.warnings.map((warning,i)=><p key={i}>{warning}</p>)}</div>}
        {draft.write_blocked&&<p role="status" className="text-xs text-amber-200">{draft.write_blocked}</p>}
        {draft.can_rebuild&&<label className="flex gap-2 text-sm"><input type="checkbox" checked={rebuild} onChange={e=>{setRebuild(e.target.checked);invalidate();}}/>备份原 NFO 并重建</label>}
        <button className="btn btn-primary" onClick={confirm}>{draft.confirmed?'重新确认匹配':'确认匹配 / 补充来源'}</button>
        <fieldset className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3"><legend className="mb-2 font-semibold">选择写入字段</legend>{writeFields.map(([key,label])=><label key={key} className="flex gap-2"><input type="checkbox" checked={fields.includes(key)} onChange={e=>setFields(e.target.checked?[...fields,key]:fields.filter(item=>item!==key))}/>{label}</label>)}</fieldset>
        <label className="flex gap-2 text-xs"><input type="checkbox" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>覆盖勾选字段（默认仅补缺）</label><label className="flex gap-2 text-xs"><input type="checkbox" checked={metadataOnly} onChange={e=>setMetadataOnly(e.target.checked)}/>仅保存元数据，不下载 / 替换海报</label>
        {draft.replace_identity&&<label className="flex gap-2 text-xs text-amber-200"><input type="checkbox" checked={identity} onChange={e=>setIdentity(e.target.checked)}/>已确认是另一部电影，允许替换原身份与所选资料</label>}
        <p className="break-all text-xs text-ink-400">写入：{draft.target_path}</p>
        <button className="btn btn-primary" disabled={!draft.confirmed||!!draft.write_blocked||!fields.length||(draft.replace_identity&&!identity)} onClick={save}>保存当前电影</button>
      </fieldset>}</section>
    </div>
    <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t divider pt-3"><JobProgress job={task.job} accent="cinema" onCancel={task.job?.kind==='scrape.search'||task.job?.kind==='scrape.preview'?task.cancel:undefined}/>{task.busy&&<p role="status" className="text-xs">正在处理，请等待当前请求或保存完成…</p>}<button className="btn border divider" disabled={task.busy||!confirmed.size} onClick={saveConfirmed}>保存已确认草稿（{confirmed.size}）</button><button className="btn" disabled={task.busy||batchSaving} onClick={close}>关闭</button>{batchSaving&&<button className="btn" onClick={()=>{batchStop.current=true;}}>停止后续保存</button>}</footer>
    {discard&&<Modal title="放弃未保存刮削草稿？" onClose={()=>setDiscard(false)}><p>已完成的保存会保留；当前候选和未保存草稿将关闭。</p><div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={()=>setDiscard(false)}>继续刮削</button><button className="btn btn-primary" onClick={onClose}>放弃草稿并关闭</button></div></Modal>}
    {settings&&<ScrapeSettingsDialog onClose={()=>setSettings(false)}/>}
  </Modal>;
}
