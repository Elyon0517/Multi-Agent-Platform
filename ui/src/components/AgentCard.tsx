import type { AccentColorName } from '@/design/tokens';
import type { OfficeCharacterName } from '@/scene/office/cast';
import { RunCostHud } from '@/views/RunCostHud';
import { useTranslation } from 'react-i18next';
import { PixelPanel } from './PixelPanel';
import { PixelBadge, type StatusKind } from './PixelBadge';
import { SpritePortrait } from './SpritePortrait';
import { AgentNameEditor } from './AgentNameEditor';
export interface AgentCardProps {
  name: string; character: OfficeCharacterName; accent: AccentColorName; status: StatusKind; ptyId?: string;
  project: string; action?: string; progress?: number; contextTokens?: number; contextLimit?: number;
  selected?: boolean; isGod?: boolean; onClick?: () => void;
  onRename?: (name: string) => Promise<{ ok: boolean; error?: string }>;
  doingCount?: number; onTaskNoteClick?: () => void; draggable?: boolean; note?: string; onEditNote?: () => void;
}
export function AgentCard(p: AgentCardProps) {
  const { t } = useTranslation();
  const percentage = Math.max(0, Math.min(100, (p.progress ?? 0) * 12.5));
  const color = `var(--cth-${percentage >= 87.5 ? 'coral' : percentage >= 75 ? 'lemon' : p.accent})`;
  const context = p.contextLimit && p.contextTokens !== undefined
    ? t('agentCard.contextTitle', { used: `${Math.round(p.contextTokens / 1000)}k`,
      limit: `${Math.round(p.contextLimit / 1000)}k`, pct: Math.round(p.contextTokens / p.contextLimit * 100) })
    : t('agentCard.contextGaugeTitle');
  return <div className="lab-agent-card" role="button" tabIndex={0} draggable={p.draggable}
    aria-current={p.selected ? 'true' : undefined} onClick={p.onClick} onKeyDown={e => {
      if (e.target === e.currentTarget && [' ', 'Enter'].includes(e.key)) { e.preventDefault(); p.onClick?.(); }
    }} style={{ position: 'relative', width: 220, minWidth: 220, height: 78, cursor: 'pointer',
      transform: p.isGod ? 'translateY(-2px)' : undefined,
      boxShadow: p.selected ? '0 0 0 2px var(--cth-ink-900)' : undefined }}>
    <PixelPanel noPadding style={{ height: '100%', padding: '6px 8px',
      background: p.isGod ? `var(--cth-${p.accent}-light)` : undefined }}>
      <div style={{ display: 'flex', height: '100%', gap: 8 }}>
        <div style={{ width: 36, height: p.isGod ? 50 : 46, alignSelf: 'center', overflow: 'hidden', flexShrink: 0,
          background: p.isGod ? 'var(--cth-paper-100)' : `var(--cth-${p.accent}-light)` }}>
          <SpritePortrait character={p.character} /></div>
        <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <header style={{ display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
            {p.onRename ? <AgentNameEditor name={p.name} uppercase onCommit={p.onRename} /> :
              <span style={{ minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                font: '8px/12px var(--cth-font-display)' }}>{p.name.toUpperCase()}</span>}
            {p.isGod && <span style={{ font: '7px/11px var(--cth-font-display)',
              background: `var(--cth-${p.accent})`, padding: '1px 4px' }}>{t('agentCard.boss')}</span>}
            <PixelBadge status={p.status} />
          </header>
          <div className="lab-ellipsis" title={`${p.project} ${p.action ?? ''}`}
            style={{ fontSize: 11, lineHeight: '14px', color: 'var(--cth-ink-500)' }}>
            {p.status !== 'idle' && p.action ? p.action : p.project}</div>
          <div onClick={e => e.stopPropagation()} style={{ display: 'flex', minHeight: 14, minWidth: 0, overflow: 'hidden' }}>
            {p.isGod ? <RunCostHud /> : <><span className="lab-ellipsis" title={p.note}
              style={{ flex: 1, fontSize: 10.5, fontStyle: 'italic', color: 'var(--cth-ink-500)' }}>
              {p.note?.split('\n').find(line => line.trim())}</span>
              {p.onEditNote && <button type="button" onClick={p.onEditNote}
                aria-label={t('agentCard.editNoteAria', { name: p.name })} title={t('agentCard.editNote')}
                style={{ border: 0, background: 'transparent', padding: 0, width: 15, height: 14, cursor: 'pointer' }}>✎</button>}</>}
          </div>
          <div role="meter" aria-label={context} aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100}
            title={context} style={{ marginTop: 'auto', height: 4, background: 'var(--cth-cream-200)' }}>
            <div style={{ width: `${percentage}%`, height: '100%', background: color }} /></div>
        </div>
      </div>
    </PixelPanel>
    {!!p.doingCount && <button type="button" title={t('agentCard.doingTasks', { count: p.doingCount })}
      onClick={e => { e.stopPropagation(); p.onTaskNoteClick?.(); }}
      style={{ position: 'absolute', right: -4, bottom: -5, width: 20, height: 18, border: 0,
        background: 'var(--cth-sky)', transform: 'rotate(4deg)', cursor: 'pointer' }}>{p.doingCount > 1 ? p.doingCount : '✎'}</button>}
  </div>;
}
