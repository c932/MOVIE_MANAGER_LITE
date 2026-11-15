import {useEffect, useRef, useState} from 'react';
import {Modal} from '../Modal';
import {movieApi} from '../../api/client';
import {localPlayUrl} from '../../utils/movieDisplay';
import type {MovieListItem} from '../../types/api';

export function LocalPlayback({movie, menu = false, onRequested}: {movie:MovieListItem; menu?:boolean; onRequested?:()=>void}) {
  const [help, setHelp] = useState(false);
  const [message, setMessage] = useState('');
  const path = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  useEffect(()=>()=>clearTimeout(timer.current),[]);
  function requested() {
    // 外部协议先在当前用户点击中交由浏览器处理，再更新界面，保留用户手势。
    clearTimeout(timer.current);
    timer.current = setTimeout(()=>{setHelp(true);onRequested?.();},350);
  }
  async function copy() {
    try {
      if(navigator.clipboard) {await navigator.clipboard.writeText(movie.video_path);setMessage('视频路径已复制，可粘贴到播放器中打开。');}
      else {path.current?.focus();path.current?.select();setMessage('视频路径已选中，请按 Ctrl+C 复制。');}
    } catch {path.current?.focus();path.current?.select();setMessage('请按 Ctrl+C 复制已选中的视频路径。');}
  }
  return <>
    <a role={menu?'menuitem':undefined} className={menu?'flex w-full rounded px-3 py-2 text-sm hover:bg-ink-700':'btn btn-primary'}
      href={localPlayUrl(movie)} target="_blank" rel="noopener noreferrer" onClick={requested}>▶ 本地播放器播放</a>
    {help&&<Modal title={`本地播放 · ${movie.title}`} onClose={()=>setHelp(false)}>
      <p role="status" className="text-sm">已向浏览器请求打开本地播放器。若弹出“打开电影墙”，请选择允许打开。</p>
      <p className="mt-3 text-sm text-ink-300">如果没有任何反应，可下载下面的播放列表，再从浏览器下载栏打开；也可将视频路径粘贴到播放器中。</p>
      <div className="my-4 flex flex-wrap gap-2"><a className="btn btn-primary" href={movieApi.playlistUrl(movie.id)} download>下载播放列表并打开</a><button className="btn border divider" onClick={copy}>复制视频路径</button></div>
      <label className="block text-xs text-ink-300">视频路径<input ref={path} className="input mt-1 w-full" readOnly value={movie.video_path} onFocus={event=>event.currentTarget.select()}/></label>
      {message&&<p role="status" className="mt-3 text-sm text-green-300">{message}</p>}
      <p className="mt-3 text-xs text-ink-400">协议播放需要 Windows 电影墙 3.5.0 或更新版；播放列表可交给 mpv、VLC 或 MPC。播放电脑须能访问该 NAS 路径。</p>
    </Modal>}
  </>;
}
