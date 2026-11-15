import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { movieApi } from '../../api/client';
import type { NASConfig, NASConnection, NASDirectories, NASLibrary, NASStatus } from '../../types/api';

const initial: NASConfig = {host: '192.168.50.100', port: 445, username: '', password: '', domain: '', share: '', vers: '3.0', guest: false};

export function NASSettingsPanel({ onPathsChanged, onChanged }: { onPathsChanged: (paths: string[]) => void; onChanged: () => void }) {
  const [config, setConfig] = useState<NASConfig>(initial);
  const [status, setStatus] = useState<NASStatus | null>(null);
  const [shares, setShares] = useState<string[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState('');
  const [path, setPath] = useState('');
  const [folders, setFolders] = useState<(NASDirectories & {id: string}) | null>(null);
  const [folderError, setFolderError] = useState('');
  const [libraries, setLibraries] = useState<NASLibrary[]>([]);
  const dirty = useRef(false);
  const mounted = useRef(true);
  const reportChanged = useEffectEvent(() => onChanged());
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const reload = async () => {
    const value = await movieApi.nasStatus();
    if (!mounted.current) return;
    setStatus(value);
    if (!dirty.current) setLibraries(value.libraries);
  };
  useEffect(() => {
    let active = true;
    movieApi.nasStatus().then(value => { if (active) { setStatus(value); setLibraries(value.libraries); const first = value.connections.find(item => item.connected); if (first) setSelected(first.id); } })
      .catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const job = await movieApi.get(jobId);
        if (!active) return;
        setMessage(job.message || '正在连接 NAS…');
        if (job.status === 'error' || job.status === 'cancelled') {
          setError((job.error || '操作已取消').replace(/^(ValueError|RuntimeError):\s*/, '')); setMessage(''); setJobId(null); setBusy(false);
        } else if (job.status === 'done') {
          const result = job.result as {shares?: string[]; id?: string};
          if (result.shares) { setShares(result.shares); setMessage('登录成功，请选择共享目录并连接。'); }
          else { setConfig(value => ({...value, password: ''})); setMessage(result.id ? '共享已连接，请选择媒体库目录。' : '已断开连接'); }
          if (result.id) { setSelected(result.id); setPath(''); }
          await reload();
          if (active) { setJobId(null); setBusy(false); reportChanged(); }
        } else timer = setTimeout(poll, 700);
      } catch (e) { if (active) { setError((e as Error).message); setMessage(''); setBusy(false); setJobId(null); } }
    };
    poll();
    return () => { active = false; clearTimeout(timer); };
    // 轮询只跟随当前任务，组件关闭即停止读取结果；后端已开始的连接会完成。
  }, [jobId]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    movieApi.nasDirectories(selected, path).then(value => { if (active) { setFolders({...value, id: selected}); setFolderError(''); } })
      .catch(e => { if (active) setFolderError((e as Error).message); });
    return () => { active = false; };
  }, [selected, path, status]);
  const launch = async (action: 'shares' | 'connect' | 'disconnect', id = '') => {
    setError(''); setMessage('正在连接 NAS…'); setBusy(true);
    try {
      const result = action === 'shares' ? await movieApi.nasShares(config) : action === 'connect' ? await movieApi.nasConnect(config) : await movieApi.nasDisconnect(id);
      if (mounted.current) setJobId(result.job_id);
    } catch (e) { if (mounted.current) { setError((e as Error).message); setBusy(false); setMessage(''); } }
  };
  const chooseConnection = (item: NASConnection) => {
    setConfig({host: item.host, port: item.port, username: item.username, password: '', domain: item.domain, share: item.share, vers: item.vers, guest: item.guest});
    if (item.connected) { setSelected(item.id); setPath(''); }
  };
  const savedAccount = status?.connections.some(item => item.host === config.host && item.username === config.username && item.has_password);
  const addRoot = (connection: NASConnection) => {
    setLibraries([...libraries.filter(item => item.connection_id !== connection.id), {connection_id: connection.id, path: '', label: `//${connection.host}/${connection.share}`}]);
    dirty.current = true;
    setMessage('已将整个共享加入待扫描列表，请点击“保存媒体库目录”。');
  };
  const canAdd = folders?.id === selected && folders.path === path && !folderError && status?.connections.some(item => item.id === selected && item.connected);
  const add = () => {
    if (!canAdd) return;
    const connection = status!.connections.find(item => item.id === selected)!;
    if (!libraries.some(item => item.connection_id === selected && item.path === path)) {
      setLibraries([...libraries, {connection_id: selected, path, label: `//${connection.host}/${connection.share}${path ? '/' + path : ''}`}]);
      dirty.current = true;
    }
  };
  const save = async () => {
    setBusy(true); setError(''); setMessage('正在保存媒体库目录…');
    try {
      const result = await movieApi.nasLibraries(libraries.map(({connection_id, path}) => ({connection_id, path})));
      if (mounted.current) { dirty.current = false; onPathsChanged(result.movie_paths); onChanged(); setMessage('媒体库目录已保存。关闭设置后点击“扫描 NAS”开始扫描。'); await reload(); }
    } catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  };
  return <section className="mb-6 space-y-4 border-b divider pb-5" aria-labelledby="nas-heading">
    <div className="flex items-center justify-between gap-2"><h3 id="nas-heading" className="font-semibold">NAS 登录与媒体库</h3><button className="btn text-xs" disabled={busy} onClick={() => { setError(''); reload().catch(e => setError((e as Error).message)); }}>刷新连接状态</button></div>
    <p className="text-xs leading-relaxed text-ink-300">连接 NAS 的 SMB 共享，用于扫描 NFO 和读取海报。默认只读，不修改 NAS 文件。密码只保存在 NUC，不进入共享电影数据库。</p>
    {status && !status.available && <p role="alert" className="text-sm text-red-400">{status.detail || 'NAS 连接组件不可用'}</p>}
    <fieldset disabled={busy || status?.available === false} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className="text-xs text-ink-300">NAS IP / 主机名<input className="input mt-1 w-full" value={config.host} onChange={e => setConfig({...config, host: e.target.value})} autoComplete="off" /></label>
      <label className="text-xs text-ink-300">SMB 端口<input className="input mt-1 w-full" type="number" min="1" max="65535" value={config.port} onChange={e => setConfig({...config, port: Number(e.target.value)})} /></label>
      <label className="text-xs text-ink-300">用户名<input className="input mt-1 w-full" value={config.username} autoComplete="off" disabled={config.guest} onChange={e => setConfig({...config, username: e.target.value})} /></label>
      <label className="text-xs text-ink-300">密码<input className="input mt-1 w-full" type="password" value={config.password} disabled={config.guest} autoComplete="new-password" placeholder={savedAccount ? '留空使用已保存密码' : '请输入 NAS 密码'} onChange={e => setConfig({...config, password: e.target.value})} /></label>
      <label className="text-xs text-ink-300">域（可选）<input className="input mt-1 w-full" value={config.domain} onChange={e => setConfig({...config, domain: e.target.value})} /></label>
      <label className="text-xs text-ink-300">SMB 版本<select className="input mt-1 w-full" value={config.vers} onChange={e => setConfig({...config, vers: e.target.value})}><option value="3.0">SMB 3.0（推荐）</option><option value="3.1.1">SMB 3.1.1</option><option value="2.1">SMB 2.1</option><option value="2.0">SMB 2.0（旧设备）</option></select></label>
      <label className="flex items-center gap-2 text-xs text-ink-300 sm:col-span-2"><input type="checkbox" checked={config.guest} onChange={e => setConfig({...config, guest: e.target.checked})} />访客免密访问</label>
      <div className="flex flex-wrap gap-2 sm:col-span-2"><button className="btn border divider" onClick={() => launch('shares')} disabled={!config.host}>测试登录并列出共享</button></div>
      <label className="text-xs text-ink-300 sm:col-span-2">共享目录名（如 movie、Movie Series，可选择或手动输入）<input className="input mt-1 w-full" value={config.share} list="nas-share-options" onChange={e => setConfig({...config, share: e.target.value})} /><datalist id="nas-share-options">{shares.map(name => <option key={name} value={name} />)}</datalist></label>
      <button className="btn btn-primary w-fit sm:col-span-2" disabled={!config.host || !config.share} onClick={() => launch('connect')}>保存登录并连接共享</button>
    </fieldset>
    {busy && <p role="status" className="text-sm">{message || '正在处理 NAS 操作…'}</p>}
    {!busy && message && <p role="status" className="text-sm text-ink-200">{message}</p>}
    {error && <p role="alert" className="break-words text-sm text-red-400">{error}</p>}
    {status?.connections.map(item => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 border-b divider py-2 text-sm"><div><strong>{item.host} / {item.share}</strong><p className="text-xs text-ink-300">{item.connected ? '已连接 · 只读' : item.error || '未连接'} · {item.guest ? '访客' : item.username}</p></div><div className="flex flex-wrap gap-1">{item.connected && <button className="btn border divider" disabled={busy} onClick={() => addRoot(item)}>将整个共享加入媒体库</button>}<button className="btn" disabled={busy} onClick={() => chooseConnection(item)}>{item.connected ? '选择子目录' : '使用已保存登录'}</button>{item.mounted && <button className="btn" disabled={busy} onClick={() => launch('disconnect', item.id)}>断开</button>}</div></div>)}
    {selected && <div className="space-y-2"><p className="text-sm">媒体库子目录：{path || '共享根目录'}</p><div className="flex flex-wrap gap-2"><button className="btn" disabled={!path || busy} onClick={() => setPath(path.split('/').slice(0, -1).join('/'))}>上一级</button><button className="btn border divider" disabled={!canAdd || busy} onClick={add}>将当前目录加入媒体库</button></div>
      {folderError ? <p role="alert" className="text-sm text-red-400">{folderError}</p> : folders?.id !== selected || folders.path !== path ? <p role="status">正在读取目录…</p> : <div className="max-h-44 overflow-auto rounded border divider">{folders.directories.length ? folders.directories.map(item => <button className="block w-full px-3 py-2 text-left text-sm hover:bg-ink-700" disabled={busy} key={item.path} onClick={() => setPath(item.path)}>文件夹：{item.name}</button>) : <p className="p-3 text-xs text-ink-300">没有下级文件夹，可直接添加当前目录。</p>}</div>}
    </div>}
    <div className="space-y-2"><h4 className="text-sm font-semibold">待扫描的媒体库目录</h4>{libraries.length ? libraries.map((item, index) => <div className="flex items-center justify-between gap-2 text-xs" key={`${item.connection_id}-${item.path}`}><span className="break-all">{item.label || `${item.connection_id}/${item.path}`}</span><button className="btn" disabled={busy} onClick={() => { setLibraries(libraries.filter((_, i) => i !== index)); dirty.current = true; }}>移除</button></div>) : <p className="text-xs text-ink-300">请连接共享后，将共享根目录或所需子目录加入媒体库。</p>}<button className="btn border divider" disabled={busy || status?.available === false} onClick={save}>保存媒体库目录</button></div>
  </section>;
}
