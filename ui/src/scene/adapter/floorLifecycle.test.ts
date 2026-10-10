import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '@/store/store';
import { activeFloorAgents } from './activity';
import type { LabEvent, RosterEntry, Run } from '@/api/client';

// Acceptance: which sub-agents are on the Office floor while a real run's events stream in.
const roster: RosterEntry[] = [
  { role: 'root', kind: 'worker', alias: 'root', model: 'gpt', ctx_window: 1000 },
  { role: 'supervisor', kind: 'worker', alias: 'root', model: 'gpt', ctx_window: 1000 },
  { role: 'planner', kind: 'worker', alias: 'strong', model: 'claude', ctx_window: 1000 },
  { role: 'coder', kind: 'worker', alias: 'strong', model: 'claude', ctx_window: 1000 },
  { role: 'correctness-reviewer', kind: 'reviewer', alias: 'strong', model: 'claude', ctx_window: 1000 },
  { role: 'arch-reviewer', kind: 'reviewer', alias: 'strong-alt', model: 'gpt', ctx_window: 1000 },
  { role: 'test-style-reviewer', kind: 'reviewer', alias: 'cheap', model: 'gpt-mini', ctx_window: 1000 },
  { role: 'arbiter', kind: 'deterministic', alias: '', model: '', ctx_window: 0 },
];
const run: Run = {
  id: 'r1', goal: 'fix add', status: 'PLANNING', project_id: 'p', max_iter: 5, budget_cents: 100,
  cost_cents: 0, tokens_in: 0, tokens_out: 0, paused_reason: null, created_at: '2026-10-10T00:00:00Z',
};

let seq = 0;
function emit(type: LabEvent['type'], actor: string, payload: Record<string, unknown> = {}): void {
  seq += 1;
  useStore.getState().applyEvent({ run_id: run.id, seq, ts: run.created_at, type, actor, payload });
}
const started = (role: string) => emit('step.started', role, { role, iteration: 1 });
const finished = (role: string, model = 'm') => emit('step.finished', role, { role, model, summary: `${role} done` });
const status = (src: string, dst: string) => emit('run.status', 'driver', { src, dst });
/** Sub-agents currently on the floor; Root is always seated and checked separately. */
const floor = () => activeFloorAgents(useStore.getState().agents, false).map((a) => a.id).filter((id) => id !== 'root').sort();
const statusOf = (id: string) => useStore.getState().agents.find((a) => a.id === id)?.status;

beforeEach(() => {
  seq = 0;
  useStore.getState().setRoster(roster);
  useStore.getState().setRuns([run]);
  useStore.getState().setActiveRun(run.id);
});

describe('Office floor follows the run: agents appear while working and leave when done', () => {
  it('walks planner → coder → gate → three reviewers → approval with the right agents on the floor', () => {
    expect(floor()).toEqual([]);

    started('planner');
    expect(floor()).toEqual(['planner']);
    expect(statusOf('planner')).toBe('thinking');
    finished('planner', 'claude');
    emit('artifact.created', 'planner', { kind: 'plan', to: 'coder' });
    expect(floor()).toEqual([]);
    expect(statusOf('planner')).toBe('success');

    status('PLANNING', 'CODING');
    started('coder');
    emit('step.tool_call', 'coder', { role: 'coder', tool: 'Edit', status: 'started' });
    expect(floor()).toEqual(['coder']);
    expect(statusOf('coder')).toBe('working');
    finished('coder', 'claude');
    expect(floor()).toEqual([]);

    status('CODING', 'GATING');
    emit('step.started', 'gate', { role: 'gate' });
    expect(floor()).toEqual(['gate']);
    emit('gate.finished', 'gate', { passed: true });
    expect(floor()).toEqual([]);

    status('GATING', 'REVIEWING');
    for (const r of ['correctness-reviewer', 'arch-reviewer', 'test-style-reviewer']) started(r);
    expect(floor()).toEqual(['arch-reviewer', 'correctness-reviewer', 'test-style-reviewer']);
    finished('arch-reviewer', 'gpt');
    expect(floor()).toEqual(['correctness-reviewer', 'test-style-reviewer']);
    finished('correctness-reviewer', 'claude');
    finished('test-style-reviewer', 'gpt-mini');
    expect(floor()).toEqual([]);

    status('REVIEWING', 'ARBITRATING');
    emit('arbiter.decision', 'arbiter', { action: 'SIGNOFF' });
    emit('approval.requested', 'supervisor', { reason: 'signoff' });
    status('ARBITRATING', 'WAITING_HUMAN');
    expect(floor()).toEqual([]);
    expect(useStore.getState().runs[0].status).toBe('WAITING_HUMAN');

    emit('approval.decided', 'human', { decision: 'approve' });
    status('WAITING_HUMAN', 'DONE');
    expect(floor()).toEqual([]);
    expect(['planner', 'coder', 'arch-reviewer'].map(statusOf)).toEqual(['idle', 'idle', 'idle']);
  });

  it('shows the model that actually answered on each finished agent', () => {
    started('coder');
    finished('coder', 'claude-opus');
    expect(useStore.getState().agents.find((a) => a.id === 'coder')?.action).toBe('claude-opus');
  });

  it('keeps Root seated the whole time and marks it busy while it answers in chat', () => {
    const ids = (busy: boolean) => activeFloorAgents(useStore.getState().agents, busy).map((a) => [a.id, a.status]);
    expect(ids(false)).toEqual([['root', 'idle']]);
    expect(ids(true)).toEqual([['root', 'thinking']]);
  });

  it('clears agents that were interrupted when the run pauses for a human', () => {
    // e.g. budget pause or execution error after step.started but before step.finished
    status('PLANNING', 'CODING');
    started('planner');
    finished('planner', 'claude');
    started('coder');
    emit('step.tool_call', 'coder', { role: 'coder', tool: 'Edit', status: 'started' });
    for (const r of ['correctness-reviewer', 'arch-reviewer']) started(r);
    emit('approval.requested', 'supervisor', { reason: 'budget_exceeded' });
    status('CODING', 'WAITING_HUMAN');
    expect(floor()).toEqual([]);
    expect(['coder', 'correctness-reviewer', 'arch-reviewer'].map(statusOf)).toEqual(['idle', 'idle', 'idle']);
    expect(statusOf('supervisor')).toBe('blocked');
    expect(statusOf('planner')).toBe('success');
    expect(useStore.getState().agents.find((a) => a.id === 'planner')?.action).toBe('claude');
  });
});
