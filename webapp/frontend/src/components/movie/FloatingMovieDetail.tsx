import { useEffect, useRef, useState } from 'react';

export function FloatingMovieDetail({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    const element = dialog.current;
    return () => { clearTimeout(timer.current); element?.close(); };
  }, []);
  const close = () => {
    if (closing) return;
    setClosing(true);
    timer.current = setTimeout(onClose, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180);
  };
  return <dialog ref={dialog} aria-label={title} className="movie-overlay" data-closing={closing}
    onClick={event => { if (event.target === event.currentTarget) close(); }} onCancel={event => { event.preventDefault(); close(); }}>
    <section className="movie-floating-panel" aria-label="电影详情">
      <div className="flex items-center justify-between gap-3 border-b divider px-4 py-2"><h2 className="truncate text-sm text-ink-300">{title}</h2><button autoFocus className="btn" aria-label="关闭电影详情" onClick={close}>关闭 ×</button></div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  </dialog>;
}
