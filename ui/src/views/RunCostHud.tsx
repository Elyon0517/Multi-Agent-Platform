import { useTranslation } from 'react-i18next';
import { useStore } from '@/store/store';

export function RunCostHud() {
  const { t } = useTranslation();
  const run = useStore((s) => s.runs.find((r) => r.id === s.activeRunId));
  if (!run) return null;
  const pct = !run.budget_unlimited && run.budget_cents ? Math.round((run.cost_cents / run.budget_cents) * 100) : 0;
  return (
    <span title={t('lab.budgetTooltip', { cost: run.cost_cents.toFixed(2), budget: run.budget_unlimited ? '∞' : run.budget_cents })}
      style={{ fontFamily: 'var(--cth-font-mono)', fontSize: 10.5, color: pct >= 80 ? 'var(--cth-coral)' : 'var(--cth-ink-500)' }}>
      {run.cost_cents.toFixed(1)}c · {run.budget_unlimited ? '∞' : `${pct}%`}
    </span>
  );
}
