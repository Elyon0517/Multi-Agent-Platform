import { LANGUAGES, setLanguage } from '@/i18n';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { api, type RunDetail } from '@/api/client';
import { useStore, type ConsoleTab } from '@/store/store';
import { OfficeFloor } from '@/scene/office/OfficeFloor';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { TasksKanban } from '@/components/TasksKanban';
import { TaskDetailOverlay } from '@/components/TaskDetailOverlay';
import { AskMeTab } from '@/components/AskMeTab';
import { AgentStrip } from '@/components/AgentStrip';
import { MemoryGraphPanel } from '@/components/MemoryGraphPanel';
import { RunTimeline } from '@/views/RunTimeline';
import { VerdictBoard } from '@/views/VerdictBoard';
import { ApprovalBar } from '@/views/ApprovalBar';
import { AgentDetail } from '@/views/AgentDetail';
import { ActivityView } from '@/views/ActivityView';
import { KnowledgeView } from '@/views/KnowledgeView';
import { ProjectView } from '@/views/ProjectView';
import { SettingsView } from '@/views/SettingsView';
import { Status, errorText } from '@/views/ui';

const TABS: { key: ConsoleTab; label: string }[] = [
  { key: 'runs', label: 'runs' }, { key: 'project', label: 'project' }, { key: 'tasks', label: 'tasks' },
  { key: 'human', label: 'askMe' }, { key: 'memory', label: 'memory' }, { key: 'graph', label: 'graph' },
  { key: 'activity', label: 'activity' }, { key: 'settings', label: 'settings' },
];

export function App() {
  const { t, i18n } = useTranslation();
  const { activeRunId, runs, setRoster, setRuns, setActiveRun, applyEvent, commandCenterTab: tab,
    requestCommandCenterTab: setTab, selectedId, activeProjectId } = useStore();
  const [goal, setGoal] = useState('make test_add pass');
  const [demo, setDemo] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runtime = demo ? 'fake' : undefined;

  useEffect(() => {
    api.roster().then(setRoster).catch((e) => setError(errorText(e)));
    api.runs().then(setRuns).catch(() => undefined);
  }, [setRoster, setRuns]);

  useEffect(() => {
    if (!activeRunId) { setDetail(null); return; }
    const refresh = () => api.run(activeRunId).then(setDetail).catch(() => undefined);
    void refresh();
    return api.events(activeRunId, (e) => {
      applyEvent(e);
      if (e.type === 'run.status' || e.type === 'step.finished' || e.type.startsWith('approval')) void refresh();
    });
  }, [activeRunId, applyEvent]);

  const openRun = async (id: string) => {
    setRuns(await api.runs());
    setActiveRun(id);
    setTab('runs');
  };

  const start = async () => {
    setError(null);
    try {
      const run = await api.createRun({ goal, runtime, project_id: activeProjectId ?? undefined });
      await openRun(run.id);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 460px', height: '100vh', gap: 8, padding: 8, boxSizing: 'border-box' }}>
      <main style={{ display: 'grid', gridTemplateRows: 'auto 1fr auto auto', gap: 8, minHeight: 0 }}>
        <PixelPanel title="Agent Converge">
          <form onSubmit={(e) => { e.preventDefault(); void start(); }} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label htmlFor="goal" style={{ position: 'absolute', left: -9999 }}>{t('lab.goal')}</label>
            <input id="goal" value={goal} onChange={(e) => setGoal(e.target.value)}
              style={{ flex: 1, fontFamily: 'var(--cth-font-mono)', padding: 6 }} />
            <label style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center', whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> {t('lab.demoOffline')}
            </label>
            <select aria-label={t('lab.language')} value={i18n.resolvedLanguage ?? 'en'} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.label}</option>)}
            </select>
            <PixelButton onClick={() => void start()}>{t('lab.run')}</PixelButton>
          </form>
          <Status error={error} />
        </PixelPanel>
        <section aria-label={t('lab.officeFloor')} style={{ position: 'relative', minHeight: 0 }}>
          <OfficeFloor />
        </section>
        {detail?.pending_approval && <ApprovalBar runId={detail.run.id} approval={detail.pending_approval} />}
        <AgentStrip />
      </main>
      <aside style={{ display: 'grid', gridTemplateRows: 'auto 1fr', gap: 8, minHeight: 0 }}>
        <nav role="tablist" aria-label={t('lab.console')} style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {TABS.map((t) => (
            <PixelButton key={t.key} size="sm" variant={t.key === tab ? 'primary' : 'secondary'} onClick={() => setTab(t.key)}>
              {i18n.t(`lab.${t.label}`)}
            </PixelButton>
          ))}
        </nav>
        <div style={{ overflow: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {selectedId && <AgentDetail />}
          {tab === 'runs' && (
            <>
              <PixelPanel title={t('lab.runs')}>
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {runs.map((r) => (
                    <li key={r.id}>
                      <button type="button" onClick={() => setActiveRun(r.id)} aria-current={r.id === activeRunId}
                        style={{ all: 'unset', cursor: 'pointer', fontWeight: r.id === activeRunId ? 700 : 400 }}>
                        {r.id} · {r.status} · {r.cost_cents.toFixed(2)}c
                      </button>
                    </li>
                  ))}
                </ul>
              </PixelPanel>
              {detail && <RunTimeline detail={detail} />}
              {detail && <VerdictBoard detail={detail} />}
            </>
          )}
          {tab === 'project' && <ProjectView runtime={runtime} onRunStarted={(id) => void openRun(id)} />}
          {tab === 'tasks' && <TasksKanban />}
          {tab === 'human' && <AskMeTab />}
          {tab === 'memory' && <KnowledgeView />}
          {tab === 'graph' && (
            <MemoryGraphPanel godId="supervisor"
              onJumpToMemory={(id) => { useStore.getState().select(id); setTab('memory'); }} />
          )}
          {tab === 'activity' && <ActivityView />}
          {tab === 'settings' && <SettingsView />}
        </div>
      </aside>
      <TaskDetailOverlay />
    </div>
  );
}
