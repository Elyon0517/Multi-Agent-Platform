import { useEffect, useRef, useState, useLayoutEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type Project, type Conversation, type RunDetail, type ToolApproval, type ToolDecision } from '@/api/client';
import { ApprovalBar } from './ApprovalBar';
import { useStore } from '@/store/store';
import { PixelButton } from '@/components/PixelButton';
import { Icon } from '@/components/Icon';
import { MarkdownPreview } from '@/markdown/MarkdownPreview';
import { ToolApprovalActions } from './ToolApprovalActions';
import { Status } from './ui';
import { conversationTitle, hasConversationContent } from './conversationNavigation';
export function ProjectSidebar({ collapsed, onCollapsedChange }: { collapsed: boolean; onCollapsedChange: (collapsed: boolean) => void }) {
  const { t } = useTranslation();
  const { activeProjectId, activeThreadId, setActiveProject, setActiveThread, requestCommandCenterTab, openProjectDialog, runs } = useStore();
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
  // Clear the list only when the project changes; refreshes (run events, switching conversations) update it in
  // place, otherwise the list flashes empty and the expanded project looks like it failed to open.
  const loadedScope = useRef<string | null>(null);
  useEffect(() => {
    let alive = true;
    if (loadedScope.current !== scope) { setThreads([]); loadedScope.current = scope; }
    setError(null);
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
  const deleteThread = async (thread: Conversation, projectId: string | null) => {
    if (!window.confirm(t('lab.deleteConversationConfirm', { title: conversationTitle(thread) }))) return;
    setError(null);
    try {
      try {
        await api.deleteThread(projectId ?? 'global', thread.id);
      } catch (e) {
        // A task still running or waiting in this conversation: offer to stop it, then delete.
        if (!String(e).includes('unfinished run') || !window.confirm(t('lab.stopAndDeleteConversation'))) throw e;
        const unfinished = (await api.runs(projectId ?? undefined))
          .filter((r) => r.thread_id === thread.id && r.status !== 'DONE' && r.status !== 'CANCELLED');
        await Promise.all(unfinished.map((r) => api.cancelRun(r.id)));
        await api.deleteThread(projectId ?? 'global', thread.id);
      }
      setThreads((old) => old.filter((x) => x.id !== thread.id));
      setGlobalThreads((old) => old.filter((x) => x.id !== thread.id));
      if (useStore.getState().activeThreadId === thread.id) setActiveThread(null);
    } catch (e) { setError(String(e)); }
  };
  const threadList = (items: Conversation[], projectId: string | null) => items.filter(hasConversationContent).map(thread => (
    <div className="sidebar-project-row" key={thread.id}>
      <button className="sidebar-item sidebar-thread" type="button"
        aria-current={thread.id === activeThreadId ? 'page' : undefined}
        title={conversationTitle(thread)} onClick={() => { setActiveProject(projectId); setActiveThread(thread.id); }}>
        {conversationTitle(thread)}
      </button>
      <button className="sidebar-icon-button danger" type="button" title={t('lab.deleteConversation')}
        aria-label={`${t('lab.deleteConversation')}: ${conversationTitle(thread)}`} onClick={() => void deleteThread(thread, projectId)}>
        <Icon name="trash" />
      </button>
    </div>
  ));
  if (collapsed) {
    return (
      <nav className="project-navigation sidebar-rail" aria-label={t('lab.projects')}>
        <button type="button" className="sidebar-icon-button" title={t('lab.expandSidebar')} aria-label={t('lab.expandSidebar')}
          onClick={() => onCollapsedChange(false)}><Icon name="sidebar" /></button>
      </nav>
    );
  }
  return (
    <nav className="project-navigation" aria-label={t('lab.projects')}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '-6px -2px 6px 0' }}>
        <button type="button" className="sidebar-icon-button" title={t('lab.collapseSidebar')} aria-label={t('lab.collapseSidebar')}
          onClick={() => onCollapsedChange(true)}><Icon name="sidebar" /></button>
      </div>
      <div className="sidebar-actions">
        <PixelButton size="sm" disabled={creating} onClick={() => void newChat(null)}>{t('lab.newConversation')}</PixelButton>
        <PixelButton size="sm" variant="secondary" onClick={() => openProjectDialog('new')}>{t('lab.newProject')}</PixelButton>
      </div>
      <h2>{t('lab.projects')}</h2>
      {projects.length === 0 && <p className="sidebar-empty">{t('lab.noProjects', { defaultValue: 'No projects yet' })}</p>}
      {projects.map(project => (
        <div key={project.id}>
          <div className="sidebar-project-row">
            <button className="sidebar-item sidebar-project" type="button" aria-current={project.id === activeProjectId ? 'page' : undefined}
              onClick={() => { setActiveProject(project.id); requestCommandCenterTab('chat'); }}>▣ {project.name}</button>
            <button className="sidebar-icon-button" type="button" disabled={creating} title={t('lab.newConversation')}
              aria-label={`${t('lab.newConversation')}: ${project.name}`} onClick={() => void newChat(project.id)}>
              <Icon name="plus" />
            </button>
            <button className="sidebar-icon-button danger" type="button" title={t('lab.deleteProject')}
              aria-label={`${t('lab.deleteProject')}: ${project.name}`} onClick={() => void deleteProject(project)}>
              <Icon name="trash" />
            </button>
          </div>
          {project.id === activeProjectId && <div className="sidebar-project-threads">
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
  const [pending, setPending] = useState<string | null>(null);
  const [toolApprovals, setToolApprovals] = useState<Record<string, ToolApproval['status']>>({});
  const [toolRefresh, setToolRefresh] = useState(0);
  const [toolBusy, setToolBusy] = useState(false);
  const [activeRunIds, setActiveRunIds] = useState<string[]>([]);
  const [runStatus, setRunStatus] = useState<Record<string, string>>({});
  const [runDetails, setRunDetails] = useState<Record<string, RunDetail>>({});
  const [refreshTick, setRefreshTick] = useState(0);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [stopping, setStopping] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const unresolvedTools = Object.values(toolApprovals).some((status) => ['pending', 'executing', 'unknown_outcome'].includes(status));
  useEffect(() => {
    if (!activeThreadId) return;
    let alive = true;
    const reload = () => api.toolApprovals(activeProjectId ?? 'global', activeThreadId).then((approvals) => {
      if (alive) setToolApprovals(Object.fromEntries(approvals.map((a) => [a.id, a.status])));
    }).catch((e) => { if (alive) setError(String(e)); });
    void reload();
    const timer = unresolvedTools ? setInterval(() => { void reload(); }, 3000) : undefined;
    return () => { alive = false; if (timer !== undefined) clearInterval(timer); };
  }, [activeProjectId, activeThreadId, toolRefresh, unresolvedTools]);
  // The composer grows with its content up to a limit, then scrolls.
  useLayoutEffect(() => {
    const el = composer.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.4))}px`;
  }, [draft]);
  useEffect(() => {
    setToolApprovals({}); setToolBusy(false);
    setThread(null); setDraft(''); setDelta(''); setBusy(false); setError(null); setPending(null);
    stickToBottom.current = true;
    if (!activeThreadId) return;
    let alive = true;
    const reload = () => Promise.all([
      api.threads(activeProjectId ?? 'global'),
      api.toolApprovals(activeProjectId ?? 'global', activeThreadId),
    ]).then(([ts, approvals]) => {
      if (alive) {
        setThread(ts.find((x) => x.id === activeThreadId) ?? null);
        setToolApprovals(Object.fromEntries(approvals.map((a) => [a.id, a.status])));
      }
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
    // Every run started from this conversation: its pending approval and whether it is still going.
    const ids = [...new Set(thread.messages.filter((m) => m.run_id).map((m) => m.run_id!))];
    const reloadRuns = () => Promise.all(ids.map(async (id) => {
      const detail = await api.run(id);
      return [id, detail.run.status, detail] as const;
    })).then((items) => {
      if (!alive) return;
      setRunDetails(Object.fromEntries(items.map(([id, , detail]) => [id, detail])));
      setRunStatus(Object.fromEntries(items.map(([id, status]) => [id, status])));
      const active = items.filter(([, status]) => status !== 'DONE' && status !== 'CANCELLED' && status !== 'WAITING_HUMAN').map(([id]) => id);
      setActiveRunIds(active);
      // Follow the conversation's running task so the office and agent strip show its live events, even when
      // the task was started elsewhere (another tab, the API or a project step).
      const latest = active.at(-1);
      const store = useStore.getState();
      if (latest && store.activeRunId !== latest && !active.includes(store.activeRunId ?? '')) {
        void api.run(latest).then((detail) => {
          if (!alive || useStore.getState().activeThreadId !== activeThreadId) return;
          useStore.getState().setRuns([...useStore.getState().runs.filter((r) => r.id !== latest), detail.run]);
          useStore.getState().setActiveRun(latest);
        }).catch(() => undefined);
      }
    }).catch(() => undefined);
    // Decisions made through another tab or the API do not create chat messages.
    // Refresh authoritative run details so resolved approvals disappear here too.
    void reloadRuns();
    const timer = ids.length ? window.setInterval(() => { void reloadRuns(); }, 3000) : undefined;
    return () => { alive = false; if (timer !== undefined) window.clearInterval(timer); };
  }, [thread, refreshTick]);
  // Follow new content only while the reader is already at the bottom; opening a conversation always jumps there.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [thread?.messages.length, delta, pending, busy]);
  // Visible elapsed time tells a slow answer apart from a stuck one.
  useEffect(() => {
    if (!busy) { setElapsed(0); return; }
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const current = () => useStore.getState().activeProjectId === activeProjectId && useStore.getState().activeThreadId === activeThreadId;
  const send = async () => {
    if (!activeThreadId || !draft.trim() || busy) return;
    setBusy(true); useStore.getState().setRootBusy(true); setError(null);
    const text = draft; setDraft(''); setPending(text); stickToBottom.current = true;
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
    finally { if (current()) { useStore.getState().setRootBusy(false); setBusy(false); setDelta(''); setPending(null); } }
  };
  const stopRuns = () => {
    setStopping(true); setError(null);
    void Promise.all(activeRunIds.map((id) => api.cancelRun(id)))
      .then(() => { if (current()) setActiveRunIds([]); })
      .catch((e) => { if (current()) setError(String(e)); })
      .finally(() => { if (current()) setStopping(false); });
  };
  // Stopping Root ends the turn early; its reply still arrives through the pending send.
  const stopTurn = () => {
    setStopping(true); setError(null);
    void api.stopTurn(activeProjectId ?? 'global', activeThreadId!)
      .catch((e) => { if (current()) setError(String(e)); })
      .finally(() => { if (current()) setStopping(false); });
  };
  const decideTool = (approvalId: string, decision: ToolDecision) => {
    setToolBusy(true); setError(null);
    void api.decideTool(activeProjectId ?? 'global', activeThreadId!, approvalId, decision)
      .catch((e) => { if (current()) setError(String(e)); })
      .finally(() => { if (current()) { setToolBusy(false); setToolRefresh((x) => x + 1); } });
  };
  return (
    <section aria-label={t('lab.conversation')} className="chat">
      <div ref={scroller} className="chat-scroll" onScroll={(e) => {
        const el = e.currentTarget;
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}>
        <div className="chat-column">
          {thread?.messages.map((m) => {
            const run = m.run_id ? runs.find((r) => r.id === m.run_id) : undefined;
            const toolApproval = m.kind === 'tool_approval' && typeof m.payload?.approval_id === 'string';
            if (m.author === 'user') {
              return <article key={m.id} className="chat-msg user"><div className="chat-bubble">{m.text}</div></article>;
            }
            return (
              <article key={m.id} className={`chat-msg ${m.author === 'system' || m.kind === 'summary' || m.kind === 'tool_result' ? 'note' : 'assistant'}`}>
                {m.author === 'assistant' && m.kind !== 'summary' && <div className="chat-author">Root</div>}
                <div className="chat-md"><MarkdownPreview source={m.text} variant="card" projectId={activeProjectId ?? undefined} /></div>
                {!!m.sources?.length && (
                  <div className="chat-sources">
                    {m.sources.map((source) => source.kind === 'web' && /^https?:\/\//.test(source.ref)
                      ? <a key={source.ref} className="chat-chip" href={source.ref} target="_blank" rel="noreferrer" title={source.ref}>↗ {source.title || source.ref}</a>
                      : <span key={source.ref} className="chat-chip" title={source.ref}>{source.kind === 'file' ? '▤' : '◆'} {source.title || source.ref}</span>)}
                  </div>
                )}
                {m.run_id && (
                  <button type="button" className="chat-run" onClick={() => setActiveRun(m.run_id)}>
                    <span className="chat-run-status">{t('lab.run')} · {runStatus[m.run_id] ?? run?.status ?? '…'}</span>
                    <span className="chat-run-goal">{run?.goal ?? m.run_id}</span>
                  </button>
                )}
                {toolApproval && (
                  <ToolApprovalActions status={toolApprovals[String(m.payload.approval_id)]} busy={toolBusy}
                    onDecision={(decision) => decideTool(String(m.payload.approval_id), decision)} />
                )}
              </article>
            );
          })}
          {pending && !thread?.messages.some((m) => m.author === 'user' && m.text === pending) && (
            <article className="chat-msg user pending"><div className="chat-bubble">{pending}</div></article>
          )}
          {delta && (
            <article className="chat-msg assistant" aria-live="polite">
              <div className="chat-author">Root</div><div className="chat-md"><MarkdownPreview source={delta} variant="card" projectId={activeProjectId ?? undefined} /></div>
            </article>
          )}
          {busy && !delta && (
            <article className="chat-msg assistant" role="status" aria-live="polite">
              <div className="chat-author">Root</div><div className="thinking-dots chat-thinking">{t('lab.rootThinking', { seconds: elapsed })}</div>
            </article>
          )}
        </div>
      </div>
      {Object.values(runDetails).filter((d) => d.run.status === 'DONE' && !acknowledged.includes(d.run.id)).map((d) => (
        <div key={`done-${d.run.id}`} className="chat-decision" role="status">
          <strong>{t('lab.deliveryComplete')}</strong>
          <p>{d.run.goal.slice(0, 120)}</p>
          <p>{t('lab.deliveryNotice')}</p>
          <button type="button" onClick={() => setAcknowledged((ids) => [...ids, d.run.id])}>{t('lab.acknowledgeDelivery')}</button>
        </div>
      ))}
      {/* Decisions the team is waiting for sit right above the composer, like Claude / Codex permission prompts. */}
      {Object.values(runDetails).filter((d) => d.pending_approval).map((d) => (
        <div key={d.pending_approval!.id} className="chat-decision">
          <div className="chat-decision-title">{t('lab.run')} · {d.run.goal.slice(0, 120)}</div>
          <ApprovalBar runId={d.run.id} approval={d.pending_approval!} detail={d}
            onDecided={() => setRefreshTick((n) => n + 1)} />
        </div>
      ))}
      {activeThreadId && (
        <form className="chat-composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <textarea ref={composer} aria-label="Message root" rows={3} value={draft} maxLength={20000} disabled={busy}
            placeholder={t('lab.messageHint')}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter adds a line. Enter that confirms an IME candidate (e.g. pinyin) must not send.
              if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return;
              e.preventDefault();
              void send();
            }} />
          <div className="chat-composer-bar">
            <span>{activeRunIds.length > 0 ? `${t('lab.run')} · ${[...new Set(activeRunIds.map((id) => runStatus[id]))].join(' / ')}` : t('lab.composerHint')}</span>
            {/* Like Claude / Codex: with an empty composer and a task running, the send button becomes Stop. */}
            {busy
              ? <button type="button" className="primary" disabled={stopping} title={t('lab.stopTurnTitle')} onClick={stopTurn}>■ {t('lab.stopRun')}</button>
              : !draft.trim() && activeRunIds.length > 0
              ? <button type="button" className="primary" disabled={stopping} title={t('lab.stopRunTitle')} onClick={stopRuns}>■ {t('lab.stopRun')}</button>
              : <button type="submit" className="primary" disabled={busy || !draft.trim()} aria-label="Send">{busy ? '…' : '↑'}</button>}
          </div>
        </form>
      )}
      <Status error={error} />
    </section>
  );
}

