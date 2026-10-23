import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useStore } from '@/store/store';
import { byActivity } from './agentOrder';
import { AgentCard } from './AgentCard';
export interface AgentStripProps { config?: null; }
export function AgentStrip(_props: AgentStripProps) {
  const state = useStore();
  const { t } = useTranslation();
  const [drag, setDrag] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ id: string; left: number; bottom: number } | null>(null);
  return <div style={{ display: 'flex', alignItems: 'center', gap: 12, height: 112, minHeight: 112,
    padding: '14px 16px', background: 'var(--cth-cream-200)', borderTop: '1px solid var(--cth-ink-300)',
    overflowX: 'auto', overflowY: 'hidden' }}>
    {byActivity(state.agents).map(agent => {
      const tasks = state.tasks.filter(task => task.status === 'doing' && task.assignee === agent.id);
      return <div key={agent.id} draggable onDragStart={event => {
        setDrag(agent.id); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', agent.id);
      }} onDragOver={event => { if (drag && drag !== agent.id) event.preventDefault(); }}
        onDrop={event => { event.preventDefault(); if (drag) state.reorderAgents(drag, agent.id); setDrag(null); }}
        onDragEnd={() => setDrag(null)} style={{ flexShrink: 0, opacity: drag === agent.id ? .4 : 1 }}>
        <AgentCard {...agent} draggable status={agent.id === 'root' && state.rootBusy ? 'thinking' : agent.status}
          selected={state.selectedId === agent.id} onClick={() => state.select(agent.id)}
          onRename={name => state.renameAgent(agent.id, name)} doingCount={tasks.length}
          onTaskNoteClick={() => { if (tasks[0]) state.openTaskDetail(tasks[0].id); }}
          onEditNote={agent.isGod ? undefined : () => {
            const element = document.activeElement?.closest('.lab-agent-card');
            const rect = element?.getBoundingClientRect();
            setEditor({ id: agent.id, left: Math.max(8, Math.min(rect?.left ?? 16, innerWidth - 288)),
              bottom: Math.max(8, innerHeight - (rect?.top ?? innerHeight - 120) + 8) });
          }} />
      </div>;
    })}
    {editor && <><div onClick={() => setEditor(null)} style={{ position: 'fixed', inset: 0, zIndex: 349 }} />
      <section role="dialog" aria-label={t('agentStrip.privateNote', { name: state.agents.find(a => a.id === editor.id)?.name })}
        style={{ position: 'fixed', left: editor.left, bottom: editor.bottom, width: 280, padding: 10, zIndex: 350,
          background: 'var(--cth-paper-100)', boxShadow: 'var(--cth-panel-border-dialog)' }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          {t('agentStrip.privateNote', { name: state.agents.find(a => a.id === editor.id)?.name })}
          <button type="button" onClick={() => setEditor(null)} aria-label={t('agentStrip.closeNoteEditor')}>✕</button>
        </header>
        <textarea autoFocus rows={3} value={state.agents.find(a => a.id === editor.id)?.note ?? ''}
          onChange={e => state.setAgentNote(editor.id, e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setEditor(null); }}
          placeholder={t('agentStrip.notePlaceholder')} style={{ width: '100%', marginTop: 6, resize: 'none' }} />
        <small>{t('agentStrip.oneLineOneBullet')}</small>
      </section></>}
  </div>;
}
