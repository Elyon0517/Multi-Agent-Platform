import { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';

export type StatusKind =
  | 'idle' | 'thinking' | 'working' | 'waiting' | 'blocked' | 'success' | 'ghost'
  | 'compacting' | 'looping'
  // Typing reflects an unsent user draft, derived at render time.
  | 'typing';

export interface PixelBadgeProps {
  status: StatusKind;
  label?: string;
  style?: CSSProperties;
}

const colorByStatus: Record<StatusKind, string> = {
  idle:     'var(--cth-status-idle)',
  thinking: 'var(--cth-status-thinking)',
  working:  'var(--cth-status-working)',
  waiting:  'var(--cth-status-waiting)',
  blocked:  'var(--cth-status-blocked)',
  success:  'var(--cth-status-success)',
  ghost:    'var(--cth-status-ghost)',
  compacting: 'var(--cth-status-compacting)',
  looping:    'var(--cth-status-looping)',
  typing:     'var(--cth-status-typing)'
};

// Blocked means waiting on the user; waiting means waiting on another agent.
const labelKeyByStatus: Record<StatusKind, string> = {
  idle:     'badge.idle',
  thinking: 'badge.thinking',
  working:  'badge.working',
  waiting:  'badge.waiting',
  blocked:  'badge.blocked',
  success:  'badge.success',
  ghost:    'badge.ghost',
  compacting: 'badge.compacting',
  looping:    'badge.looping',
  typing:     'badge.typing'
};

export function PixelBadge({ status, label, style }: PixelBadgeProps) {
  const { t } = useTranslation();
  const key = labelKeyByStatus[status];
  const text = label ?? (key ? t(key) : status);
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        // Keep the chip wide enough for its label.
        flexShrink: 0,
        gap: 6,
        padding: '2px 8px 0',
        background: 'var(--cth-cream-100)',
        boxShadow: `inset 0 0 0 1px ${colorByStatus[status]}`,
        fontFamily: 'var(--cth-font-ui)',
        fontSize: 'var(--cth-text-body-sm)',
        lineHeight: '18px',
        color: 'var(--cth-ink-900)',
        userSelect: 'none',
        ...style
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          background: colorByStatus[status],
          boxShadow: 'inset 0 0 0 1px var(--cth-ink-300)'
        }}
      />
      {text}
    </span>
  );
}
