import { useEffect, useState } from 'react';
export type WorkspaceImageState = { status: 'loading' } | { status: 'error'; error: string } |
  { status: 'ready'; url: string; mime: string; size: number };
export function useWorkspaceImage(project: string | null | undefined, path: string | null | undefined): WorkspaceImageState {
  const [image, update] = useState<WorkspaceImageState>({ status: 'loading' });
  useEffect(() => {
    const request = new AbortController();
    let url: string | undefined;
    update({ status: 'loading' });
    const load = async () => {
      if (!project || !path) { update({ status: 'error', error: 'no file' }); return; }
      try {
        const result = await window.cth.readBinary(project, path, request.signal);
        if (request.signal.aborted) return;
        if (result.ok) {
          url = URL.createObjectURL(new Blob([result.bytes], { type: result.mime }));
          update({ status: 'ready', url, mime: result.mime, size: result.size });
        } else update({ status: 'error', error: result.error });
      } catch (error) {
        if (!request.signal.aborted) update({ status: 'error', error: String(error instanceof Error ? error.message : error) });
      }
    };
    void load();
    return () => { request.abort(); if (url) URL.revokeObjectURL(url); };
  }, [project, path]);
  return image;
}
