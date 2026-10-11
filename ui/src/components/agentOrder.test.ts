import { describe, expect, it } from 'vitest';
import { byActivity } from './agentOrder';

describe('agent strip order', () => {
  it('keeps root first, active agents next and idle last, preserving drag order within a group', () => {
    const agents = [
      { id: 'arbiter', status: 'idle' as const },
      { id: 'coder', status: 'idle' as const },
      { id: 'root', status: 'idle' as const, isGod: true },
      { id: 'reviewer', status: 'waiting' as const },
      { id: 'planner', status: 'working' as const },
      { id: 'summarizer', status: 'thinking' as const },
    ];
    expect(byActivity(agents).map((a) => a.id)).toEqual(['root', 'planner', 'summarizer', 'reviewer', 'arbiter', 'coder']);
  });
});
