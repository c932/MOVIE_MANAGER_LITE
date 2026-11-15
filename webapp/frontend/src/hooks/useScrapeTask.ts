import {useEffect, useRef, useState} from 'react';
import {movieApi} from '../api/client';
import type {Job} from '../types/api';

export function useScrapeTask() {
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [job,setJob] = useState<Job|null>(null);
  const mounted = useRef(true);
  const running = useRef(false);
  const current = useRef('');
  useEffect(() => { mounted.current=true; return () => {mounted.current=false;}; },[]);
  async function run<T>(start: () => Promise<{job_id:string}>): Promise<T|null> {
    if (running.current) return null;
    running.current=true; setBusy(true); setError(''); setJob(null);
    try {
      current.current=(await start()).job_id;
      while (mounted.current) {
        const value = await movieApi.get(current.current);
        if (!mounted.current) return null;
        setJob(value);
        if (value.status==='done') return value.result as T;
        if (value.status==='error') throw new Error(value.error?.replace(/^ScrapeError:\s*/, '') || '操作失败');
        if (value.status==='cancelled') throw new Error('已取消后续操作，已完成的保存会保留。');
        await new Promise(resolve => setTimeout(resolve,600));
      }
    } catch(e) { if(mounted.current) setError((e as Error).message); }
    finally { running.current=false; current.current=''; if(mounted.current) setBusy(false); }
    return null;
  }
  const cancel = () => { if(current.current) movieApi.cancel(current.current).catch(e=>setError((e as Error).message)); };
  return {busy,error,job,run,cancel,setError};
}
