import { useState } from 'react';
import { BlockedBanner } from '@/components/BlockedBanner';
import { api, type Approval } from '@/api/client';

export function ApprovalBar({ runId, approval }: { runId: string; approval: Approval }) {
  const [feedback, setFeedback] = useState('');
  const onAction = (label: string) => {
    const decision = label === 'Approve' ? 'approve' : label === 'Abort' ? 'abort' : 'reject';
    void api.decide(runId, decision, feedback || undefined);
  };
  return (
    <div>
      <BlockedBanner
        reason={{
          summary: approval.reason,
          detail: JSON.stringify(approval.payload).slice(0, 400),
          actions: [
            { label: 'Approve', kind: 'approve' },
            { label: 'Reject', kind: 'deny' },
            { label: 'Abort', kind: 'neutral' },
          ],
        }}
        onAction={onAction}
      />
      <label htmlFor="feedback" style={{ display: 'block', marginTop: 4 }}>Feedback for reject</label>
      <input id="feedback" value={feedback} onChange={(e) => setFeedback(e.target.value)} style={{ width: '100%' }} />
    </div>
  );
}
