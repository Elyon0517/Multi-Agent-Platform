import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, onConnectionChange } from './client';

const respond = (status: number, body: string) => vi.fn(async () => new Response(body, { status }));

describe('connection tracking', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('names the failed service, sends nothing but the probe while down, and recovers', async () => {
    const seen: Array<[boolean, string | null]> = [];
    const stop = onConnectionChange((reachable, failure) => seen.push([reachable, failure]));

    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(api.health()).rejects.toThrow('server unreachable');

    // Ordinary requests fail fast instead of retrying against a dead server.
    const blocked = respond(200, '[]');
    vi.stubGlobal('fetch', blocked);
    await expect(api.projects()).rejects.toThrow('server unreachable');
    expect(blocked).not.toHaveBeenCalled();

    vi.stubGlobal('fetch', respond(200, '{"ok":true}'));
    await api.health();

    // Vite answers an empty 500 when the backend behind its proxy is down.
    vi.stubGlobal('fetch', respond(500, ''));
    await expect(api.health()).rejects.toThrow();

    vi.stubGlobal('fetch', respond(200, '{"ok":true}'));
    await api.health();
    await api.projects();

    stop();
    expect(seen).toEqual([[false, 'dev-server'], [true, null], [false, 'backend'], [true, null]]);
  });

  it('treats an application error from a running backend as reachable', async () => {
    const seen: boolean[] = [];
    const stop = onConnectionChange((reachable) => seen.push(reachable));
    vi.stubGlobal('fetch', respond(409, '{"detail":"run is busy"}'));
    await expect(api.health()).rejects.toThrow('409 run is busy');
    vi.stubGlobal('fetch', respond(500, '{"detail":"recovery failed"}'));
    await expect(api.health()).rejects.toThrow('recovery failed');
    stop();
    expect(seen).toEqual([]);
  });
});
