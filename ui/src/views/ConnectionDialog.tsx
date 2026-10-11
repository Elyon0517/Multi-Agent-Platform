import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, onConnectionChange, type ConnectionFailure } from '@/api/client';
import { PixelButton } from '@/components/PixelButton';
import { Muted } from '@/views/ui';
import { Modal } from './Modal';

/** Backoff for the single health probe; after the last delay it stops and waits for a manual retry. */
export const RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 48000];

const START: Record<ConnectionFailure, string> = {
  'dev-server': 'npm --prefix ui run dev',
  backend: 'uv run agentlab serve',
};

/** Shown while the backend or dev server refuses connections; closes itself once a request succeeds. */
export function ConnectionDialog() {
  const { t } = useTranslation();
  const [failure, setFailure] = useState<ConnectionFailure | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => onConnectionChange((reachable, reason) => {
    setFailure(reachable ? null : reason);
    setAttempt(0);
    if (reachable) setDismissed(false);
  }), []);

  useEffect(() => {
    if (!failure || attempt >= RETRY_DELAYS_MS.length) return;
    const timer = setTimeout(() => {
      api.health().catch(() => setAttempt((n) => n + 1));
    }, RETRY_DELAYS_MS[attempt]);
    return () => clearTimeout(timer);
  }, [failure, attempt]);

  if (!failure || dismissed) return null;
  const gaveUp = attempt >= RETRY_DELAYS_MS.length;
  return (
    <Modal title={t('lab.connectionLostTitle')} onClose={() => setDismissed(true)}>
      <p style={{ margin: '4px 0 8px' }}>{t(failure === 'dev-server' ? 'lab.devServerDown' : 'lab.backendDown')}</p>
      <pre style={{ margin: '0 0 8px', padding: 8, background: 'var(--cth-paper-100)', whiteSpace: 'pre-wrap' }}>
        {START[failure]}
      </pre>
      <Muted>
        {gaveUp
          ? t('lab.connectionGaveUp')
          : t('lab.connectionRetrying', { attempt: attempt + 1, total: RETRY_DELAYS_MS.length, seconds: RETRY_DELAYS_MS[attempt] / 1000 })}
      </Muted>
      <div style={{ marginTop: 8 }}>
        <PixelButton size="sm" onClick={() => { api.health().catch(() => setAttempt(RETRY_DELAYS_MS.length)); }}>{t('lab.retryNow')}</PixelButton>
      </div>
    </Modal>
  );
}
