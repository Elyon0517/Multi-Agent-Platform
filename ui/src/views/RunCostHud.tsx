import { useTranslation } from 'react-i18next';
import { useStore } from '@/store/store';

export function RunCostHud() {
  const { t } = useTranslation();
  const run = useStore((s) => s.runs.find((r) => r.id === s.activeRunId));
  if (!run) return null;
  return (
    <span title={t('lab.costTooltip', { cost: run.cost_cents.toFixed(2) })}
      style={{ fontFamily: 'var(--cth-font-mono)', fontSize: 10.5, color: 'var(--cth-ink-500)' }}>
      {run.cost_cents.toFixed(1)}c
    </span>
  );
}
