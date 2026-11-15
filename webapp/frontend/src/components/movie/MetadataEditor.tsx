import {useEffect,useRef,useState} from 'react';
import {Modal} from '../Modal';
import {JobProgress} from '../JobProgress';
import {movieApi} from '../../api/client';
import {scrapeApi} from '../../api/scrape';
import type {EditorSnapshot,ScrapeRow} from '../../api/scrape';
import type {MovieListItem,Actor} from '../../types/api';
import {useScrapeTask} from '../../hooks/useScrapeTask';
import {ratingOrder,ratingNames} from '../../utils/movieDisplay';

export function MetadataEditor({row,onClose,onSaved}:{row:ScrapeRow;onClose:()=>void;onSaved:(movie:MovieListItem)=>void}) {
  const [snapshot,setSnapshot]=useState<EditorSnapshot|null>(null);
  const [changes,setChanges]=useState<Record<string,unknown>>({});
  const [listText,setListText]=useState<Record<string,string>>({});
  const [votes,setVotes]=useState<Record<string,number>>({});
  const [poster,setPoster]=useState<string>();
  const [tab,setTab]=useState('影视信息');
  const [discard,setDiscard]=useState(false);
  const task=useScrapeTask();
  const load=useRef(task.run);
  useEffect(()=>{let active=true;Promise.resolve().then(async()=>{if(!active)return;const value=await load.current<EditorSnapshot>(()=>scrapeApi.edit(row.id));if(active&&value)setSnapshot(value);});return()=>{active=false;};},[row.id]);
  const dirty=!!Object.keys(changes).length||!!Object.keys(votes).length||!!poster;
  const close=()=>{if(task.busy)return;if(dirty)setDiscard(true);else onClose();};
  const movie=snapshot?.movie;
  const value=(key:string)=>key==='ratings'?{...movie?.ratings,...(changes.ratings as object||{})}:key in changes?changes[key]:(movie as unknown as Record<string,unknown>)?.[key];
  function change(key:string,data:unknown){setChanges(previous=>({...previous,[key]:data}));}
  const text=(key:string)=>String(value(key)??'');
  const list=(key:string)=>listText[key]??(value(key) as string[]||[]).join(' / ');
  const changeList=(key:string,text:string)=>{setListText(old=>({...old,[key]:text}));change(key,text.split('/').map(item=>item.trim()).filter(Boolean));};
  const actors=(value('actors') as Actor[])||[];
  const updateActor=(index:number,key:string,text:string)=>change('actors',actors.map((actor,i)=>i===index?{...actor,[key]:text}:actor));
  async function save(){if(!snapshot)return;const result=await task.run<MovieListItem>(()=>scrapeApi.saveEditor(snapshot.session,changes,votes,poster));if(result){onSaved(result);onClose();}}
  async function file(input:File|undefined){
    if(!input)return;
    if(input.size>10*1024*1024){task.setError('海报文件应小于 10 MB');return;}
    const bytes=new Uint8Array(await input.arrayBuffer());let encoded='';
    for(let i=0;i<bytes.length;i+=16384)encoded+=String.fromCharCode(...bytes.subarray(i,i+16384));
    setPoster(btoa(encoded));
  }
  return <Modal title={`编辑电影资料 · ${row.movie.title}`} wide onClose={close}>
    {task.error&&<p role="alert" className="mb-3 text-red-400">{task.error}</p>}
    {!movie?<p role="status">{task.busy?'正在读取 NFO…':'无法加载原 NFO，请先搜索匹配或重新加载。'}</p>:<>
      <nav className="mb-4 flex flex-wrap gap-2" aria-label="编辑分类">{['影视信息','评分与来源','演职人员','视频文件'].map(name=><button className={`btn ${tab===name?'btn-active':''}`} key={name} disabled={task.busy} onClick={()=>setTab(name)}>{name}</button>)}</nav>
      <fieldset disabled={task.busy} className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]"><div className="min-w-0 space-y-3">
        {tab==='影视信息'&&<>{[['title','标题'],['original_title','原名'],['tagline','宣传语'],['year','年份'],['premiered','上映日期'],['runtime','片长（分钟）'],['set_name','系列']].map(([key,label])=><label key={key} className="block text-sm">{label}<input className="input mt-1 w-full" value={text(key)} onChange={e=>change(key,e.target.value)}/></label>)}<label className="block text-sm">剧情简介<textarea className="input mt-1 h-48 w-full resize-none" value={text('plot')} onChange={e=>change('plot',e.target.value)}/></label>{[['genres','类型'],['countries','国家地区']].map(([key,label])=><label key={key} className="block text-sm">{label}（用 / 分隔）<input className="input mt-1 w-full" value={list(key)} onChange={e=>changeList(key,e.target.value)}/></label>)}</>}
        {tab==='评分与来源'&&ratingOrder.map(source=><section key={source} className="space-y-2 rounded border divider p-3"><h3>{ratingNames[source]}</h3><div className="grid grid-cols-2 gap-2"><label className="text-xs">评分（0–10）<input className="input mt-1 w-full" type="number" min="0" max="10" step="0.1" value={(value('ratings') as Record<string,number>)?.[source]??''} onChange={e=>change('ratings',{...(changes.ratings as object||{}),[source]:e.target.value===''?null:Number(e.target.value)})}/></label><label className="text-xs">评分人数<input className="input mt-1 w-full" type="number" min="0" step="1" value={votes[source]??snapshot!.votes[source]??0} onChange={e=>setVotes({...votes,[source]:Number(e.target.value)})}/></label></div><label className="block text-xs">来源 ID<input className="input mt-1 w-full" value={(changes.uniqueids as Record<string,string>)?.[source]??snapshot!.uniqueids[source]??''} onChange={e=>change('uniqueids',{...(changes.uniqueids as object||{}),[source]:e.target.value})}/></label></section>)}
        {tab==='演职人员'&&<><label className="block text-sm">导演（用 / 分隔）<input className="input mt-1 w-full" value={list('directors')} onChange={e=>changeList('directors',e.target.value)}/></label><div className="space-y-2">{actors.map((actor,i)=><div className="flex gap-2" key={i}><input className="input min-w-0 flex-1" aria-label={`演员 ${i+1} 姓名`} value={actor.name} onChange={e=>updateActor(i,'name',e.target.value)}/><input className="input min-w-0 flex-1" aria-label={`演员 ${i+1} 角色`} value={actor.role} onChange={e=>updateActor(i,'role',e.target.value)}/><button className="btn" onClick={()=>change('actors',actors.filter((_,n)=>n!==i))}>移除</button></div>)}</div><button className="btn border divider" onClick={()=>change('actors',[...actors,{name:'',role:'',thumb:''}])}>添加演员</button></>}
        {tab==='视频文件'&&<dl className="space-y-3 break-all text-sm">{[['视频',movie.video_path],['NFO',movie.nfo_path],['海报',movie.poster_path],['分辨率',movie.resolution],['HDR',movie.hdr_type],['视频编码',movie.video_codec],['音频编码',movie.audio_codec]].map(([label,text])=><div key={label}><dt className="text-ink-400">{label}</dt><dd>{text||'未知'}</dd></div>)}</dl>}
      </div><aside><img alt="当前海报" className="mb-3 aspect-[2/3] w-full object-contain" src={poster?`data:image/jpeg;base64,${poster}`:movieApi.posterUrl(movie.id,440,660,'contain')}/><label className="block text-xs">替换海报（保存后生效）<input className="mt-2 w-full" type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>file(e.target.files?.[0])}/></label>{poster&&<button className="btn" onClick={()=>setPoster(undefined)}>取消更换海报</button>}</aside></fieldset>
      <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t divider pt-3"><JobProgress job={task.job} accent="cinema"/><span className="text-xs text-ink-300">仅写入修改字段；保存前备份，并检查原文件是否已改变。</span><button className="btn" disabled={task.busy} onClick={close}>取消</button><button className="btn btn-primary" disabled={task.busy||!dirty} onClick={save}>保存修改</button></footer>
    </>}
    {discard&&<Modal title="放弃未保存修改？" onClose={()=>setDiscard(false)}><p>这些修改还未写入 NFO。</p><div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={()=>setDiscard(false)}>继续编辑</button><button className="btn btn-primary" onClick={onClose}>放弃修改</button></div></Modal>}
  </Modal>;
}
