import {useEffect,useState} from 'react';
import {Modal} from '../Modal';
import {scrapeApi} from '../../api/scrape';
import type {ScrapeSettings} from '../../api/scrape';

export function ScrapeSettingsDialog({onClose}: {onClose:()=>void}) {
  const [settings,setSettings]=useState<ScrapeSettings|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [show,setShow]=useState(false);
  useEffect(()=>{let active=true; scrapeApi.settings().then(value=>{if(active)setSettings(value);}).catch(e=>{if(active)setError((e as Error).message);});return()=>{active=false;};},[]);
  async function save() {
    if(!settings)return;
    setBusy(true);setError('');
    const {has_tmdb_api_key,has_tmdb_token,has_omdb_api_key,douban_available,...values}=settings;
    void has_tmdb_api_key;void has_tmdb_token;void has_omdb_api_key;void douban_available;
    try{await scrapeApi.saveSettings(values);onClose();}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <Modal title="刮削设置 · NUC" onClose={()=>!busy&&onClose()}>
    <p className="mb-4 text-xs text-ink-300">服务器刮削凭据与桌面端独立。密钥留空保留原值；IMDb 评分无需 OMDb Key。</p>
    {error&&<p role="alert" className="mb-3 text-red-400">{error}</p>}
    {!settings&&!error&&<p role="status">正在读取设置…</p>}
    {settings&&<form noValidate onSubmit={e=>{e.preventDefault();save();}}><fieldset disabled={busy} className="space-y-3">
      {([['tmdb_api_key','TMDB API Key'],['tmdb_token','TMDB Read Token'],['omdb_api_key','OMDb API Key']] as const).map(([key,label])=><label key={key} className="block text-sm">{label}<input className="input mt-1 w-full" type={show?'text':'password'} autoComplete="new-password" value={settings[key]||''} placeholder={settings[`has_${key}`]?'已配置；留空保留':'未配置'} onChange={e=>setSettings({...settings,[key]:e.target.value})}/></label>)}
      <button className="btn border divider" type="button" aria-pressed={show} onClick={()=>setShow(!show)}>{show?'隐藏凭据':'显示凭据'}</button>
      <label className="block text-sm">首选语言<input className="input mt-1 w-full" value={settings.language} onChange={e=>setSettings({...settings,language:e.target.value})}/></label>
      <label className="block text-sm">NUC HTTP(S) 代理<input className="input mt-1 w-full" placeholder="留空直连；使用 NUC 可访问的代理地址" value={settings.proxy} onChange={e=>setSettings({...settings,proxy:e.target.value})}/></label>
      <div className="grid grid-cols-2 gap-3"><label className="text-sm">请求超时（秒）<input className="input mt-1 w-full" type="number" min="5" max="120" value={settings.timeout} onChange={e=>setSettings({...settings,timeout:Number(e.target.value)})}/></label><label className="text-sm">豆瓣请求间隔（秒）<input className="input mt-1 w-full" type="number" min="0" step="0.1" value={settings.douban_delay} onChange={e=>setSettings({...settings,douban_delay:Number(e.target.value)})}/></label></div>
      {!settings.douban_available&&<p className="text-amber-300">NUC 尚未找到 Node / npx，豆瓣暂不可用。</p>}
      <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>取消</button><button className="btn btn-primary" type="submit">{busy?'正在保存…':'保存设置'}</button></div>
    </fieldset></form>}
  </Modal>;
}
