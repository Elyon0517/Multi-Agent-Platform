import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { SignoffReportView } from './SignoffReportView';
import { BlockedBanner } from '@/components/BlockedBanner';
import { Field, Status, errorText, inputStyle } from '@/views/ui';
import { api, type Approval, type RunDetail } from '@/api/client';

// Pause reasons with a plain-language explanation in i18n (approvalReason.*); anything else uses `unknown`.
const EXPLAINED = new Set(['signoff', 'no_changes', 'oscillation_detected', 'reviewer_conflict', 'inconsistent_verdict', 'budget_exceeded',
  'max_iter_exceeded', 'interrupted_call', 'workspace_escape', 'workspace_changed', 'edit_conflict',
  'dispatch_invalid', 'execution_error']);
// Reasons where the reviewers' open findings explain what is stuck.
const SHOW_FINDINGS = new Set(['oscillation_detected', 'reviewer_conflict', 'inconsistent_verdict', 'max_iter_exceeded']);

export function ApprovalBar({ runId, approval, detail, onDecided }: {
  runId: string; approval: Approval; detail?: RunDetail; onDecided?: () => void;
}) {
  const { t } = useTranslation();
  const [feedback, setFeedback] = useState('');
  // At the iteration limit, Approve needs a higher limit; start with another round of the same size.
  const currentMaxIter = detail?.run?.max_iter;
  const [maxIter, setMaxIter] = useState(
    approval.reason === 'max_iter_exceeded' && currentMaxIter ? String(Math.min(50, currentMaxIter * 2)) : '');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const onAction = async (label: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const decision = label === t('lab.approve') ? 'approve' : label === t('lab.abort') ? 'abort' : 'reject';
    try {
      await api.decide(runId, decision, feedback || undefined, {
        max_iter: maxIter ? Number(maxIter) : undefined,
      });
      onDecided?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const key = EXPLAINED.has(approval.reason) ? approval.reason : 'unknown';
  const errorKind = typeof approval.payload.error_kind === 'string' ? approval.payload.error_kind : null;
  const blockedReason = typeof approval.payload.blocked_reason === 'string' ? approval.payload.blocked_reason : '';
  const conflictPaths = approval.reason === 'edit_conflict' && Array.isArray(approval.payload.paths)
    ? approval.payload.paths.filter((path): path is string => typeof path === 'string') : [];
  const lastRound = detail?.iterations.at(-1);
  const findings = SHOW_FINDINGS.has(approval.reason)
    ? (lastRound?.verdicts ?? []).flatMap((v) => v.findings.filter((f) => f.severity === 'blocking' || f.severity === 'major')
      .map((f) => ({ ...f, reviewer: v.reviewer_id.split('@')[0] }))).slice(0, 8)
    : [];
  return (
    <div aria-busy={busy} style={{ maxHeight: '45vh', overflowY: 'auto' }}>
      {approval.reason === 'signoff' && approval.report && <SignoffReportView report={approval.report} />}
      {approval.reason === 'signoff' && !approval.report && approval.payload.automated_checks === 'not_run' &&
        <p role="status"><strong>{t('lab.untestedSignoff')}</strong></p>}
      <BlockedBanner
        reason={{
          summary: t(`approvalReason.${key}.title`),
          detail: t(`approvalReason.${key}.body`) + (errorKind ? ` (${t('lab.errorKind')}: ${errorKind})` : '')
            + (blockedReason ? ` ${t('lab.coderSaid')}: ${blockedReason}` : '')
            + (key === 'unknown' ? ` [${approval.reason}]` : ''),
          actions: [
            ...(approval.reason === 'dispatch_invalid' ? [] : [{ label: t('lab.approve'), kind: 'approve' as const }]),
            { label: t('lab.reject'), kind: 'deny' },
            { label: t('lab.abort'), kind: 'neutral' },
          ],
        }}
        onAction={onAction}
      />
      <Status error={error} />
      {conflictPaths.length > 0 && <ul>{conflictPaths.map((path) => <li key={path}><code>{path}</code></li>)}</ul>}
      {approval.reason !== 'signoff' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Field id="resume-max-iter" label={t('lab.resumeMaxIter')}>
            <input id="resume-max-iter" type="number" min="1" max="50" step="1" style={inputStyle}
              value={maxIter} onChange={(e) => setMaxIter(e.target.value)} />
          </Field>
        </div>
      )}
      {findings.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <strong>{t('lab.openFindings')}</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {findings.map((f, i) => (
              <li key={i}><code>{f.severity}</code> {f.file}{f.line ? `:${f.line}` : ''} — {f.issue} <span style={{ color: 'var(--cth-ink-500)' }}>({f.reviewer})</span></li>
            ))}
          </ul>
        </div>
      )}
      {approval.reason === 'interrupted_call' && <p>{t('lab.interruptedCall')}</p>}
      <label htmlFor="feedback" style={{ display: 'block', marginTop: 4 }}>{t('lab.feedbackForReject')}</label>
      <input id="feedback" value={feedback} onChange={(e) => setFeedback(e.target.value)} style={{ width: '100%' }} />
    </div>
  );
}
