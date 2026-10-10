import { useTranslation } from 'react-i18next';
import { PixelPanel } from '@/components/PixelPanel';
import type { RunDetail } from '@/api/client';

export function RunTimeline({ detail }: { detail: RunDetail }) {
  const { t } = useTranslation();
  const { run, steps } = detail;
  return (
    <PixelPanel title={t('lab.runTitle', { id: run.id, status: run.status })}>
      <p style={{ margin: '0 0 8px' }}>
        {run.goal} · {run.cost_cents.toFixed(2)} / {run.budget_cents.toFixed(0)}c · {t('lab.tokens')} {run.tokens_in + run.tokens_out}
        {run.paused_reason && <strong> · {t('lab.paused')}: {run.paused_reason}</strong>}
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--cth-font-mono)', fontSize: 11 }}>
        <thead>
          <tr><th scope="col">#</th><th scope="col">{t('lab.role')}</th><th scope="col">{t('lab.model')}</th>
            <th scope="col">{t('lab.cost')}</th><th scope="col">{t('lab.attempts')}</th></tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr key={s.id}>
              <td>{s.iteration_n}</td><td>{s.role}</td><td>{s.model}</td><td>{s.usage.cost_cents.toFixed(2)}</td>
              <td>{s.attempt_count}{s.retry_reasons.length > 0 && ` (${s.retry_reasons.join(',')})`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </PixelPanel>
  );
}
