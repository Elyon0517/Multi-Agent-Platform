import { useTranslation } from 'react-i18next';
import type { ToolApproval, ToolDecision } from '@/api/client';

export function ToolApprovalActions({ status, busy, onDecision }: {
  status: ToolApproval['status'] | undefined;
  busy: boolean;
  onDecision: (decision: ToolDecision) => void;
}) {
  const { t } = useTranslation();
  if (!status) return <span>{t('lab.toolStatusLoading')}</span>;
  if (status === 'pending') return (
    <div className="chat-actions">
      <button type="button" className="primary" disabled={busy} onClick={() => onDecision('allow')}>{t('lab.allowTool')}</button>
      <button type="button" disabled={busy} onClick={() => onDecision('deny')}>{t('lab.denyTool')}</button>
    </div>
  );
  if (status === 'unknown_outcome') return (
    <div>
      <p role="status">{t('lab.toolOutcomeUnknown')}</p>
      <div className="chat-actions">
        <button type="button" disabled={busy} onClick={() => onDecision('confirm_done')}>{t('lab.toolConfirmDone')}</button>
        <button type="button" disabled={busy} onClick={() => onDecision('close_unknown')}>{t('lab.toolCloseUnknown')}</button>
      </div>
    </div>
  );
  return <span role="status">{t(`lab.toolStatus.${status}`)}</span>;
}
