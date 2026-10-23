import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useStore } from '@/store/store';
import { usePoll } from '@/hooks/usePoll';
import { MarkdownPreview } from '@/markdown/MarkdownPreview';
import { PixelPanel } from './PixelPanel';
import { PixelButton } from './PixelButton';
export interface HumanQA { q: string; a?: string; askedAt?: string; answeredAt?: string; dismissedAt?: string; }
export interface HiveTask {
  id: string; title: string; description?: string; assignee?: string; status: 'todo' | 'doing' | 'blocked' | 'done';
  dependsOn: string[]; priority: number; createdAt: string; humanQA?: HumanQA[];
}
export function openQuestion(task: HiveTask): HumanQA | undefined {
  return task.humanQA?.slice().reverse().find(question => typeof question.q === 'string' && !question.a && !question.dismissedAt);
}
export function waitsOnHuman(task: HiveTask): boolean { return task.status === 'blocked' && !!openQuestion(task); }
const columns = [
  { status: 'doing', label: 'kanban.colDoing', color: 'lemon' },
  { status: 'blocked', label: 'kanban.colBlocked', color: 'coral' },
  { status: 'done', label: 'kanban.colDone', color: 'mint' },
] as const;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object';
const string = (v: unknown) => typeof v === 'string' ? v : undefined;
export function parseTasks(value: unknown): HiveTask[] {
  if (!record(value) || !Array.isArray(value.tasks)) return [];
  return value.tasks.filter(record).map((raw, index) => {
    const title = string(raw.title) ?? '(untitled)', date = string(raw.createdAt) ?? '';
    // Fallbacks depend only on the received record, never on the wall clock.
    const fallback = Array.from(`${title}|${date}|${index}`).reduce((hash, c) => Math.imul(hash ^ c.charCodeAt(0), 16777619) >>> 0, 2166136261);
    const qa = Array.isArray(raw.humanQA) ? raw.humanQA.filter(record).filter(q => typeof q.q === 'string').map(q => ({
      q: q.q as string, a: string(q.a), askedAt: string(q.askedAt), answeredAt: string(q.answeredAt), dismissedAt: string(q.dismissedAt),
    })) : undefined;
    return { id: string(raw.id) || `t-${fallback.toString(36)}`, title, createdAt: date, description: string(raw.description),
      assignee: string(raw.assignee), status: (['todo','doing','blocked','done'].includes(String(raw.status)) ? raw.status : 'doing') as HiveTask['status'],
      dependsOn: Array.isArray(raw.dependsOn) ? raw.dependsOn.filter((p): p is string => typeof p === 'string') : [],
      priority: typeof raw.priority === 'number' && Number.isFinite(raw.priority) ? raw.priority : 3, humanQA: qa };
  });
}
export function TasksKanban() {
  const state = useStore(), { t } = useTranslation();
  const tasks = usePoll(async () => parseTasks(await window.cth.hiveTasks()), [] as HiveTask[], 5000);
  const [error, setError] = useState('');
  const name = (id?: string) => [...state.agents, ...state.restorableAgents].find(a => a.id === id)?.name ?? id;
  return <section style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--cth-paper-200)' }}>
    <header style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderBottom: '1px solid var(--cth-ink-300)' }}>
      <span style={{ font: '9px var(--cth-font-display)' }}>{t('kanban.count', { count: tasks.length })}</span>
      <small style={{ color: 'var(--cth-ink-300)' }}>{t('kanban.newWorkHint')}</small>
    </header>
    {error && <div role="alert">{error}</div>}
    <div style={{ display: 'flex', padding: 10, gap: 8, flex: 1, minHeight: 0, overflowX: 'auto' }}>
      {columns.map(column => {
        const cards = tasks.filter(task => task.status === column.status);
        return <section key={column.status} style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column',
          background: 'var(--cth-cream-100)', boxShadow: 'var(--cth-panel-border)' }}>
          <header style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 8px 4px',
            background: `var(--cth-${column.color})`, font: '9px var(--cth-font-display)' }}>
            {t(column.label)}<span>{cards.length}</span></header>
          <div style={{ padding: 6, display: 'grid', gap: 6, overflowY: 'auto', alignContent: 'start' }}>
            {!cards.length && <small style={{ textAlign: 'center' }}>—</small>}
            {cards.map(task => <div key={task.id} style={{ position: 'relative' }}>
              <button type="button" title={t('kanban.openTaskDetails')} onClick={() => state.openTaskDetail(task.id)}
                style={{ display: 'grid', gap: 2, width: '100%', textAlign: 'start', cursor: 'pointer', padding: '6px 18px 6px 7px',
                  border: 0, borderLeft: `4px solid var(--cth-${column.color})`, background: 'var(--cth-paper-100)' }}>
                <code style={{ fontSize: 10, color: 'var(--cth-ink-500)' }}>{task.id}</code>
                <span style={{ fontSize: 12 }}>{task.title}</span>
                <small>{name(task.assignee) || t('kanban.unassigned')}{waitsOnHuman(task) ? ' ?' : ''}</small>
                <Priority level={task.priority} />
              </button>
              <button type="button" aria-label={t('kanban.dismissTask')} title={t('kanban.dismissTask')}
                onClick={() => { void window.cth.hiveDeleteTask(task.id).then(result => { if (!result.ok) setError(result.error ?? 'Could not remove task'); }); }}
                style={{ position: 'absolute', right: 2, top: 2, border: 0, background: 'transparent', fontSize: 10 }}>✕</button>
            </div>)}
          </div>
        </section>;
      })}
    </div>
  </section>;
}
function Priority({ level }: { level: number }) {
  const bounded = Math.max(1, Math.min(5, level));
  const { t } = useTranslation();
  return <span title={t('kanban.priority', { level: bounded })} style={{ display: 'inline-flex', gap: 1 }}>
    {Array.from({ length: 5 }, (_, i) => <span key={i} style={{ width: 4, height: 8,
      background: `var(--cth-${i >= bounded ? 'cream-200' : bounded >= 4 ? 'coral' : bounded === 3 ? 'lemon' : 'mint'})`,
      border: '1px solid var(--cth-ink-300)' }} />)}</span>;
}
export function TaskDetail({ task, all, assigneeName, onMove, onAssign, onClose }: {
  task: HiveTask; all: HiveTask[]; assigneeName?: string; onMove: (status: HiveTask['status']) => void;
  onAssign: () => void; onClose: () => void;
}) {
  const { t } = useTranslation(), projectId = useStore(state => state.activeProjectId);
  const column = columns.find(c => c.status === task.status) ?? columns[0];
  const dependencies = all.filter(candidate => task.dependsOn?.includes(candidate.id));
  return <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 280, display: 'grid', placeItems: 'center',
    padding: 24, background: 'rgba(26,19,32,.6)' }}>
    <div role="dialog" aria-modal="true" aria-label={t('kanban.taskTitle')} onClick={event => event.stopPropagation()}
      onKeyDown={event => { if (event.key === 'Escape') onClose(); }} style={{ width: 720, maxWidth: '94vw', maxHeight: '90vh', display: 'flex' }}>
      <PixelPanel variant="dialog" title={t('kanban.taskTitle')} noPadding style={{ width: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: 14, display: 'grid', gap: 10, overflowY: 'auto' }}>
          <div style={{ borderLeft: `4px solid var(--cth-${column.color})`, paddingLeft: 8, fontSize: 15 }}>{task.title}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <code style={{ fontSize: 10 }}>{task.id}</code><span>{t(column.label)}</span>
            <span>{assigneeName ?? t('kanban.unassigned')}</span><Priority level={task.priority} />
            <time style={{ marginLeft: 'auto', fontSize: 10 }}>{Number.isFinite(Date.parse(task.createdAt)) ? new Date(task.createdAt).toLocaleString() : ''}</time>
          </div>
          <pre dir="auto" style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', padding: 10,
            background: 'var(--cth-paper-100)', font: '12px/18px var(--cth-font-mono)', boxShadow: 'var(--cth-panel-border)' }}>
            {task.description?.trim() || t('kanban.noDescription')}</pre>
          {!!task.humanQA?.length && <section><small>{t('kanban.humanQA')}</small>{task.humanQA.map((qa, i) => <div key={i}>
            <div style={{ background: 'var(--cth-lilac-light)', padding: '5px 7px', marginTop: 4 }}>
              Q <MarkdownPreview projectId={projectId ?? undefined} source={qa.q} variant="card" /></div>
            {qa.a ? <div style={{ background: 'var(--cth-mint-light)', padding: '5px 7px' }}>
              A <MarkdownPreview projectId={projectId ?? undefined} source={qa.a} variant="card" /></div> :
              <small style={{ color: 'var(--cth-coral)' }}>{qa.dismissedAt ? 'Dismissed' : t('kanban.awaitingAnswer')}</small>}
          </div>)}</section>}
          {!!dependencies.length && <section><small>{t('kanban.dependsOn')}</small>{dependencies.map(dependency =>
            <div key={dependency.id} style={{ background: 'var(--cth-cream-200)', padding: '3px 6px' }}>{dependency.title}</div>)}</section>}
          <footer style={{ display: 'flex', gap: 6 }}>
            <select aria-label="Task status" value={task.status} onChange={e => onMove(e.target.value as HiveTask['status'])} style={{ flex: 1 }}>
              {columns.map(c => <option key={c.status} value={c.status}>{t(c.label)}</option>)}</select>
            <PixelButton size="sm" variant="secondary" onClick={onAssign}>{t('kanban.assignToAgent')}</PixelButton>
            <PixelButton size="sm" onClick={onClose}>{t('common.close')}</PixelButton>
          </footer>
        </div>
      </PixelPanel>
    </div>
  </div>;
}
