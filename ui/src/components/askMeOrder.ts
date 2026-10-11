/** Sort cards by newest open question; keep each card's answer history chronological. */

/** The only thing the ordering needs from a card's open ask. Structural so the
 *  test does not have to construct a whole HiveTask. */
export interface AskLike {
  askedAt?: string;
}

/** `askedAt` as epoch ms, or null when it is missing or unparseable.
 *  Never throws — a hand-edited ledger must not be able to crash the board. */
export function askedAtMs(open: AskLike | undefined): number | null {
  const raw = open?.askedAt;
  if (!raw) return null;
  const ms = Date.parse(raw);
  return Number.isNaN(ms) ? null : ms;
}

/** Newest open question first; missing or invalid timestamps sort last. */
export function compareByNewestAsk(a: AskLike | undefined, b: AskLike | undefined): number {
  const ax = askedAtMs(a);
  const bx = askedAtMs(b);
  if (ax === null && bx === null) return 0;
  if (ax === null) return 1;  // a has no time -> after b
  if (bx === null) return -1; // b has no time -> after a
  return bx - ax;             // descending
}
