// 任务进度条 — 后台扫描/刮削/导入/补全/LLM 判定等
import type { Job } from '../types/api';

interface Props {
  job: Job | null;
  onCancel?: () => void;
  accent?: 'cinema' | 'arcade';
}

export function JobProgress({ job, onCancel, accent = 'cinema' }: Props) {
  if (!job) return null;

  const pct =
    job.total > 0 ? Math.min(100, Math.round((job.current / job.total) * 100)) : 0;
  const barColor = accent === 'arcade' ? 'bg-arcade-500' : 'bg-cinema-500';
  const statusColor =
    job.status === 'error'
      ? 'text-red-400'
      : job.status === 'cancelled'
        ? 'text-ink-300'
        : job.status === 'done'
          ? 'text-green-400'
          : 'text-ink-200';

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className={`font-medium ${statusColor}`}>
        {job.status === 'running' && job.stage ? job.stage : job.kind}
      </span>
      {job.total > 0 && (
        <span className="font-mono text-ink-300">
          {job.current}/{job.total}
        </span>
      )}
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-ink-700">
        <div
          className={`h-full ${barColor} transition-all duration-300`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {job.message && (
        <span className="max-w-64 truncate text-ink-400" title={job.message}>
          {job.message}
        </span>
      )}
      {job.status === 'running' && onCancel && (
        <button
          className="rounded px-1.5 py-0.5 text-ink-300 hover:bg-ink-700 hover:text-red-400"
          onClick={onCancel}
          title="取消"
        >
          ✕
        </button>
      )}
    </div>
  );
}
