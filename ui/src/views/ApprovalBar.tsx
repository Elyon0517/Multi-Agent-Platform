import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { BlockedBanner } from '@/components/BlockedBanner';
import { api, type Approval } from '@/api/client';

export function ApprovalBar({ runId, approval }: { runId: string; approval: Approval }) {
  const { t } = useTranslation();
  const [feedback, setFeedback] = useState('');
  const onAction = (label: string) => {
    const decision = label === t('lab.approve') ? 'approve' : label === t('lab.abort') ? 'abort' : 'reject';
    void api.decide(runId, decision, feedback || undefined);
  };
  return (
    <div>
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
      <label htmlFor="feedback" style={{ display: 'block', marginTop: 4 }}>{t('lab.feedbackForReject')}</label>
      <input id="feedback" value={feedback} onChange={(e) => setFeedback(e.target.value)} style={{ width: '100%' }} />
    </div>
  );
}
