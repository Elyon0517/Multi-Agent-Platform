import type { StatusKind } from './PixelBadge';

// Root stays first; then agents doing work, then those needing attention, then finished, then idle.
const RANK: Record<StatusKind, number> = {
  working: 0, thinking: 0, typing: 0, compacting: 0, looping: 0,
  waiting: 1, blocked: 1,
  success: 2,
  idle: 3, ghost: 3,
};

/** Display order for the agent strip. Stable: within a group, the user's drag order is kept. */
export function byActivity<T extends { isGod?: boolean; status: StatusKind }>(agents: T[]): T[] {
  return agents
    .map((agent, index) => ({ agent, index }))
    .sort((a, b) => Number(!!b.agent.isGod) - Number(!!a.agent.isGod)
      || RANK[a.agent.status] - RANK[b.agent.status]
      || a.index - b.index)
    .map(({ agent }) => agent);
}
