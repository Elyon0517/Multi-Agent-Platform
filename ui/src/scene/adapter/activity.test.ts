import { describe, expect, it } from 'vitest';
import { activeFloorAgents } from './activity';
import type { Agent } from '@/store/store';
const agent = (id: string, status: Agent['status'] = 'idle'): Agent => ({
  id, name: id, status, character: 'jim', accent: 'sky', description: '', action: '', progress: 0,
  project: '', isGod: id === 'supervisor',
});
describe('actual floor activity', () => {
  it('keeps an idle or completed floor empty', () => {
    expect(activeFloorAgents([agent('supervisor'), agent('coder', 'success'), agent('reviewer', 'blocked')], false)).toEqual([]);
  });
  it('shows only root while chatting', () => {
    expect(activeFloorAgents([agent('supervisor'), agent('coder')], true).map(a => a.id)).toEqual(['root']);
  });
  it('shows concurrent workers and removes each after completion', () => {
    const agents = [agent('coder', 'working'), agent('correctness-reviewer', 'thinking'), agent('arch-reviewer', 'thinking')];
    expect(activeFloorAgents(agents, false)).toHaveLength(3);
    agents[0].status = 'success';
    expect(activeFloorAgents(agents, false).map(a => a.id)).toEqual(['correctness-reviewer', 'arch-reviewer']);
  });
});
