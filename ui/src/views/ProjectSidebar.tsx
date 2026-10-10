import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type Project, type Conversation } from '@/api/client';
import { useStore } from '@/store/store';
import { PixelButton } from '@/components/PixelButton';
import ReactMarkdown from 'react-markdown';
import { Status } from './ui';
export function ProjectSidebar() {
  const { t } = useTranslation();
  const {
    activeProjectId,
    activeThreadId,
    setActiveProject,
    setActiveThread,
    requestCommandCenterTab,
    runs,
  } = useStore();
  const [projects, setProjects] = useState<Project[]>([]);
  const [threads, setThreads] = useState<Conversation[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .projects()
      .then((p) => {
        if (alive) setProjects(p);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, [activeProjectId, runs]);
  useEffect(() => {
    setThreads([]);
    setError(null);
    let alive = true;
    api
      .threads(activeProjectId ?? 'global')
      .then((x) => {
        if (alive) setThreads(x);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, [activeProjectId, activeThreadId, runs]);
  return (
    <nav
      aria-label={t('lab.projects')}
      style={{ overflow: 'auto', padding: 8, background: 'var(--cth-cream-100)' }}
    >
      <h2 style={{ fontSize: 14 }}>{t('lab.projects')}</h2>
      <PixelButton size="sm" onClick={() => requestCommandCenterTab('project')}>
        {t('lab.newProject')}
      </PixelButton>
      <PixelButton size="sm" variant="secondary" onClick={() => {
        setActiveProject(null);
        void api.createThread('global', t('lab.newConversation')).then((thread) => {
          if (!useStore.getState().activeProjectId) setActiveThread(thread.id);
        }).catch((e) => setError(String(e)));
      }}>Chat</PixelButton>
      {!activeProjectId && threads.map((thread) => <button type="button" key={thread.id} onClick={() => setActiveThread(thread.id)}>{thread.title}</button>)}
      {projects.map((p) => (
        <div key={p.id} style={{ marginTop: 10 }}>
          <button
            type="button"
            aria-current={p.id === activeProjectId}
            onClick={() => setActiveProject(p.id)}
            style={{
              fontWeight: p.id === activeProjectId ? 700 : 400,
              width: '100%',
              textAlign: 'left',
              padding: 6,
            }}
          >
            {p.name}
          </button>
          {p.id === activeProjectId && (
            <>
              <PixelButton
                size="sm"
                variant="secondary"
                onClick={() => {
                  void api
                    .createThread(p.id, t('lab.newConversation'))
                    .then((thread) => {
                      if (useStore.getState().activeProjectId === p.id) setActiveThread(thread.id);
                    })
                    .catch((e) => setError(String(e)));
                }}
              >
                {t('lab.newConversation')}
              </PixelButton>
              {threads.map((thread) => (
                <button
                  type="button"
                  key={thread.id}
                  aria-current={thread.id === activeThreadId}
                  onClick={() => setActiveThread(thread.id)}
                  style={{
                    display: 'block',
                    margin: '4px 0 4px 12px',
                    fontWeight: thread.id === activeThreadId ? 700 : 400,
                  }}
                >
                  {thread.title}
                </button>
              ))}
            </>
          )}
        </div>
      ))}
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
      if (type === 'message.delta') setDelta(String(payload.text ?? ''));
      if (type === 'message.created') { setDelta(''); void reload(); }
      if (type === 'turn.finished') { setDelta(''); setBusy(false); void reload(); }
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
    setBusy(true); setError(null);
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
    finally { if (current()) { setBusy(false); setDelta(''); } }
  };
  return (
    <section aria-label={t('lab.conversation')} style={{ maxHeight: 400, overflow: 'auto', fontSize: 12, padding: 8 }}>
      {thread?.messages.map((m) => (
        <article key={m.id} style={{ borderBottom: '1px solid #ddd', padding: 6 }}>
          <strong>{m.author}: </strong><ReactMarkdown>{m.text}</ReactMarkdown>
          {m.sources?.map((source) => <div key={source.ref}>
            {source.kind === 'web' && /^https?:\/\//.test(source.ref)
              ? <a href={source.ref} target="_blank" rel="noreferrer">{source.title || source.ref}</a>
              : <span>{source.kind}: {source.title || source.ref}</span>}
          </div>)}
          {m.run_id && <button type="button" onClick={() => setActiveRun(m.run_id)}>{t('lab.run')} {m.run_id}</button>}
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
      {delta && <article aria-live="polite"><strong>assistant: </strong><ReactMarkdown>{delta}</ReactMarkdown></article>}
      {activeThreadId && <form onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <textarea aria-label="Message root" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={20000} disabled={busy} style={{width: '100%'}} />
        <button type="submit" disabled={busy || !draft.trim()}>{busy ? '…' : 'Send'}</button>
      </form>}
      <Status error={error} />
    </section>
  );
}
