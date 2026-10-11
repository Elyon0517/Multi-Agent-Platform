import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PixelPanel } from './PixelPanel';
import { PixelBadge, StatusKind } from './PixelBadge';
import { SpritePortrait } from './SpritePortrait';
import { RunCostHud } from '@/views/RunCostHud';
import { AccentColorName } from '@/design/tokens';
import { OfficeCharacterName } from '@/scene/office/cast';
import { AgentNameEditor } from './AgentNameEditor';

export interface AgentCardProps {
  name: string;
  character: OfficeCharacterName;
  accent: AccentColorName;
  status: StatusKind;
  /** This agent's pty, if it has one. Only used to notice that the USER has
   *  unsent text on its prompt — which holds the agent's queue, and otherwise
   *  looks identical to an idle agent with nothing to do. */
  ptyId?: string;
  project: string;
  action?: string;
  /** Context gauge: 0..8 segments filled (session context ÷ context limit). */
  progress?: number;
  /** Live context size (tokens) — shown in the gauge tooltip. */
  contextTokens?: number;
  /** Context-window limit (tokens) assumed for the agent's model. */
  contextLimit?: number;
  selected?: boolean;
  /** Your clone — gets a persistent accent frame + BOSS tag so it stands out.
   *  (`isGod` / the `god` agent id stay as-is internally; this is display only.) */
  isGod?: boolean;
  onClick?: () => void;
  /** Persists an inline display-name edit; identity and hive paths stay unchanged. */
  onRename?: (name: string) => Promise<{ ok: boolean; error?: string }>;
  /** Number of ledger tasks this agent is actively DOING — rendered as a blue
   *  sticky note stuck to the card. Clicking it opens the first task's detail. */
  doingCount?: number;
  onTaskNoteClick?: () => void;
  draggable?: boolean; // must sit on the <button> itself — Chromium won't start a drag on an ancestor from inside a form control
  /** Private note — rendered as the card's own row (v0.3.4) so it can never
   *  cover the context gauge. First line only; full text in the tooltip. */
  note?: string;
  /** Opens the note editor (the strip owns the editing overlay). When set, the
   *  card shows a small ✎ affordance on its note row. */
  onEditNote?: () => void;
}

const fmtK = (n: number): string => `${Math.round(n / 1000)}k`;

export function AgentCard({
  name, character, accent, status, ptyId, project, action, progress = 0,
  contextTokens, contextLimit, selected, isGod, onClick, onRename,
  doingCount = 0, onTaskNoteClick, draggable, note, onEditNote
}: AgentCardProps) {
  const { t } = useTranslation();
  const [hover, setHover] = useState(false);
  const typing = false;
  void ptyId;
  // Root identity uses the surface; selection uses a shared ring.

  // Ink keeps the selection ring legible across agent accents and themes.
  const selectionRing = selected ? '0 0 0 2px var(--cth-ink-900)' : '';

  // Context gauge as ONE clean fill (0..8 → 0..100%). Colour escalates as the
  // window fills: accent while comfortable, amber from 6/8, coral from 7/8.
  const pct = Math.min(8, Math.max(0, progress)) / 8 * 100;
  const gaugeColor = progress >= 7 ? 'var(--cth-coral)'
    : progress >= 6 ? 'var(--cth-lemon)'
      : `var(--cth-${accent})`;
  const gaugeTitle = contextTokens !== undefined && contextLimit
    ? t('agentCard.contextTitle', { used: fmtK(contextTokens), limit: fmtK(contextLimit), pct: Math.round((contextTokens / contextLimit) * 100) })
    : t('agentCard.contextGaugeTitle');

  // Use one card size for all agents, with room for name, status and controls.
  const width = 220;
  const height = 78;
  const lift = (isGod ? -2 : 0) - (hover ? 1 : 0) - (selected ? 1 : 0);
  /** Root uses a tinted surface and the same border geometry as other cards. */
  const godSurface: React.CSSProperties = isGod
    ? {
        background: `var(--cth-${accent}-light)`,
        boxShadow: `inset 0 0 0 1px var(--cth-${accent})`
      }
    : {};
  const dropShadow = isGod
    ? `2px 3px 0 0 rgba(26,19,32,${hover ? 0.2 : 0.14})`
    : (hover ? '1px 2px 0 0 rgba(26,19,32,0.12)' : 'none');
  // Ring first so it sits tight to the card, then the existing drop shadow.
  const outerShadow = [selectionRing, dropShadow === 'none' ? '' : dropShadow]
    .filter(Boolean).join(', ') || 'none';

  // One context line: what it's DOING while working, WHERE it lives while idle.
  const infoLine = (status !== 'idle' && action) ? action : project;
  const noteFirstLine = (note ?? '').split('\n').find((l) => l.trim()) ?? '';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick?.();
        }
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      draggable={draggable}
      // The ring is the visual answer to "which terminal is open"; this is the
      // same answer for a screen reader. Matches SidebarRow in fullscreen.
      aria-current={selected ? 'true' : undefined}
      className="cth-titlebar-nodrag"
      style={{
        width, minWidth: width, height,
        padding: 0, border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left',
        position: 'relative',
        transform: lift ? `translateY(${lift}px)` : 'none',
        boxShadow: outerShadow,
        transition: 'transform 90ms steps(2, end), box-shadow 90ms steps(2, end)'
      }}
    >
      {/* The taken note, stuck to the card like on the desk: this worker is
          actively DOING a ledger task. Click → the task's detail overlay. */}
      {doingCount > 0 && (
        <span
          title={doingCount === 1
            ? t('agentCard.doingTasks', { count: doingCount })
            : t('agentCard.doingTasksPlural', { count: doingCount })}
          onClick={(e) => { e.stopPropagation(); onTaskNoteClick?.(); }}
          style={{
            position: 'absolute', right: -4, bottom: -5, zIndex: 2,
            width: 20, height: 18,
            background: 'var(--cth-sky)',
            boxShadow: 'inset 0 0 0 1px var(--cth-ink-300), 1px 2px 0 rgba(26,19,32,0.18)',
            transform: 'rotate(4deg)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--cth-font-display)', fontSize: 8, color: 'var(--cth-ink-900)',
            cursor: 'pointer'
          }}
        >
          {doingCount > 1 ? doingCount : '✎'}
        </span>
      )}
      <PixelPanel
        variant="default"
        style={{ height: '100%', padding: '6px 8px', ...godSurface }}
        noPadding
      >
        <div style={{ display: 'flex', gap: 8, height: '100%' }}>
          {/* Portrait tile — vertically centred so the card reads calm and even. */}
          <div style={{
            width: 36, height: isGod ? 50 : 46, alignSelf: 'center',
            // God's CARD is now accent-light, so the tile cannot be — it would
            // vanish into its own background. Paper reads as an inset frame
            // against the tint, which is what the tile is meant to look like.
            background: isGod ? 'var(--cth-paper-100)' : `var(--cth-${accent}-light)`,
            boxShadow: `inset 0 0 0 1px var(--cth-ink-${isGod ? '300' : '100'})`,
            // Anchor the sprite's TOP: the 56px-tall portrait overflows this
            // tile, and bottom-anchoring cropped the head — crop feet, not face.
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center', overflow: 'hidden',
            flexShrink: 0
          }}>
            <SpritePortrait character={character} scale={2} />
          </div>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
            {/* Identity row: name (+ BOSS tag) + status. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between', minWidth: 0 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, minWidth: 0, flex: 1 }}>
                {onRename ? (
                  <AgentNameEditor name={name} onCommit={onRename} uppercase />
                ) : (
                  <span style={{
                    fontFamily: 'var(--cth-font-display)',
                    fontSize: 'var(--cth-text-display-sm)',
                    lineHeight: 'var(--cth-lh-display-sm)',
                    color: 'var(--cth-ink-900)',
                    flex: 1, minWidth: 0,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                  }}>{name.toUpperCase()}</span>
                )}
                {isGod && (
                  <span style={{
                    fontFamily: 'var(--cth-font-display)', fontSize: 7, lineHeight: '11px',
                    background: `var(--cth-${accent})`, color: 'var(--cth-ink-900)',
                    padding: '1px 4px 0', flexShrink: 0
                  }}>{t('agentCard.boss')}</span>                )}
              </span>
              {/* flexShrink:0 — the badge is a fixed 2-to-5 character chip; when
                  it was allowed to shrink, the browser resolved the overflow by
                  eating the NAME instead. Truncation should land on the longest,
                  most redundant thing, not on the identity. */}
              <PixelBadge status={typing ? 'typing' : status} style={{ flexShrink: 0 }} />
            </div>

            {/* Context line: action while working, repo while idle. */}
            <div
              title={`${project}${action && status !== 'idle' ? ` — ${action}` : ''}`}
              style={{
                fontSize: 11, lineHeight: '14px',
                color: 'var(--cth-ink-500)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
              }}
            >{infoLine}</div>

            {/* God: voice on its own compact row. Workers: the private note row.
                Both sit ABOVE the gauge, so it is never covered. */}
            {isGod ? (
              // Let the label shrink, then clip overflow within the card.
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  minWidth: 0, overflow: 'hidden'
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <RunCostHud />
              </div>
            ) : (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0, minHeight: 14 }}
              >
                {noteFirstLine ? (
                  <span
                    title={note}
                    style={{
                      flex: 1, minWidth: 0, fontSize: 10.5, lineHeight: '14px',
                      color: 'var(--cth-ink-500)', fontStyle: 'italic',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                    }}
                  >{noteFirstLine}</span>
                ) : <span style={{ flex: 1 }} />}
                {onEditNote && (
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); onEditNote(); }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); onEditNote(); }
                    }}
                    title={note ? t('agentCard.editNote') : t('agentCard.addNote')}
                    aria-label={t('agentCard.editNoteAria', { name })}
                    style={{
                      flexShrink: 0, width: 15, height: 14,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 10, lineHeight: 1, cursor: 'pointer',
                      // Quiet until the card is hovered — discoverable, not noisy.
                      color: hover ? 'var(--cth-ink-500)' : 'var(--cth-ink-300)'
                    }}
                  >✎</span>
                )}
              </div>
            )}

            {/* Context gauge — slim fill bar pinned to the card's bottom edge. */}
            <div style={{ marginTop: 'auto' }} title={gaugeTitle}>
              <div style={{
                height: 4, width: '100%',
                background: 'var(--cth-cream-200)',
                boxShadow: 'inset 0 0 0 1px var(--cth-ink-100)',
                overflow: 'hidden'
              }}>
                <div style={{ width: `${pct}%`, height: '100%', background: gaugeColor }} />
              </div>
            </div>
          </div>
        </div>
      </PixelPanel>
    </div>
  );
}
