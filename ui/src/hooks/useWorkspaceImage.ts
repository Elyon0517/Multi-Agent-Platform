/** Load a bounded project image through the API, owning its blob URL for the mounted lifetime. */
import { useEffect, useState } from 'react';

export type WorkspaceImageState =
  | { status: 'loading' }
  | { status: 'ready'; url: string; mime: string; size: number }
  | { status: 'error'; error: string };

export function useWorkspaceImage(
  projectId: string | null | undefined,
  rel: string | null | undefined
): WorkspaceImageState {
  const [state, setState] = useState<WorkspaceImageState>({ status: 'loading' });

  useEffect(() => {
    if (!projectId || !rel) {
      setState({ status: 'error', error: 'no file' });
      return;
    }
    const abort = new AbortController();
    let alive = true;
    let created: string | null = null;
    setState({ status: 'loading' });

    void window.cth.readBinary(projectId, rel, abort.signal).then((res) => {
      // Bail BEFORE creating the URL when the consumer already unmounted — a URL
      // created after cleanup has run would never be revoked by anyone.
      if (!alive) return;
      if (!res.ok) { setState({ status: 'error', error: res.error }); return; }
      created = URL.createObjectURL(new Blob([res.bytes], { type: res.mime }));
      setState({ status: 'ready', url: created, mime: res.mime, size: res.size });
    }).catch((e: unknown) => {
      if (alive) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) });
    });

    return () => {
      alive = false;
      abort.abort();
      if (created) URL.revokeObjectURL(created);
    };
  }, [projectId, rel]);

  return state;
}
