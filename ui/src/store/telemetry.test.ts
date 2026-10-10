import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { LabEvent } from '@/api/client';
import { EMPTY_TELEMETRY, foldTelemetry, stepSummary } from './telemetry';

const ev = (type: LabEvent['type'], actor: string, payload: Record<string, unknown> = {}, seq = 1): LabEvent =>
  ({ run_id: 'r1', seq, ts: '2026-10-09T00:00:00Z', type, actor, payload });

describe('telemetry fold', () => {
  it('accumulates tokens and cost per agent across steps', () => {
    const step = { role: 'coder', model: 'm', tokens_in: 100, tokens_out: 50, cost_cents: 2, latency_ms: 30 };
    const a = foldTelemetry(EMPTY_TELEMETRY, ev('step.finished', 'coder', step));
    const b = foldTelemetry(a.next, ev('step.finished', 'coder', step, 2));
    expect(b.usage).toMatchObject({ agentId: 'coder', input: 200, output: 100, usd: 0.04 });
    expect(b.next.spans.coder).toHaveLength(2);
  });

  it('records failed gate as an unsuccessful span', () => {
    const r = foldTelemetry(EMPTY_TELEMETRY, ev('gate.finished', 'gate', { passed: false, failed_at: 'test' }));
    expect(r.span).toMatchObject({ agentId: 'gate', success: false, error: 'failed at test' });
  });

  it('ignores unrelated events', () => {
    expect(foldTelemetry(EMPTY_TELEMETRY, ev('run.created', 'driver')).next).toBe(EMPTY_TELEMETRY);
  });

  it('extracts step summaries for RecentText', () => {
    expect(stepSummary(ev('step.finished', 'planner', { role: 'planner', summary: 'plan' }))).toEqual({ id: 'planner', text: 'plan' });
    expect(stepSummary(ev('step.started', 'planner'))).toBeNull();
  });
});

const decide = vi.fn();
vi.mock('@/api/client', () => ({ api: { decide: (...a: unknown[]) => decide(...a) } }));

describe('bridge answer -> decision', () => {
  beforeEach(() => { decide.mockReset(); decide.mockResolvedValue({}); });

  it.each([
    ['approve', 'approve', undefined],
    ['LGTM ship it', 'approve', undefined],
    ['abort this', 'abort', undefined],
    ['please add a docstring', 'reject', 'please add a docstring'],
  ])('%s -> %s', async (answer, decision, feedback) => {
    const { labBridge } = await import('@/bridge');
    const r = await labBridge.hivePatchTask('r1', { humanQA: [{ q: 'ok?', a: answer }] });
    expect(r.ok).toBe(true);
    expect(decide).toHaveBeenCalledWith('r1', decision, feedback);
  });

  it('dismiss does not call the API', async () => {
    const { labBridge } = await import('@/bridge');
    await labBridge.hivePatchTask('r1', { humanQA: [{ q: 'ok?', dismissedAt: 'now' }] });
    expect(decide).not.toHaveBeenCalled();
  });
});
