import { useRef, useState } from 'react';
import { isComposingKey } from '@/shared/imeGuard';
export interface AgentNameEditorProps {
  name: string; onCommit: (name: string) => Promise<{ ok: boolean; error?: string }>;
  uppercase?: boolean; fontSize?: number | string;
}
export function AgentNameEditor({ name, onCommit, uppercase, fontSize = 'var(--cth-text-display-sm)' }: AgentNameEditorProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState('');
  const busy = useRef(false), cancelled = useRef(false);
  const begin = () => { cancelled.current = false; setError(''); setDraft(name); };
  const save = async () => {
    if (busy.current || cancelled.current || draft === null) return;
    const value = draft.trim();
    if (!value) { setError('Name is required'); return; }
    if (value === name) { setDraft(null); return; }
    busy.current = true;
    try {
      const result = await onCommit(value);
      if (result.ok) setDraft(null); else setError(result.error || 'Rename failed');
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { busy.current = false; }
  };
  const style = { fontFamily: 'var(--cth-font-display)', fontSize, minWidth: 0,
    color: 'var(--cth-ink-900)', textTransform: uppercase ? 'uppercase' as const : undefined };
  if (draft !== null) return <input autoFocus aria-label={`Rename ${name}`} aria-invalid={!!error} title={error}
    value={draft} onChange={e => setDraft(e.target.value)} onFocus={e => e.currentTarget.select()}
    onClick={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()} onBlur={() => void save()}
    onKeyDown={e => {
      e.stopPropagation(); if (isComposingKey(e)) return;
      if (e.key === 'Escape') { cancelled.current = true; setDraft(null); }
      if (e.key === 'Enter') { e.preventDefault(); void save(); }
    }} style={{ ...style, width: '100%', height: 20, padding: '1px 4px',
      background: 'var(--cth-paper-100)', border: `1px solid var(--cth-${error ? 'coral' : 'ink-300'})` }} />;
  return <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', flex: 1, minWidth: 0 }}>
    <span onDoubleClick={e => { e.stopPropagation(); begin(); }} title={`${name} — double-click to rename`}
      style={{ ...style, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
    <button type="button" aria-label={`Rename ${name}`} title={`Rename ${name}`}
      onClick={e => { e.stopPropagation(); begin(); }} onMouseDown={e => e.stopPropagation()}
      style={{ background: 'transparent', border: 0, padding: 0, width: 14, height: 14,
        color: 'var(--cth-ink-500)', fontSize: 9, cursor: 'text', flexShrink: 0 }}>✎</button>
  </span>;
}
