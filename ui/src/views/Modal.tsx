import { useTranslation } from 'react-i18next';
import { useEffect, useRef, type ReactNode } from 'react';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';

/** Native modal dialog: Esc and the backdrop close it, focus stays inside while open. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog ref={ref} aria-label={title} onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
      style={{ padding: 0, border: 0, background: 'transparent', width: 'min(560px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 32px)' }}>
      <PixelPanel variant="dialog" title={title}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: -4 }}>
          <PixelButton size="sm" variant="secondary" onClick={onClose}>{t('lab.close')}</PixelButton>
        </div>
        {children}
      </PixelPanel>
    </dialog>
  );
}
