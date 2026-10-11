/** Refresh before subscribing so the roster exists when history and live events are applied. */
export function watchRun(refresh: () => Promise<void>, subscribe: (refreshAgain: () => void) => () => void): () => void {
  let alive = true;
  let refreshing = false;
  let close: (() => void) | undefined;
  const reload = async () => {
    if (!alive || refreshing) return;
    refreshing = true;
    try {
      await refresh();
      // A later poll can establish the stream if the initial refresh failed.
      if (alive && !close) close = subscribe(() => { void reload(); });
    } catch {
      // Connection state is surfaced by the API client; polling retries after recovery.
    } finally {
      refreshing = false;
    }
  };
  void reload();
  const timer = setInterval(() => { void reload(); }, 3000);
  return () => { alive = false; clearInterval(timer); close?.(); };
}
