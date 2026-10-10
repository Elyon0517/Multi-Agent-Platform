import { PixelPanel } from '@/components/PixelPanel';
import { useStore } from '@/store/store';
import { Muted } from '@/views/ui';
import type { LabEvent } from '@/api/client';

function describe(e: LabEvent): string {
  const p = e.payload;
  switch (e.type) {
    case 'step.started': return `${e.actor} started (iter ${String(p.iteration ?? '')})`;
    case 'step.finished': return `${e.actor} finished · ${String(p.model ?? '')} · ${Number(p.cost_cents ?? 0).toFixed(2)}c`;
    case 'artifact.created': return `${e.actor} → ${String(p.to ?? '—')}: ${String(p.kind)}`;
    case 'gate.finished': return `gate ${p.passed ? 'passed' : `failed at ${String(p.failed_at ?? '?')}`}`;
    case 'arbiter.decision': return `arbiter: ${String(p.action)}`;
    case 'approval.requested': return `needs human: ${String(p.reason)}`;
    case 'approval.decided': return `human ${String(p.decision)}${p.feedback ? `: ${String(p.feedback)}` : ''}`;
    case 'run.status': return `${String(p.src)} → ${String(p.dst)}`;
    case 'budget.warning': return `budget warning: ${Number(p.cost_cents ?? 0).toFixed(1)}c / ${String(p.budget_cents)}c`;
    default: return e.type;
  }
}

export function ActivityView() {
  const events = useStore((s) => s.events);
  return (
    <PixelPanel title="Activity">
      {events.length === 0 && <Muted>Select a run to see its event stream.</Muted>}
      <ol reversed style={{ margin: 0, paddingLeft: 26, fontSize: 12, fontFamily: 'var(--cth-font-mono)' }}>
        {[...events].reverse().map((e) => (
          <li key={e.seq} style={{ padding: '1px 0' }}>
            <span style={{ color: 'var(--cth-ink-500)' }}>{new Date(e.ts).toLocaleTimeString()} </span>{describe(e)}
          </li>
        ))}
      </ol>
    </PixelPanel>
  );
}
