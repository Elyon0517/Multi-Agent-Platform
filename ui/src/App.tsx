import { LANGUAGES, setLanguage } from '@/i18n';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, type RunDetail } from '@/api/client';
import { useStore, type ConsoleTab } from '@/store/store';
import { OWNER_BY_RUN_STATUS, seatFor } from '@/scene/adapter/mapping';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { TasksKanban } from '@/components/TasksKanban';
import { TaskDetailOverlay } from '@/components/TaskDetailOverlay';
import { AskMeTab } from '@/components/AskMeTab';
import { AgentStrip } from '@/components/AgentStrip';
import { RunTimeline } from '@/views/RunTimeline';
import { VerdictBoard } from '@/views/VerdictBoard';
import { ApprovalBar } from '@/views/ApprovalBar';
import { AgentDetail } from '@/views/AgentDetail';
import { ActivityView } from '@/views/ActivityView';
import { KnowledgeView } from '@/views/KnowledgeView';
import { ProjectView } from '@/views/ProjectView';
import { ProjectDialogs } from '@/views/ProjectDialogs';
import { ConnectionDialog } from '@/views/ConnectionDialog';
import { ConsoleSplitter, OfficeMonitor } from '@/views/LayoutControls';
import { loadLayout, saveLayout, type LayoutPrefs } from '@/views/layoutPrefs';
import { Icon } from '@/components/Icon';
import { MonitorView } from '@/views/MonitorView';
import { SettingsView } from '@/views/SettingsView';
import { Status, errorText } from '@/views/ui';

import { ArtifactViewer } from '@/views/ArtifactViewer';
import { ProjectSidebar, ConversationView } from '@/views/ProjectSidebar';

const TABS: { key: ConsoleTab; label: string }[] = [
  { key: 'chat', label: 'conversation' },
  { key: 'runs', label: 'runs' }, { key: 'project', label: 'project' }, { key: 'tasks', label: 'tasks' },
  { key: 'human', label: 'askMe' }, { key: 'memory', label: 'memory' },
  { key: 'activity', label: 'activity' }, { key: 'monitor', label: 'monitor' }, { key: 'settings', label: 'settings' },
];

export function App() {
  const { t, i18n } = useTranslation();
  const { activeRunId, runs, setRoster, setRuns, setActiveRun, applyEvent, commandCenterTab: tab,
    requestCommandCenterTab: setTab, selectedId, activeProjectId, activeThreadId, setActiveThread } = useStore();
  const [demo, setDemo] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runtime = demo ? 'fake' : undefined;
  const [layout, setLayout] = useState<LayoutPrefs>(loadLayout);
  const updateLayout = (patch: Partial<LayoutPrefs>) => setLayout((old) => { const next = { ...old, ...patch }; saveLayout(next); return next; });
  const sidebarWidth = layout.sidebarCollapsed ? 32 : 200;

  useEffect(() => {
    let alive = true;
    api.runs(activeProjectId ?? undefined).then(x => { if (alive) setRuns(activeProjectId ? x : x.filter(r => r.project_id === 'default')); }).catch(() => undefined);
    setError(null);
    return () => { alive = false; };
  }, [activeProjectId, setRoster, setRuns]);

  useEffect(() => {
    let alive = true;
    api.roster(activeProjectId ?? undefined, activeRunId ?? undefined)
      .then(x => { if (alive) setRoster(x); })
      .catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [activeProjectId, activeRunId, setRoster]);

  useEffect(() => {
    setDetail(null);
    if (!activeRunId) { setDetail(null); return; }
    const refresh = () => api.run(activeRunId).then((next) => {
      if (useStore.getState().activeRunId !== activeRunId) return;
      setDetail(next);
      void api.roster(next.run.project_id === 'default' ? undefined : next.run.project_id, activeRunId)
        .then(x => { if (useStore.getState().activeRunId === activeRunId) setRoster(x); })
        .catch(() => undefined);
      const current = useStore.getState().runs;
      setRuns(current.map((run) => run.id === next.run.id ? next.run : run));
    }).catch(() => undefined);
    void refresh();
    return api.events(activeRunId, (e) => {
      applyEvent(e);
      if (e.type === 'run.status' || e.type === 'step.finished' || e.type.startsWith('approval')) void refresh();
    });
  }, [activeRunId, applyEvent, setRuns]);

  // `?follow=1` (used by scripts/showcase.py): keep the newest run without a project on screen.
  useEffect(() => {
    if (!new URLSearchParams(window.location.search).has('follow')) return;
    const timer = setInterval(() => {
      if (useStore.getState().activeProjectId) return;
      void api.runs().then((all) => {
        const runs = all.filter(r => r.project_id === 'default');
        const newest = runs.reduce<typeof runs[number] | null>((a, r) => (!a || r.created_at > a.created_at ? r : a), null);
        if (!newest || newest.id === useStore.getState().activeRunId) return;
        setRuns(runs);
        setActiveRun(newest.id);
        setTab('runs');
      }).catch(() => undefined);
    }, 1500);
    return () => clearInterval(timer);
  }, [setRuns, setActiveRun, setTab]);

  const openRun = async (id: string) => {
    const projectId = useStore.getState().activeProjectId;
    const next = await api.runs(projectId ?? undefined);
    if (useStore.getState().activeProjectId !== projectId || !next.some(r => r.id === id && (!projectId || r.project_id === projectId))) return;
    setRuns(projectId ? next : next.filter(r => r.project_id === 'default'));
    setActiveRun(id);
    setTab('runs');
  };

  return (
    <div className={`app-layout${layout.sidebarCollapsed ? ' sidebar-collapsed' : ''}`} style={{ display: 'grid', gridTemplateColumns: `${sidebarWidth}px minmax(0, 1fr) 6px ${layout.consoleWidth}px`, columnGap: 0, height: '100vh', padding: 8, boxSizing: 'border-box' }}>
      <ProjectSidebar collapsed={layout.sidebarCollapsed} onCollapsedChange={(sidebarCollapsed) => updateLayout({ sidebarCollapsed })} />
      <main className="workspace-main" style={{ minWidth: 0, margin: '0 0 0 8px', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', alignContent: layout.officeMinimized ? 'start' : undefined, gridTemplateRows: `auto ${layout.officeMinimized ? 'auto' : 'minmax(0, 1fr)'} auto${detail?.pending_approval ? ' auto' : ''}`, gap: 8, minHeight: 0 }}>
        {/* Work starts in the Root conversation; the header only holds global toggles. */}
        <header style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between', padding: '4px 8px',
          background: 'var(--cth-cream-200)', boxShadow: 'inset 0 0 0 1px var(--cth-ink-300)' }}>
          <h1 style={{ margin: 0, fontFamily: 'var(--cth-font-display)', fontSize: 11 }}>Multi-Agent Platform</h1>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center', whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> {t('lab.demoOffline')}
            </label>
            <select aria-label={t('lab.language')} value={i18n.resolvedLanguage ?? 'en'} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.label}</option>)}
            </select>
          </div>
          {error && <div style={{ flexBasis: '100%' }}><Status error={error} /></div>}
        </header>
        <OfficeMonitor minimized={layout.officeMinimized} onMinimizedChange={(officeMinimized) => updateLayout({ officeMinimized })} />
        {detail?.run.id === activeRunId && detail?.pending_approval && <ApprovalBar key={detail.pending_approval.id} runId={detail.run.id} approval={detail.pending_approval} detail={detail} />}
        <AgentStrip />
      </main>
      <ConsoleSplitter width={layout.consoleWidth} leftWidth={sidebarWidth} onChange={(consoleWidth) => updateLayout({ consoleWidth })} />
      <aside className="workspace-console" style={{ minWidth: 0, display: 'grid', gridTemplateRows: 'auto 1fr', gap: 8, minHeight: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
          <nav role="tablist" aria-label={t('lab.console')} style={{ display: 'flex', gap: 4, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
            {TABS.map((t) => (
              <PixelButton key={t.key} size="sm" variant={t.key === tab ? 'primary' : 'secondary'} onClick={() => setTab(t.key)}>
                {i18n.t(`lab.${t.label}`)}
              </PixelButton>
            ))}
          </nav>
          {activeProjectId && (
            <span title={t('lab.agentConfiguration')} style={{ flex: 'none' }}>
              <PixelButton size="sm" variant="secondary" onClick={() => useStore.getState().openProjectDialog('config')}>
                <span style={{ display: 'inline-flex', alignItems: 'center' }} aria-label={t('lab.agentConfiguration')}><Icon name="gear" /></span>
              </PixelButton>
            </span>
          )}
        </div>
        <div style={{ overflow: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: tab === 'chat' ? 'flex' : 'none', flex: 1, minHeight: 0 }}><ConversationView /></div>
          {selectedId && <AgentDetail />}
          {tab === 'runs' && (
            <>
              <PixelPanel title={t('lab.runs')}>
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {runs.map((r) => (
                    <li key={r.id}>
                      <button type="button" onClick={() => setActiveRun(r.id)} aria-current={r.id === activeRunId}
                        style={{ all: 'unset', cursor: 'pointer', fontWeight: r.id === activeRunId ? 700 : 400 }}>
                        {seatFor(OWNER_BY_RUN_STATUS[r.status]).name} · {r.goal} · {r.status} · {r.cost_cents.toFixed(2)}c
                      </button>
                    </li>
                  ))}
                </ul>
              </PixelPanel>
              {detail?.run.id === activeRunId && <RunTimeline detail={detail} />}
              {detail?.run.id === activeRunId && <VerdictBoard key={`verdict:${detail.run.id}`} detail={detail} />}
              {detail?.run.id === activeRunId && <ArtifactViewer key={`artifact:${detail.run.id}`} detail={detail} />}
            </>
          )}
          {tab === 'project' && <ProjectView onRunStarted={(id) => void openRun(id)} />}
          {tab === 'tasks' && <TasksKanban />}
          {tab === 'human' && <AskMeTab />}
          {tab === 'memory' && <KnowledgeView key={activeProjectId ?? 'global'} />}
          {tab === 'activity' && <ActivityView />}
          {tab === 'monitor' && <MonitorView />}
          {tab === 'settings' && <SettingsView />}
        </div>
      </aside>
      <TaskDetailOverlay />
      <ProjectDialogs runtime={runtime} />
      <ConnectionDialog />
    </div>
  );
}
