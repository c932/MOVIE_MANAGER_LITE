// 任务进度轮询 Hook — 后台任务进度条用
import { useCallback, useEffect, useRef, useState } from 'react';
import { movieApi, gameApi } from '../api/client';
import type { Job } from '../types/api';

type JobsApi = {
  get: (id: string) => Promise<Job>;
  cancel: (id: string) => Promise<Job>;
};

export function useJobPoll(
  api: JobsApi,
  jobId: string | null,
  intervalMs = 800,
  onDone?: (job: Job) => void,
) {
  const [job, setJob] = useState<Job | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    // 立即拉一次
    api.get(jobId).then(setJob).catch(() => {});
    timerRef.current = setInterval(async () => {
      try {
        const j = await api.get(jobId);
        setJob(j);
        if (j.status === 'done' || j.status === 'error' || j.status === 'cancelled') {
          stop();
          onDoneRef.current?.(j);
        }
      } catch {
        stop();
      }
    }, intervalMs);
    return stop;
  }, [jobId, intervalMs, api, stop]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    await api.cancel(jobId);
  }, [jobId, api]);

  return { job, cancel, stop };
}

export { movieApi, gameApi };
