import { useTranslation } from 'react-i18next';
import type { GateResult } from '@/api/client';

// Defaults to [] so a backend older than the gate_reports field hides the table instead of crashing the page.
export function GateDiagnostics({ reports = [] }: { reports?: GateResult[] }) {
  const { t } = useTranslation();
  if (!reports.length) return null;
  return <section aria-label={t('lab.gateDiagnostics')} style={{ marginTop: 12 }}>
    <h3>{t('lab.gateDiagnostics')}</h3>
    {reports.map((report, round) => <div key={round}>
      <strong>{round + 1}. {report.language} · {report.mode} · {report.passed ? t('lab.gatePassed') : t('lab.gateFailed', { step: report.failed_at ?? '?' })}</strong>
      {report.steps.map((step, index) => <div key={index}>
        <p>{step.name} · {step.duration_ms}ms · exit {step.exit_code}</p>
        {step.diagnostics.length > 0 && <table style={{ width: '100%', textAlign: 'left', fontSize: 11 }}>
          <thead><tr><th scope="col">file:line</th><th scope="col">{t('lab.diagnosticCode')}</th><th scope="col">{t('lab.diagnosticMessage')}</th></tr></thead>
          <tbody>{step.diagnostics.map((diagnostic, row) => <tr key={row}>
            <td style={{ overflowWrap: 'anywhere' }}>{diagnostic.file}:{diagnostic.line ?? '—'}{diagnostic.col !== null ? `:${diagnostic.col}` : ''}</td>
            <td>{diagnostic.code || '—'}</td><td style={{ overflowWrap: 'anywhere' }}>{diagnostic.message}</td>
          </tr>)}</tbody>
        </table>}
        {!step.passed && step.log_tail && <details><summary>{t('lab.gateLog')}</summary>
          <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{step.log_tail}</pre></details>}
      </div>)}
    </div>)}
  </section>;
}
