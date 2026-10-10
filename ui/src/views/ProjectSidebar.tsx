import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type Project, type Conversation } from '@/api/client';
import { useStore } from '@/store/store';
import { PixelButton } from '@/components/PixelButton';
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
    if (!activeProjectId) return;
    let alive = true;
    api
      .threads(activeProjectId)
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
  useEffect(() => {
    setThread(null);
    if (!activeProjectId || !activeThreadId) return;
    let alive = true;
    api
      .threads(activeProjectId)
      .then((ts) => {
        if (alive) setThread(ts.find((x) => x.id === activeThreadId) ?? null);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [activeProjectId, activeThreadId, runs]);
  return (
    <div aria-label={t('lab.conversation')} style={{ maxHeight: 160, overflow: 'auto', fontSize: 12 }}>
      {thread?.messages.map((m) => (
        <p key={m.id} style={{ whiteSpace: 'pre-wrap' }}>
          <strong>{m.author}: </strong>
          {m.text}
          {m.run_id && (
            <button type="button" onClick={() => setActiveRun(m.run_id)}>
              {t('lab.run')} {m.run_id}
            </button>
          )}
        </p>
      ))}
    </div>
  );
}
