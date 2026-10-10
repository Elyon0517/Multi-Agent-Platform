import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type Project, type Conversation } from '@/api/client';
import { useStore } from '@/store/store';
import { PixelButton } from '@/components/PixelButton';
import { Icon } from '@/components/Icon';
import ReactMarkdown from 'react-markdown';
import { Status } from './ui';
import { conversationTitle, hasConversationContent } from './conversationNavigation';
export function ProjectSidebar() {
  const { t } = useTranslation();
  const { activeProjectId, activeThreadId, setActiveProject, setActiveThread, requestCommandCenterTab, runs } = useStore();
  const [projects, setProjects] = useState<Project[]>([]);
  const [threads, setThreads] = useState<Conversation[]>([]);
  const [globalThreads, setGlobalThreads] = useState<Conversation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);
  const scope = activeProjectId ?? 'global';
  useEffect(() => {
    let alive = true;
    api.projects().then(p => { if (alive) setProjects(p); }).catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, [activeProjectId, runs]);
  useEffect(() => {
    let alive = true;
    setThreads([]); setError(null);
    const reload = () => {
      void api.threads(scope).then(ts => { if (alive) { setThreads(ts); if (scope === 'global') setGlobalThreads(ts); } }).catch(e => { if (alive) setError(String(e)); });
      if (scope !== 'global') void api.threads('global').then(ts => { if (alive) setGlobalThreads(ts); }).catch(e => { if (alive) setError(String(e)); });
    };
    reload();
    const close = activeThreadId ? api.threadEvents(scope, activeThreadId, type => {
      if (type === 'message.created' || type === 'turn.finished') reload();
    }) : () => undefined;
    return () => { alive = false; close(); };
  }, [scope, activeThreadId, runs]);
  const deleteProject = async (project: Project) => {
    if (!window.confirm(t('lab.deleteProjectConfirm', { name: project.name }))) return;
    // Second confirmation: typing the name guards against an accidental double click.
    const typed = window.prompt(t('lab.deleteProjectTypeName', { name: project.name }));
    if (typed === null) return;
    if (typed.trim() !== project.name) { setError(t('lab.deleteProjectMismatch')); return; }
    try {
      await api.deleteProject(project.id);
      setProjects(old => old.filter(p => p.id !== project.id));
      const state = useStore.getState();
      state.setRuns(state.runs.filter(r => r.project_id !== project.id));
      if (state.activeProjectId === project.id) { setActiveProject(null); setActiveThread(null); state.setActiveRun(null); }
    } catch (e) { setError(String(e)); }
  };
  const newChat = async (projectId: string | null) => {
    if (creatingRef.current) return;
    creatingRef.current = true; setCreating(true); setError(null);
    try {
      const ts = await api.threads(projectId ?? 'global');
      const empty = ts.find(thread => !hasConversationContent(thread));
      const thread = empty ?? await api.createThread(projectId ?? 'global', t('lab.newConversation'));
      setActiveProject(projectId); setActiveThread(thread.id);
    } catch (e) { setError(String(e)); }
    finally { creatingRef.current = false; setCreating(false); }
  };
  const threadList = (items: Conversation[], projectId: string | null) => items.filter(hasConversationContent).map(thread => (
    <button className="sidebar-item sidebar-thread" type="button" key={thread.id}
      aria-current={thread.id === activeThreadId ? 'page' : undefined}
      title={conversationTitle(thread)} onClick={() => { setActiveProject(projectId); setActiveThread(thread.id); }}>
      {conversationTitle(thread)}
    </button>
  ));
  return (
    <nav className="project-navigation" aria-label={t('lab.projects')}>
      <div className="sidebar-actions">
        <PixelButton size="sm" disabled={creating} onClick={() => void newChat(null)}>{t('lab.newConversation')}</PixelButton>
        <PixelButton size="sm" variant="secondary" onClick={() => requestCommandCenterTab('project')}>{t('lab.newProject')}</PixelButton>
      </div>
      <h2>{t('lab.projects')}</h2>
      {projects.length === 0 && <p className="sidebar-empty">{t('lab.noProjects', { defaultValue: 'No projects yet' })}</p>}
      {projects.map(project => (
        <div key={project.id}>
          <div className="sidebar-project-row">
            <button className="sidebar-item sidebar-project" type="button" aria-current={project.id === activeProjectId ? 'page' : undefined}
              onClick={() => { setActiveProject(project.id); requestCommandCenterTab('project'); }}>▣ {project.name}</button>
            <button className="sidebar-icon-button" type="button" title={t('lab.deleteProject')}
              aria-label={`${t('lab.deleteProject')}: ${project.name}`} onClick={() => void deleteProject(project)}>
              <Icon name="trash" />
            </button>
          </div>
          {project.id === activeProjectId && <div className="sidebar-project-threads">
            <button className="sidebar-item" type="button" disabled={creating} onClick={() => void newChat(project.id)}>＋ {t('lab.newConversation')}</button>
            {threadList(threads, project.id)}
          </div>}
        </div>
      ))}
      <h2>{t('lab.conversation')}</h2>
      {threadList(globalThreads, null)}
      {globalThreads.filter(hasConversationContent).length === 0 && <p className="sidebar-empty">{t('lab.noConversations', { defaultValue: 'No conversations yet' })}</p>}
      <Status error={error} />
    </nav>
  );
}
export function ConversationView() {
  const { t } = useTranslation();
  const { activeProjectId, activeThreadId, runs, setActiveRun } = useStore();
  const [thread, setThread] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [delta, setDelta] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Record<string, string>>({});
  useEffect(() => {
    setThread(null); setDraft(''); setDelta(''); setBusy(false); setError(null); setApprovals({});
    if (!activeThreadId) return;
    let alive = true;
    const reload = () => api.threads(activeProjectId ?? 'global').then((ts) => {
      if (alive) setThread(ts.find((x) => x.id === activeThreadId) ?? null);
    }).catch((e) => { if (alive) setError(String(e)); });
    void reload();
    const close = api.threadEvents(activeProjectId ?? 'global', activeThreadId, (type, payload) => {
      if (!alive) return;
      if (type === 'sync') void reload();
      if (type === 'message.delta') { useStore.getState().setRootBusy(true); setDelta(String(payload.text ?? '')); }
      if (type === 'message.created') { setDelta(''); void reload(); }
      if (type === 'turn.finished') { useStore.getState().setRootBusy(false); setDelta(''); setBusy(false); void reload(); }
    });
    return () => { alive = false; close(); };
  }, [activeProjectId, activeThreadId]);
  useEffect(() => {
    if (!thread) return;
    let alive = true;
    const ids = [...new Set(thread.messages.filter((m) => m.kind === 'approval' && m.run_id).map((m) => m.run_id!))];
    void Promise.all(ids.map(async (id) => {
      const detail = await api.run(id);
      return [id, detail.pending_approval?.id ?? ''] as const;
    })).then((items) => { if (alive) setApprovals(Object.fromEntries(items)); }).catch(() => undefined);
    return () => { alive = false; };
  }, [thread, runs]);
  const current = () => useStore.getState().activeProjectId === activeProjectId && useStore.getState().activeThreadId === activeThreadId;
  const send = async () => {
    if (!activeThreadId || !draft.trim() || busy) return;
    setBusy(true); useStore.getState().setRootBusy(true); setError(null);
    const text = draft; setDraft('');
    try {
      const response = await api.sendMessage(activeProjectId ?? 'global', activeThreadId, text);
      if (!current()) return;
      const ts = await api.threads(activeProjectId ?? 'global');
      if (!current()) return;
      setThread(ts.find((x) => x.id === activeThreadId) ?? null);
      if (response.run) {
        useStore.getState().setRuns([...useStore.getState().runs.filter((run) => run.id !== response.run!.id), response.run]);
        setActiveRun(response.run.id);
      }
    } catch (e) { if (current()) { setError(String(e)); setDraft(text); } }
    finally { if (current()) { useStore.getState().setRootBusy(false); setBusy(false); setDelta(''); } }
  };
  return (
    <section aria-label={t('lab.conversation')} style={{ height: '100%', minHeight: 0, width: '100%', display: 'flex', flexDirection: 'column', fontSize: 12, padding: 8 }}>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', overflowWrap: 'anywhere' }}>
      {thread?.messages.map((m) => (
        <article key={m.id} style={{ borderBottom: '1px solid #ddd', padding: 6 }}>
          <strong>{m.author === 'assistant' ? 'Root' : m.author}: </strong><ReactMarkdown>{m.text}</ReactMarkdown>
          {m.sources?.map((source) => <div key={source.ref}>
            {source.kind === 'web' && /^https?:\/\//.test(source.ref)
              ? <a href={source.ref} target="_blank" rel="noreferrer">{source.title || source.ref}</a>
              : <span>{source.kind}: {source.title || source.ref}</span>}
          </div>)}
          {m.run_id && <button type="button" onClick={() => setActiveRun(m.run_id)}>{t('lab.run')}: {runs.find(r => r.id === m.run_id)?.goal ?? 'Root'}</button>}
          {m.kind === 'approval' && m.run_id && approvals[m.run_id] && m.payload?.approval_id === approvals[m.run_id] && <div>
            {(['approve', 'reject', 'abort'] as const).map((decision) => <button key={decision} type="button" onClick={() => {
              const feedback = decision === 'reject' ? window.prompt('Feedback') : undefined;
              if (decision === 'reject' && feedback === null) return;
              void api.decide(m.run_id!, decision, feedback ?? undefined).then(() => {
                if (current()) setApprovals((old) => ({...old, [m.run_id!]: ''}));
              }).catch((e) => { if (current()) setError(String(e)); });
            }}>{decision}</button>)}
          </div>}
        </article>
      ))}
      {delta && <article aria-live="polite"><strong>Root: </strong><ReactMarkdown>{delta}</ReactMarkdown></article>}
      </div>
      {activeThreadId && <form onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <textarea aria-label="Message root" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={20000} disabled={busy} style={{width: '100%'}} />
        <button type="submit" disabled={busy || !draft.trim()}>{busy ? '…' : 'Send'}</button>
      </form>}
      <Status error={error} />
    </section>
  );
}
