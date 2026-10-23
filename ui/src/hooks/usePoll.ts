import { useEffect, useState } from 'react';
// A request finishes before the next timer starts. Cleanup discards late replies.
export function usePoll<T>(load: () => Promise<T>, initial: T, milliseconds: number, key: unknown = ''): T {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try { const next = await load(); if (!stopped) setValue(next); } catch { /* Keep the last completed snapshot. */ }
      if (!stopped) timer = setTimeout(refresh, milliseconds);
    };
    setValue(initial); void refresh();
    return () => { stopped = true; clearTimeout(timer); };
    // Callers supply a stable key for data ownership, not an inline loader identity.
  }, [key, milliseconds]);
  return value;
}
