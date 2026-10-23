import type { CSSProperties, ReactNode } from 'react';
import type { AccentColorName } from '@/design/tokens';
export interface PixelPanelProps {
  variant?: 'default' | 'inset' | 'active' | 'terminal' | 'dialog'; title?: string;
  accent?: AccentColorName; children?: ReactNode; style?: CSSProperties; className?: string; noPadding?: boolean;
}
export function PixelPanel(props: PixelPanelProps) {
  const variant = props.variant ?? 'default';
  const surface = variant === 'inset' ? 'cream-200' : variant === 'dialog' ? 'cream-50' :
    variant === 'terminal' ? 'paper-100' : 'cream-100';
  const border = variant === 'default' || variant === 'active' ? '' : `-${variant}`;
  return <div className={props.className} style={{ position: 'relative',
    background: `var(--cth-${surface})`, padding: props.noPadding ? 0 : 12,
    boxShadow: variant === 'active' && props.accent
      ? `inset 0 0 0 1px var(--cth-ink-100), inset 0 0 0 3px var(--cth-${props.accent}), inset 0 0 0 5px var(--cth-ink-900)`
      : `var(--cth-panel-border${border})`, ...props.style }}>
    {props.title && <div style={{ margin: props.noPadding ? 0 : '-12px -12px 12px', padding: '6px 12px 4px',
      background: `var(--cth-${props.accent ? props.accent : 'cream-200'})`, color: 'var(--cth-ink-900)',
      fontFamily: 'var(--cth-font-display)', fontSize: 'var(--cth-text-display-md)',
      lineHeight: 'var(--cth-lh-display-md)', boxShadow: 'inset 0 -1px var(--cth-ink-900)' }}>{props.title}</div>}
    {props.children}
  </div>;
}
