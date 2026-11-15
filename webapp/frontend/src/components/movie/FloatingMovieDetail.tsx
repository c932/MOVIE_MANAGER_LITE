import { useLayoutEffect, useRef, useState } from 'react';

export function FloatingMovieDetail({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [closing, setClosing] = useState(false);
  const [visible, setVisible] = useState(false);
  useLayoutEffect(() => {
    dialog.current?.showModal();
    closeButton.current?.focus({preventScroll: true});
    const element = dialog.current;
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setVisible(true)); });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); clearTimeout(timer.current); element?.close(); };
  }, []);
  const close = () => {
    if (closing) return;
    setClosing(true);
    timer.current = setTimeout(onClose, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 200);
  };
  return <dialog ref={dialog} aria-label={title} className="movie-overlay" data-phase={closing ? 'closing' : visible ? 'open' : 'opening'}
    onClick={event => { if (event.target === event.currentTarget) close(); }} onCancel={event => { event.preventDefault(); close(); }}>
    <section className="movie-floating-panel" aria-label="电影详情">
      <div className="flex items-center justify-between gap-3 border-b divider px-4 py-2"><h2 className="truncate text-sm text-ink-300">{title}</h2><button ref={closeButton} className="btn" aria-label="关闭电影详情" onClick={close}>关闭 ×</button></div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  </dialog>;
}
