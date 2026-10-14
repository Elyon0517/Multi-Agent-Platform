// Original workspace conversations, independent of character likeness or media.
import type { OfficeCharacterName } from './cast';
export type BreakSpot = 'coffee' | 'vending' | 'snack' | 'table';
const pick = <T,>(items: readonly T[], seed: number): T =>
  items[((seed % items.length) + items.length) % items.length];
const POOLS: Record<BreakSpot, readonly string[]> = {
  coffee: ['Fresh cup, fresh perspective.', 'The kettle has finished its sprint.', 'One sip before the next idea.'],
  vending: ['Choosing a snack is a tiny design review.', 'Crunchy fuel for a quiet afternoon.', 'Saving the last biscuit for later.'],
  snack: ['A small break makes room for a new thought.', 'The fruit bowl has excellent uptime.', 'Back after this snack.'],
  table: ['What did we learn today?', 'A blank page is a good place to start.', 'Resting my eyes before the next review.'],
};
export function pickSoloLine(_character: OfficeCharacterName, spot: BreakSpot, seed: number): string {
  return pick(POOLS[spot], seed);
}
type Exchange = readonly string[];
const EXCHANGES: readonly Exchange[] = [
  ['The tricky case finally has a test.', 'That is a good reason for tea.'],
  ['I drew the data flow on a napkin.', 'Keep it. That might be our next diagram.'],
  ['The build finished while I made coffee.', 'Perfect timing for both.'],
  ['Any ideas for the next iteration?', 'A smaller change and a clearer explanation.'],
  ['The plant grew another leaf.', 'Quiet progress still counts.'],
  ['I found a simpler way through the task.', 'Show me after the break.'],
];
export function pickExchange(_speaker: OfficeCharacterName, seed: number): Exchange {
  return pick(EXCHANGES, seed);
}
