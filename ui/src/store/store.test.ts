import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from './store';
import type { LabEvent, Run } from '@/api/client';

const run: Run = {
  thread_id: null, workspace: "/tmp/test", language: null, policy: "auto", iteration_base: 0,
  id: 'r', goal: 'g', status: 'CODING', project_id: 'p', max_iter: 5,
  budget_cents: 100, budget_unlimited: false, cost_cents: 10, tokens_in: 100, tokens_out: 20,
  paused_reason: null, created_at: '2026-10-09T00:00:00Z',
};
function event(seq: number, total = 10): LabEvent {
  return { run_id: 'r', seq, ts: run.created_at, type: 'step.finished', actor: 'coder',
    payload: { role: 'coder', tokens_in: 100, tokens_out: 20, cost_cents: 10,
      cumulative_cost_cents: total, cumulative_tokens_in: total * 10, cumulative_tokens_out: total * 2 } };
}

beforeEach(() => {
  useStore.getState().setRuns([run]);
  useStore.getState().setActiveRun('r');
});

describe('event replay accounting', () => {
  it('does not add replayed usage to the cumulative API snapshot', () => {
    useStore.getState().applyEvent(event(1));
    expect(useStore.getState().runs[0].cost_cents).toBe(10);
    useStore.getState().applyEvent(event(2, 15));
    expect(useStore.getState().runs[0].cost_cents).toBe(15);
    expect(useStore.getState().runs[0].tokens_in).toBe(150);
  });

  it('ignores duplicates and events from a different run', () => {
    const e = event(1);
    useStore.getState().applyEvent(e);
    useStore.getState().applyEvent(e);
    useStore.getState().applyEvent({ ...event(2), run_id: 'other' });
    expect(useStore.getState().events).toHaveLength(1);
    expect(useStore.getState().telemetry.usage.coder?.input).toBe(100);
  });

  it('keeps a newer snapshot when an older event is replayed after reselection', () => {
    useStore.getState().setRuns([{ ...run, cost_cents: 20 }]);
    useStore.getState().setActiveRun('r');
    useStore.getState().applyEvent(event(1, 10));
    expect(useStore.getState().runs[0].cost_cents).toBe(20);
  });
});

describe('project isolation', () => {
  it('clears run, approvals, tasks, agent activity, telemetry and conversations on switching', () => {
    const s = useStore.getState();
    s.setActiveProject('p'); s.setRuns([run]); s.setActiveRun('r'); s.setActiveThread('thread'); s.setActiveRun('r');
    s.select('coder'); s.setAnswerDraft('r', 'private reply'); s.applyEvent(event(1));
    s.setActiveProject('other');
    const next = useStore.getState();
    expect(next.activeRunId).toBeNull(); expect(next.activeThreadId).toBeNull();
    expect(next.runs).toEqual([]); expect(next.tasks).toEqual([]); expect(next.events).toEqual([]);
    expect(next.agents).toEqual([]); expect(next.answerDrafts).toEqual({}); expect(next.selectedId).toBeNull();
    next.applyEvent(event(2)); expect(useStore.getState().events).toEqual([]);
  });
  it('switching conversations drops the previous run and its approval events', () => {
    useStore.getState().setActiveRun('r'); useStore.getState().applyEvent(event(1));
    useStore.getState().setActiveThread('next-thread');
    expect(useStore.getState().activeRunId).toBeNull(); expect(useStore.getState().events).toEqual([]);
  });
});
