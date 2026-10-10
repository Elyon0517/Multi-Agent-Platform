import { useCallback, useEffect, useState } from 'react';
import { api, type Project, type ProjectStep, type StepStatus } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { PixelButton } from '@/components/PixelButton';
import { useStore } from '@/store/store';
import { Field, Muted, Status, errorText, inputStyle } from '@/views/ui';

const DOT: Record<StepStatus, string> = {
  todo: 'var(--cth-ink-300)', doing: 'var(--cth-sky)', done: 'var(--cth-mint)', blocked: 'var(--cth-coral)',
};

function phaseStatus(steps: ProjectStep[]): StepStatus {
  if (steps.every((s) => s.status === 'done')) return 'done';
  if (steps.some((s) => s.status === 'blocked')) return 'blocked';
  return steps.some((s) => s.status !== 'todo') ? 'doing' : 'todo';
}

function NewProject({ onCreated, runtime }: { onCreated: (p: Project) => void; runtime?: string }) {
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    if (!name.trim() || !goal.trim() || !workspace.trim()) { setError('name, goal and workspace are required'); return; }
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createProject({ name, goal, workspace, runtime }));
      setName(''); setGoal('');
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PixelPanel title="New project">
      <form onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <Field id="p-name" label="Name"><input id="p-name" style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field id="p-goal" label="Goal" hint="The project-planner (root model) breaks this into phases and steps.">
          <textarea id="p-goal" rows={3} style={inputStyle} value={goal} onChange={(e) => setGoal(e.target.value)} />
        </Field>
        <Field id="p-ws" label="Workspace path (git repo)">
          <input id="p-ws" style={inputStyle} value={workspace} placeholder="/Users/…/my-repo" onChange={(e) => setWorkspace(e.target.value)} />
        </Field>
        <PixelButton disabled={busy} onClick={() => void create()}>{busy ? 'planning…' : 'Create & plan'}</PixelButton>
        <Status error={error} />
      </form>
    </PixelPanel>
  );
}

export function ProjectView({ runtime, onRunStarted }: { runtime?: string; onRunStarted: (runId: string) => void }) {
  const activeProjectId = useStore((s) => s.activeProjectId);
  const setActiveProject = useStore((s) => s.setActiveProject);
  const runs = useStore((s) => s.runs);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const project = projects.find((p) => p.id === activeProjectId) ?? null;

  const refresh = useCallback(() => { api.projects().then(setProjects).catch((e) => setError(errorText(e))); }, []);
  useEffect(refresh, [refresh]);
  useEffect(refresh, [refresh, runs]);

  const startStep = async (step: ProjectStep) => {
    if (!project) return;
    setError(null);
    try {
      const run = await api.createRun({ goal: step.title, runtime, workspace: project.workspace,
        project_id: project.id, step_id: step.id });
      onRunStarted(run.id);
      refresh();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const setStatus = async (step: ProjectStep, status: StepStatus) => {
    if (!project) return;
    const next = await api.patchStep(project.id, step.id, status);
    setProjects((ps) => ps.map((p) => (p.id === next.id ? next : p)));
  };

  const done = project?.phases.flatMap((p) => p.steps).filter((s) => s.status === 'done').length ?? 0;
  const total = project?.phases.flatMap((p) => p.steps).length ?? 0;

  return (
    <>
      <PixelPanel title="Projects">
        {projects.length === 0 && <Muted>No projects yet.</Muted>}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {projects.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => setActiveProject(p.id)} aria-current={p.id === activeProjectId}
                style={{ all: 'unset', cursor: 'pointer', fontWeight: p.id === activeProjectId ? 700 : 400, fontSize: 13 }}>
                {p.name}
              </button>
            </li>
          ))}
        </ul>
      </PixelPanel>
      {project && (
        <PixelPanel title={`${project.name} · ${done}/${total}`}>
          <Muted>{project.goal}</Muted>
          <div role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}
            style={{ height: 8, background: 'var(--cth-cream-300)', margin: '6px 0 10px' }}>
            <div style={{ height: '100%', width: `${total ? (done / total) * 100 : 0}%`, background: 'var(--cth-mint)' }} />
          </div>
          {project.phases.map((phase, pi) => (
            <section key={phase.id} style={{ marginBottom: 10 }}>
              <h3 style={{ margin: '0 0 4px', fontSize: 13, display: 'flex', gap: 6, alignItems: 'center' }}>
                <span aria-hidden style={{ width: 8, height: 8, background: DOT[phaseStatus(phase.steps)] }} />
                P{pi + 1} · {phase.title}
              </h3>
              <ol style={{ margin: 0, paddingLeft: 18 }}>
                {phase.steps.map((step) => (
                  <li key={step.id} style={{ fontSize: 12, marginBottom: 4 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span aria-label={step.status} style={{ width: 8, height: 8, background: DOT[step.status], flexShrink: 0 }} />
                      <span style={{ flex: 1, textDecoration: step.status === 'done' ? 'line-through' : undefined }}>{step.title}</span>
                      {step.status !== 'done' && step.status !== 'doing' && (
                        <PixelButton size="sm" onClick={() => void startStep(step)}>run</PixelButton>
                      )}
                      {step.status !== 'done' && (
                        <PixelButton size="sm" variant="secondary" onClick={() => void setStatus(step, 'done')}>mark done</PixelButton>
                      )}
                    </div>
                    {step.run_ids.length > 0 && (
                      <div style={{ color: 'var(--cth-ink-500)', fontSize: 11 }}>
                        runs: {step.run_ids.map((id) => (
                          <button key={id} type="button" onClick={() => onRunStarted(id)}
                            style={{ all: 'unset', cursor: 'pointer', textDecoration: 'underline', marginRight: 6 }}>{id}</button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </PixelPanel>
      )}
      <Status error={error} />
      <NewProject runtime={runtime} onCreated={(p) => { setProjects((ps) => [...ps, p]); setActiveProject(p.id); }} />
    </>
  );
}
