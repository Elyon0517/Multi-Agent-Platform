import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
export type StatusKind = 'idle' | 'thinking' | 'working' | 'waiting' | 'blocked' | 'success' | 'ghost' |
  'compacting' | 'looping' | 'typing';
export interface PixelBadgeProps { status: StatusKind; label?: string; style?: CSSProperties; }
export function PixelBadge({ status, label, style }: PixelBadgeProps) {
  const { t } = useTranslation();
  const paint = `var(--cth-status-${status})`;
  return <span data-status={status} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
    flexShrink: 0, padding: '2px 8px 0', color: 'var(--cth-ink-900)', background: 'var(--cth-cream-100)',
    boxShadow: `inset 0 0 0 1px ${paint}`, fontFamily: 'var(--cth-font-ui)',
    fontSize: 'var(--cth-text-body-sm)', lineHeight: '18px', userSelect: 'none', ...style }}>
    <span aria-hidden style={{ width: 8, height: 8, background: paint, border: '1px solid var(--cth-ink-300)' }} />
    {label ?? t(`badge.${status}`)}
  </span>;
}
