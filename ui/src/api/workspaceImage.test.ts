import { afterEach, expect, it, vi } from 'vitest';
import { api } from './client';
import { labBridge } from '@/bridge';

afterEach(() => vi.unstubAllGlobals());

it('loads binary bytes by registered project ID and URL-encodes the relative path', async () => {
  const fetch = vi.fn(async (_url: string) => new Response(new Uint8Array([137, 80, 78, 71]), { headers: { 'content-type': 'image/png' } }));
  vi.stubGlobal('fetch', fetch);
  const result = await labBridge.readBinary('project/a', 'screens/a b.png');
  expect(result).toMatchObject({ ok: true, mime: 'image/png', size: 4 });
  expect(fetch.mock.calls[0][0]).toBe('/api/projects/project%2Fa/images?path=screens%2Fa+b.png');
});

it('surfaces authorization/path errors through the bridge', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"invalid image path"}', { status: 422 })));
  const result = await labBridge.readBinary('project', '../private.png');
  expect(result.ok).toBe(false);
  if (!result.ok) expect(result.error).toContain('invalid image path');
});

it('rejects non-image content and oversized bodies, including chunked streams', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('plain text', { headers: { 'content-type': 'text/plain' } })));
  await expect(api.workspaceImage('project', 'image.png')).rejects.toThrow('not an image');
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new Uint8Array(1), {
    headers: { 'content-type': 'image/png', 'content-length': String(11 * 1024 * 1024) },
  })));
  await expect(api.workspaceImage('project', 'image.png')).rejects.toThrow('larger than 10 MB');
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(10 * 1024 * 1024 + 1)); },
    cancel() { cancelled = true; },
  });
  vi.stubGlobal('fetch', vi.fn(async () => new Response(stream, { headers: { 'content-type': 'image/png' } })));
  await expect(api.workspaceImage('project', 'image.png')).rejects.toThrow('larger than 10 MB');
  expect(cancelled).toBe(true);
});
