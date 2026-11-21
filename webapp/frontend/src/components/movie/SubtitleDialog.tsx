import {useState} from 'react';
import {Download, ExternalLink, Search, Upload} from 'lucide-react';
import {movieApi} from '../../api/client';
import {useScrapeTask} from '../../hooks/useScrapeTask';
import type {MovieListItem, SubtitleCandidate, SubtitleDraft, SubtitleSearch, SubtitleUpdate} from '../../types/api';
import {subtitleLanguages, subtitleSummary} from '../../utils/subtitles';
import {ActionIcon} from '../ActionIcon';
import {Modal} from '../Modal';

export function SubtitleDialog({movie, onClose, onUpdated}: {
  movie: MovieListItem;
  onClose: () => void;
  onUpdated?: (movie: MovieListItem) => void;
}) {
  const [query, setQuery] = useState(movie.title);
  const [tracks, setTracks] = useState(movie.subtitles);
  const [results, setResults] = useState<SubtitleSearch>();
  const [draft, setDraft] = useState<SubtitleDraft>();
  const [selected, setSelected] = useState(0);
  const [language, setLanguage] = useState('und');
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');
  const [verification, setVerification] = useState('');
  const job = useScrapeTask();
  const busy = Boolean(working) || job.busy;

  const run = async (label: string, action: () => Promise<void>) => {
    setError(''); setFeedback(''); setWorking(label);
    try { await action(); } catch (failure) { setError((failure as Error).message); }
    finally { setWorking(''); }
  };
  const openDraft = (value: SubtitleDraft) => {
    setDraft(value); setSelected(0); setLanguage(value.tracks[0]?.language || 'und');
    setVerification('');
  };
  const download = (item: SubtitleCandidate) => run('正在下载并检查字幕…', async () => {
    setVerification('');
    const value = await movieApi.subtitleDownload(movie.id, item);
    if ('verification_url' in value) {
      setVerification(value.verification_url); setFeedback(value.message);
    } else {
      openDraft(value);
    }
  });
  const update = (action: 'detect' | 'sync' | 'save') => run(
    action === 'detect' ? '正在读取本地字幕…' : '正在同步字幕记录…', async () => {
      const value = await job.run<SubtitleUpdate>(() => action === 'save' && draft
        ? movieApi.subtitleSave(movie.id, draft.token, selected, language)
        : movieApi.subtitleInspect(movie.id, action === 'detect' ? 'detect' : 'sync'));
      if (!value) return;
      setTracks(value.movie.subtitles); onUpdated?.(value.movie);
      if (action === 'save') setDraft(undefined);
      setFeedback(value.saved_name ? `已保存 ${value.saved_name}` : action === 'sync' ? '字幕记录已同步到 NFO 和电影库' : '已更新本地字幕状态');
    },
  );

  return <Modal title={`${movie.title} · 字幕`} onClose={onClose} closeDisabled={busy}>
    <div className="space-y-4 text-sm">
      <section aria-label="本地字幕" className="rounded-lg border divider bg-ink-800 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium">{subtitleSummary(tracks)}</span>
          <div className="flex flex-wrap gap-1">
            <button className="btn" disabled={busy} onClick={() => void update('detect')}>检测本地字幕</button>
            <button className="btn" disabled={busy} onClick={() => void update('sync')}>同步字幕到 NFO</button>
          </div>
        </div>
        {!!tracks?.length && <ul className="mt-2 space-y-1 text-xs text-ink-300">
          {tracks.map((track, index) => <li key={`${track.file}:${index}`} className="break-all">
            {track.file || '内嵌字幕'} · {subtitleLanguages[track.language] || subtitleLanguages.und}
          </li>)}
        </ul>}
      </section>
      <form noValidate className="flex flex-wrap items-end gap-2" onSubmit={e => {
        e.preventDefault();
        if (busy || !query.trim()) return;
        void run('正在搜索三个字幕站…', async () => {
          setResults(await movieApi.subtitleSearch(movie.id, query.trim())); setVerification('');
        });
      }}>
        <label className="min-w-40 flex-1">字幕搜索
          <input className="input mt-1 w-full" value={query} onChange={e => setQuery(e.target.value)} maxLength={300} disabled={busy} />
        </label>
        <button className="btn btn-active" disabled={busy || !query.trim()}><ActionIcon icon={Search} /> 搜索</button>
      </form>
      <div className="space-y-1" aria-live="polite">
        {working && <p role="status">{working}</p>}
        {(error || job.error) && <p role="alert" className="text-red-400">{error || job.error}</p>}
        {feedback && <p role="status" className="break-all text-ink-200">{feedback}</p>}
        {verification && <a className="btn" href={verification} target="_blank" rel="noreferrer">
          <ActionIcon icon={ExternalLink} /> 打开原站验证
        </a>}
      </div>
      {results && <section aria-label="字幕候选" className="space-y-2">
        <ul className="flex flex-wrap gap-2">
          {results.sources.map(source => <li key={source.source} className="text-xs text-ink-300">
            <a href={source.url} className="underline" target="_blank" rel="noreferrer">{source.name}</a>
            {source.message && <span> · {source.message}</span>}
          </li>)}
        </ul>
        {results.items.length === 0 ? <p>没有匹配的字幕，可修改关键字或打开原站。</p> :
          <ul className="max-h-64 divide-y divide-ink-700 overflow-y-auto rounded-lg border divider">
            {results.items.map(item => <li key={`${item.source}/${item.id}`} className="flex flex-wrap items-center gap-2 p-3">
              <div className="min-w-0 flex-1">
                <a className="break-all font-medium hover:underline" href={item.page} target="_blank" rel="noreferrer">{item.release}</a>
                <p className="mt-0.5 text-xs text-ink-300">
                  {results.sources.find(source => source.source === item.source)?.name} · {subtitleLanguages[item.language] || subtitleLanguages.und} · {item.score === 100 ? '文件名匹配' : `匹配度 ${item.score}%`}
                </p>
              </div>
              <button className="btn shrink-0" disabled={busy} onClick={() => void download(item)}><ActionIcon icon={Download} /> 下载</button>
            </li>)}
          </ul>}
      </section>}
      <label className="block text-xs text-ink-300">
        <span className="mb-1 flex items-center gap-1"><ActionIcon icon={Upload} /> 导入字幕或压缩包（ZIP、RAR、7z）</span>
        <input type="file" className="input w-full" disabled={busy} accept=".srt,.ass,.ssa,.vtt,.sub,.smi,.sup,.zip,.rar,.7z"
          onChange={event => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (!file) return;
            if (file.size > 48 * 1024 * 1024) { setError('字幕文件超过 48 MB'); return; }
            void run('正在读取导入文件…', async () => openDraft(await movieApi.subtitleImport(movie.id, file)));
          }} />
      </label>
      {draft && <section aria-label="保存字幕" className="space-y-2 rounded-lg border divider bg-ink-800 p-3">
        <label className="block">字幕文件
          <select className="input mt-1 w-full" value={selected} disabled={busy} onChange={e => {
            const index = Number(e.target.value);
            setSelected(index); setLanguage(draft.tracks[index].language);
          }}>
            {draft.tracks.map((track, index) => <option key={index} value={index}>{track.name}</option>)}
          </select>
        </label>
        <div className="flex flex-wrap items-end gap-2">
          <label>语言
            <select className="input ml-2" value={language} onChange={e => setLanguage(e.target.value)} disabled={busy}>
              {Object.entries(subtitleLanguages).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </label>
          <button className="btn btn-active ml-auto" disabled={busy} onClick={() => void update('save')}>保存到电影目录</button>
        </div>
      </section>}
    </div>
  </Modal>;
}
