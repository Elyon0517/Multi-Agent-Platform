import type { Agent } from '@/store/store';

export function activeFloorAgents(agents: Agent[], rootBusy: boolean): Agent[] {
  const active = agents.filter(a => ['thinking', 'working', 'compacting'].includes(a.status));
  if (rootBusy && !active.some(a => a.id === 'root')) {
    const base = agents.find(a => a.id === 'root') ?? agents.find(a => a.isGod);
    if (base) active.push({ ...base, id: 'root', name: 'Root', status: 'thinking', action: 'Root', isGod: true });
  }
  return active;
}
