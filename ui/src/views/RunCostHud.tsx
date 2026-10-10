import { useStore } from '@/store/store';

export function RunCostHud() {
  const run = useStore((s) => s.runs.find((r) => r.id === s.activeRunId));
  if (!run) return null;
  const pct = run.budget_cents ? Math.round((run.cost_cents / run.budget_cents) * 100) : 0;
  return (
    <span title={`${run.cost_cents.toFixed(2)}c of ${run.budget_cents}c budget`}
      style={{ fontFamily: 'var(--cth-font-mono)', fontSize: 10.5, color: pct >= 80 ? 'var(--cth-coral)' : 'var(--cth-ink-500)' }}>
      {run.cost_cents.toFixed(1)}c · {pct}%
    </span>
  );
}
