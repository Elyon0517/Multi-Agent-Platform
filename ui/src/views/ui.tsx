import type { CSSProperties, ReactNode } from 'react';

export const inputStyle: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '6px 8px', border: 'none',
  background: 'var(--cth-cream-100)', boxShadow: 'inset 0 0 0 1px var(--cth-ink-300)',
  fontFamily: 'var(--cth-font-mono)', fontSize: 12, color: 'var(--cth-ink-900)',
};

export function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
      <label htmlFor={id} style={{ fontSize: 12, color: 'var(--cth-ink-700)' }}>{label}</label>
      {children}
      {hint && <span style={{ fontSize: 11, color: 'var(--cth-ink-500)' }}>{hint}</span>}
    </div>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <p style={{ margin: '4px 0', fontSize: 12, color: 'var(--cth-ink-500)' }}>{children}</p>;
}

export function Status({ error, ok }: { error?: string | null; ok?: string | null }) {
  if (error) return <p role="alert" style={{ margin: '6px 0', fontSize: 12, color: 'var(--cth-coral)' }}>{error}</p>;
  if (ok) return <p role="status" style={{ margin: '6px 0', fontSize: 12, color: 'var(--cth-mint)' }}>{ok}</p>;
  return null;
}

export const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e));
