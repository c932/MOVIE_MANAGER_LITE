import { useEffect, useRef } from 'react';

export function Modal({ title, onClose, children, wide = false, closeDisabled = false }: {
  title: string; onClose: () => void; children: React.ReactNode; wide?: boolean; closeDisabled?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return <dialog ref={ref} onCancel={event => {
    if (closeDisabled) event.preventDefault();
    else onClose();
  }} aria-label={title}
    className={`m-auto max-h-[92dvh] w-[94vw] rounded-xl border border-ink-700 bg-ink-850 p-0 text-ink-50 shadow-2xl backdrop:bg-black/70 ${wide ? 'max-w-6xl' : 'max-w-2xl'}`}>
    <header className="sticky top-0 z-10 flex items-center justify-between border-b divider bg-ink-850 p-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      <button className="btn" onClick={onClose} disabled={closeDisabled} aria-label="关闭窗口">关闭</button>
    </header>
    <div className="p-4">{children}</div>
  </dialog>;
}
