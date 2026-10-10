import { useTranslation } from 'react-i18next';
import { PixelPanel } from '@/components/PixelPanel';
import { useStore } from '@/store/store';
import { Muted } from '@/views/ui';
import type { TFunction } from 'i18next';
import type { LabEvent } from '@/api/client';

function describe(e: LabEvent, t: TFunction): string {
  const p = e.payload;
  switch (e.type) {
    case 'step.started': return t('lab.stepStarted', { actor: e.actor, iteration: p.iteration ?? '' });
    case 'step.finished': return t('lab.stepFinished', { actor: e.actor, model: p.model ?? '', cost: Number(p.cost_cents ?? 0).toFixed(2) });
    case 'artifact.created': return `${e.actor} → ${String(p.to ?? '—')}: ${String(p.kind)}`;
    case 'gate.finished': return p.passed ? t('lab.gatePassed') : t('lab.gateFailed', { step: p.failed_at ?? '?' });
    case 'arbiter.decision': return t('lab.arbiterDecision', { action: p.action });
    case 'approval.requested': return t('lab.humanNeeded', { reason: p.reason });
    case 'approval.decided': return t('lab.humanDecision', { decision: p.decision }) + (p.feedback ? `: ${String(p.feedback)}` : '');
    case 'run.status': return `${String(p.src)} → ${String(p.dst)}`;
    case 'budget.warning': return t('lab.budgetWarning', { cost: Number(p.cost_cents ?? 0).toFixed(1), budget: p.budget_cents });
    default: return e.type;
  }
}

export function ActivityView() {
  const { t } = useTranslation();
  const events = useStore((s) => s.events);
  return (
    <PixelPanel title={t('lab.activity')}>
      {events.length === 0 && <Muted>{t('lab.selectARunToSeeItsEventStream')}</Muted>}
      <ol reversed style={{ margin: 0, paddingLeft: 26, fontSize: 12, fontFamily: 'var(--cth-font-mono)' }}>
        {[...events].reverse().map((e) => (
          <li key={e.seq} style={{ padding: '1px 0' }}>
            <span style={{ color: 'var(--cth-ink-500)' }}>{new Date(e.ts).toLocaleTimeString()} </span>{describe(e, t)}
          </li>
        ))}
      </ol>
    </PixelPanel>
  );
}
