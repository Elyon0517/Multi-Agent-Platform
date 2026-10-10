import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { BlockedBanner } from '@/components/BlockedBanner';
import { Field, Status, errorText, inputStyle } from '@/views/ui';
import { api, type Approval } from '@/api/client';

export function ApprovalBar({ runId, approval }: { runId: string; approval: Approval }) {
  const { t } = useTranslation();
  const [feedback, setFeedback] = useState('');
  const [budget, setBudget] = useState('');
  const [maxIter, setMaxIter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const onAction = async (label: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const decision = label === t('lab.approve') ? 'approve' : label === t('lab.abort') ? 'abort' : 'reject';
    try {
      await api.decide(runId, decision, feedback || undefined, {
        budget_cents: budget ? Number(budget) : undefined,
        max_iter: maxIter ? Number(maxIter) : undefined,
      });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div aria-busy={busy}>
      <BlockedBanner
        reason={{
          summary: approval.reason,
          detail: JSON.stringify(approval.payload).slice(0, 400),
          actions: [
            { label: t('lab.approve'), kind: 'approve' },
            { label: t('lab.reject'), kind: 'deny' },
            { label: t('lab.abort'), kind: 'neutral' },
          ],
        }}
        onAction={onAction}
      />
      {approval.reason !== 'signoff' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Field id="resume-budget" label={t('lab.resumeBudget')}
            hint={approval.payload.required_budget_cents ? t('lab.requiredBudget', { value: approval.payload.required_budget_cents }) : undefined}>
            <input id="resume-budget" type="number" min="0.01" step="0.01" style={inputStyle}
              value={budget} onChange={(e) => setBudget(e.target.value)} />
          </Field>
          <Field id="resume-max-iter" label={t('lab.resumeMaxIter')}>
            <input id="resume-max-iter" type="number" min="1" max="50" step="1" style={inputStyle}
              value={maxIter} onChange={(e) => setMaxIter(e.target.value)} />
          </Field>
        </div>
      )}
      <Status error={error} />
      <label htmlFor="feedback" style={{ display: 'block', marginTop: 4 }}>{t('lab.feedbackForReject')}</label>
      <input id="feedback" value={feedback} onChange={(e) => setFeedback(e.target.value)} style={{ width: '100%' }} />
    </div>
  );
}
