export interface GlRecoveryOptions {
  maxRebuilds?: number; delayMs?: number; onRebuild: () => void; onGiveUp?: () => void;
  schedule?: (callback: () => void, delay: number) => unknown; log?: (message: string) => void;
}
export const DEFAULT_MAX_REBUILDS = 3, DEFAULT_MAX_INIT_RETRIES = 3, DEFAULT_REBUILD_DELAY_MS = 1500;
export function installContextLossRecovery(target: EventTarget, options: GlRecoveryOptions): () => void {
  let disposed = false, used = 0, scheduled = false;
  const lost = (event: Event) => {
    event.preventDefault();
    if (disposed || scheduled) return;
    if (used >= (options.maxRebuilds ?? 3)) { disposed = true; options.onGiveUp?.(); return; }
    used++; scheduled = true; options.log?.(`Workspace context recovery ${used}`);
    (options.schedule ?? setTimeout)(() => {
      scheduled = false; if (!disposed) options.onRebuild();
    }, options.delayMs ?? DEFAULT_REBUILD_DELAY_MS);
  };
  target.addEventListener('webglcontextlost', lost);
  return () => { disposed = true; target.removeEventListener('webglcontextlost', lost); };
}
export function isContextUnavailableError(error: unknown): boolean {
  const visited = new Set<unknown>();
  let current = error;
  while (current && !visited.has(current)) {
    visited.add(current);
    const object = current as { message?: unknown; cause?: unknown };
    const message = typeof current === 'string' ? current : object.message;
    if (typeof message === 'string' &&
      /does not support webgl|(?:webgl|webgpu|gpu|rendering).{0,12}(?:unavailable|unsupported|not available|not supported)|(?:unable|failed) to (?:create|get|obtain).{0,60}context|no (?:webgl|gpu|rendering) context/i.test(message)) return true;
    current = object.cause;
  }
  return false;
}
export type InitFailurePlan = { action: 'retry'; delayMs: number; attempt: number } | { action: 'give-up' } | { action: 'report' };
export function planInitFailure(error: unknown, attempts: number, options: { maxRetries?: number; delayMs?: number } = {}): InitFailurePlan {
  return !isContextUnavailableError(error) ? { action: 'report' } : attempts >= (options.maxRetries ?? 3)
    ? { action: 'give-up' } : { action: 'retry', attempt: attempts + 1, delayMs: options.delayMs ?? 1500 };
}
