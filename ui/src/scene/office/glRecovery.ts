/** Rebuild the Pixi scene after WebGL context loss, with bounded delayed retries. */

export interface GlRecoveryOptions {
  /** Rebuild attempts before we stop fighting for a context. */
  maxRebuilds?: number;
  /** Wait before rebuilding: the eviction arrives mid-storm (several contexts
   *  are usually created at once), and claiming one back immediately just races
   *  the terminals that displaced us. */
  delayMs?: number;
  /** Rebuild the scene (in OfficeFloor: bump the effect's generation dep). */
  onRebuild: () => void;
  /** Called once, when the retry budget is spent — the caller should say
   *  something visible rather than leaving a silently blank canvas. */
  onGiveUp?: () => void;
  /** Injectable for tests. */
  schedule?: (fn: () => void, ms: number) => unknown;
  log?: (msg: string) => void;
}

export const DEFAULT_MAX_REBUILDS = 3;
export const DEFAULT_REBUILD_DELAY_MS = 1500;

/** Listen for context loss on `canvas` and rebuild. Returns an uninstall fn;
 *  call it from the effect cleanup so a torn-down scene stops responding. */
export function installContextLossRecovery(
  canvas: EventTarget,
  opts: GlRecoveryOptions
): () => void {
  const max = opts.maxRebuilds ?? DEFAULT_MAX_REBUILDS;
  const delay = opts.delayMs ?? DEFAULT_REBUILD_DELAY_MS;
  const schedule = opts.schedule ?? ((fn, ms) => setTimeout(fn, ms));
  const log = opts.log ?? ((m: string) => console.warn(m));

  let rebuilds = 0;
  let live = true;

  const onLost = (e: Event) => {
    // preventDefault allows the browser to restore the context.
    e.preventDefault();
    if (!live) return;
    if (rebuilds >= max) {
      log(`[OfficeFloor] WebGL context lost again after ${max} rebuilds — too many live contexts on this floor; giving up until restart`);
      opts.onGiveUp?.();
      live = false;
      return;
    }
    rebuilds += 1;
    log(`[OfficeFloor] WebGL context lost (Chromium evicted the oldest context) — rebuilding the scene, attempt ${rebuilds}/${max}`);
    schedule(() => { if (live) opts.onRebuild(); }, delay);
  };

  canvas.addEventListener('webglcontextlost', onLost as EventListener, false);
  return () => {
    live = false;
    canvas.removeEventListener('webglcontextlost', onLost as EventListener, false);
  };
}

/* Context creation can fail while the GPU process restarts. Retry init failures
 * separately: context-loss listeners only exist after app.init() succeeds. */

/** Retries before we accept that the floor cannot have a context right now.
 *  Three at 1500ms covers a GPU process restart with room to spare. */
export const DEFAULT_MAX_INIT_RETRIES = 3;

/** Messages meaning "no context for you", across Pixi and Chromium wordings.
 *  Deliberately narrow: anything that is NOT recognised here is reported as the
 *  bug it probably is, rather than hidden behind several seconds of retries. */
const CONTEXT_UNAVAILABLE = [
  /does not support webgl/i,                              // Pixi 8, verbatim
  /web(gl|gpu)\d?\s*(is\s+)?(not\s+(supported|available)|unsupported|unavailable)/i,
  /(unable|failed) to (create|get|obtain)[^.]*context/i,
  /no (webgl|gpu|rendering) context/i,
];

/** True when `err` says a rendering context could not be obtained — a busy
 *  process, not a browser without WebGL. Follows the `cause` chain so a caller
 *  that wrapped the failure in its own Error still classifies correctly. */
export function isContextUnavailableError(err: unknown): boolean {
  for (let e: unknown = err, depth = 0; e && depth < 5; depth++) {
    const msg = typeof e === 'string' ? e : (e as { message?: unknown })?.message;
    if (typeof msg === 'string' && CONTEXT_UNAVAILABLE.some((re) => re.test(msg))) return true;
    e = (e as { cause?: unknown })?.cause;
  }
  return false;
}

export type InitFailurePlan =
  /** Wait `delayMs`, then build the scene again from scratch. */
  | { action: 'retry'; delayMs: number; attempt: number }
  /** Out of budget: tell the user, in words, that the GPU is oversubscribed. */
  | { action: 'give-up' }
  /** Not a context problem — show the error, it is a real failure. */
  | { action: 'report' };

/** Decide what a rejected `app.init()` means. `attemptsUsed` is how many retries
 *  this mount has already spent, so the budget survives across rebuilds. */
export function planInitFailure(
  err: unknown,
  attemptsUsed: number,
  opts: { maxRetries?: number; delayMs?: number } = {}
): InitFailurePlan {
  if (!isContextUnavailableError(err)) return { action: 'report' };
  const max = opts.maxRetries ?? DEFAULT_MAX_INIT_RETRIES;
  if (attemptsUsed >= max) return { action: 'give-up' };
  // Same delay as a rebuild: a GPU process takes a moment to come back, and
  // asking again immediately just gets the same null.
  return { action: 'retry', delayMs: opts.delayMs ?? DEFAULT_REBUILD_DELAY_MS, attempt: attemptsUsed + 1 };
}
