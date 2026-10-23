import type { CSSProperties, ReactNode } from 'react';
export interface PixelButtonProps {
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive'; size?: 'sm' | 'md' | 'lg';
  children?: ReactNode; onClick?: () => void; disabled?: boolean; fullWidth?: boolean; style?: CSSProperties; title?: string;
}
export function PixelButton({ variant = 'primary', size = 'md', ...props }: PixelButtonProps) {
  const index = ['sm', 'md', 'lg'].indexOf(size);
  const fill = props.disabled ? 'cream-300' : variant === 'primary' ? 'ink-900' :
    variant === 'destructive' ? 'coral' : 'cream-100';
  const foreground = props.disabled ? 'ink-500' : variant === 'primary' ? 'cream-50' : 'ink-900';
  return <button type="button" className={`lab-button lab-button-${variant}`} title={props.title}
    disabled={props.disabled} onClick={props.onClick} style={{ display: 'inline-flex', alignItems: 'center',
      justifyContent: 'center', gap: 4, flexShrink: 0, whiteSpace: 'nowrap', userSelect: 'none',
      height: 24 + index * 8, padding: `0 ${8 + index * 4}px`, lineHeight: 1,
      background: variant === 'ghost' && !props.disabled ? 'transparent' : `var(--cth-${fill})`,
      color: `var(--cth-${foreground})`, border: 0,
      boxShadow: 'inset 0 0 0 1px var(--cth-ink-300), 0 1px 0 var(--cth-ink-100)',
      fontFamily: 'var(--cth-font-ui)', fontSize: `var(--cth-text-body-${size === 'lg' ? 'md' : 'sm'})`,
      cursor: props.disabled ? 'not-allowed' : 'pointer', width: props.fullWidth ? '100%' : undefined,
      ...props.style }}>{props.children}</button>;
}
