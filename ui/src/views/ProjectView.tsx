import { useTranslation } from 'react-i18next';
import { useCallback, useEffect, useState } from 'react';
import { api, type Project, type ProjectStep, type StepStatus } from '@/api/client';
import { PixelPanel } from '@/components/PixelPanel';
import { useStore } from '@/store/store';
import { Muted, Status, errorText } from '@/views/ui';

const DOT: Record<StepStatus, string> = {
  todo: 'var(--cth-ink-300)', doing: 'var(--cth-sky)', done: 'var(--cth-mint)', blocked: 'var(--cth-coral)',
};

function phaseStatus(steps: ProjectStep[]): StepStatus {
  if (steps.every((s) => s.status === 'done')) return 'done';
  if (steps.some((s) => s.status === 'blocked')) return 'blocked';
  return steps.some((s) => s.status !== 'todo') ? 'doing' : 'todo';
}

/** Read-only plan of the current project: what will be done and the result of each run.
 *  Work is started from the Root conversation; creation and configuration live in dialogs. */
export function ProjectView({ onRunStarted }: { onRunStarted: (runId: string) => void }) {
  const { t } = useTranslation();
  const activeProjectId = useStore((s) => s.activeProjectId);
  const runs = useStore((s) => s.runs);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!activeProjectId) { setProject(null); return; }
    api.project(activeProjectId).then(setProject).catch((e) => setError(errorText(e)));
  }, [activeProjectId]);
  useEffect(refresh, [refresh, runs]);

  if (!activeProjectId) return <PixelPanel title={t('lab.project')}><Muted>{t('lab.selectProjectHint')}</Muted></PixelPanel>;
  if (!project) return <Status error={error} />;

  const steps = project.phases.flatMap((p) => p.steps);
  const done = steps.filter((s) => s.status === 'done').length;
  const statusOf = (id: string) => runs.find((r) => r.id === id)?.status;

  return (
    <PixelPanel title={`${project.name} · ${done}/${steps.length}`}>
      <Muted>{project.goal}</Muted>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={done}
        style={{ height: 8, background: 'var(--cth-cream-300)', margin: '6px 0 10px' }}>
        <div style={{ height: '100%', width: `${steps.length ? (done / steps.length) * 100 : 0}%`, background: 'var(--cth-mint)' }} />
      </div>
      {project.phases.map((phase, pi) => (
        <section key={phase.id} style={{ marginBottom: 10 }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 13, display: 'flex', gap: 6, alignItems: 'center' }}>
            <span aria-hidden style={{ width: 8, height: 8, background: DOT[phaseStatus(phase.steps)] }} />
            P{pi + 1} · {phase.title}
          </h3>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            {phase.steps.map((step: ProjectStep) => (
              <li key={step.id} style={{ fontSize: 12, marginBottom: 4 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span aria-label={step.status} style={{ width: 8, height: 8, background: DOT[step.status], flexShrink: 0 }} />
                  <span style={{ flex: 1, textDecoration: step.status === 'done' ? 'line-through' : undefined }}>{step.title}</span>
                </div>
                {step.run_ids.length > 0 && (
                  <div style={{ color: 'var(--cth-ink-500)', fontSize: 11 }}>
                    {t('lab.runLinks')} {step.run_ids.map((id) => (
                      <button key={id} type="button" onClick={() => onRunStarted(id)}
                        style={{ all: 'unset', cursor: 'pointer', textDecoration: 'underline', marginRight: 6 }}>
                        {id}{statusOf(id) ? ` · ${statusOf(id)}` : ''}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </PixelPanel>
  );
}
