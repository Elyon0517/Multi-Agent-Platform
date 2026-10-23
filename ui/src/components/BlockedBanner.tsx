import { useTranslation } from 'react-i18next';
import type { BlockReason } from '@/store/store';
import { PixelButton } from './PixelButton';
import { Icon } from './Icon';
export interface BlockedBannerProps { reason: BlockReason; onAction: (label: string, send?: string) => void; }
export function BlockedBanner({ reason, onAction }: BlockedBannerProps) {
  const { t } = useTranslation();
  return <section role="status" style={{ padding: 12, background: 'var(--cth-coral-light)', display: 'grid', gap: 8,
    boxShadow: 'inset 0 0 0 1.5px var(--cth-ink-500), inset 0 0 0 4px var(--cth-coral)' }}>
    <header style={{ display: 'flex', gap: 8, alignItems: 'center', font: '8px/12px var(--cth-font-display)' }}>
      <Icon name="bell" />{t('blockedBanner.needsYou')}</header>
    <div style={{ fontSize: 16, lineHeight: '20px' }}>{reason.summary}</div>
    <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--cth-ink-700)' }}>{reason.detail}</div>
    {reason.command && <code style={{ background: 'var(--cth-paper-100)', padding: '4px 8px',
      font: '13px/18px var(--cth-font-mono)', overflow: 'hidden', textOverflow: 'ellipsis' }}>$ {reason.command}</code>}
    <footer style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{reason.actions.map((action, index) =>
      <PixelButton key={index} size="sm" variant={action.kind === 'approve' ? 'primary' :
        action.kind === 'deny' ? 'destructive' : 'secondary'}
        onClick={() => onAction(action.label, action.send)}>{action.label}</PixelButton>)}</footer>
  </section>;
}
