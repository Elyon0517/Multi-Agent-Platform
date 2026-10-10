import { describe, expect, it } from 'vitest';
import { translate } from './mapping';
import type { LabEvent } from '@/api/client';

const ev = (type: LabEvent['type'], actor: string, payload: Record<string, unknown> = {}): LabEvent =>
  ({ run_id: 'r', seq: 1, ts: new Date().toISOString(), type, actor, payload });

describe('event -> office mapping', () => {
  it('step.started puts the role in thinking', () => {
    expect(translate(ev('step.started', 'coder', { role: 'coder' })).patches[0])
      .toMatchObject({ id: 'coder', status: 'thinking', carrying: 'Edit' });
  });

  it('artifact handoff flies an envelope to the recipient', () => {
    expect(translate(ev('artifact.created', 'planner', { kind: 'plan', to: 'coder' })).handoffs)
      .toEqual([{ from: 'planner', to: 'coder', act: 'propose', needsHuman: false }]);
  });

  it('approval request blocks the supervisor and needs a human', () => {
    const t = translate(ev('approval.requested', 'supervisor', { reason: 'signoff' }));
    expect(t.patches[0]).toMatchObject({ id: 'supervisor', status: 'blocked' });
    expect(t.handoffs[0].needsHuman).toBe(true);
  });

  it('failed gate shows blocked', () => {
    expect(translate(ev('gate.finished', 'gate', { passed: false, failed_at: 'test' })).patches[0].status)
      .toBe('blocked');
  });

  it('terminal run status idles everyone', () => {
    const t = translate(ev('run.status', 'driver', { src: 'WAITING_HUMAN', dst: 'DONE' }));
    expect(t.runStatus).toBe('DONE');
    expect(t.patches.every((p) => p.status === 'idle')).toBe(true);
  });
});
