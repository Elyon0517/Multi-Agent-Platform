import { describe, expect, it } from 'vitest';
import { Container, Texture, TextureSource } from 'pixi.js';
import { findPath } from './pathfinding';
import { Camera } from './Camera';
import { TiledMapRenderer, type TiledMap } from './TiledMapRenderer';
import { resolveThemeMap } from './themeLoader';
import { THEMES } from './themeRegistry';
import { MessageEnvelope } from './MessageEnvelope';
import { installContextLossRecovery, planInitFailure } from './glRecovery';

const grid = (blocked: number[]) => ({ width: 4, height: 3,
  isWalkable: (x: number, y: number) => x >= 0 && y >= 0 && x < 4 && y < 3 && !blocked.includes(y * 4 + x) });
describe('workspace navigation', () => {
  it('takes a shortest orthogonal route around blocked cells', () => {
    const map = grid([1,5]), path = findPath(map, { x: 0, y: 0 }, { x: 3, y: 0 })!;
    expect(path).toHaveLength(7);
    let previous = { x: 0, y: 0 };
    for (const step of path) {
      expect(Math.abs(step.x - previous.x) + Math.abs(step.y - previous.y)).toBe(1);
      expect(map.isWalkable(step.x, step.y)).toBe(true); previous = step;
    }
    expect(path.at(-1)).toEqual({ x: 3, y: 0 });
  });
  it('rejects unreachable, blocked and out-of-bounds destinations without mutating the grid', () => {
    const map = grid([1,4]);
    expect(findPath(map, { x: 0, y: 0 }, { x: 3, y: 2 })).toBeNull();
    expect(findPath(map, { x: 0, y: 0 }, { x: 1, y: 0 })).toBeNull();
    expect(findPath(map, { x: 0, y: 0 }, { x: 4, y: 0 })).toBeNull();
    expect(findPath(map, { x: 0, y: 0 }, { x: 0, y: 0 })).toEqual([]);
  });
  it('camera smoothing is independent of refresh rate and respects map edges', () => {
    const a = new Container(), b = new Container();
    const setup = (layer: Container) => { const c = new Camera(layer); c.setMapSize(1000, 800); c.setViewSize(500,400); c.focusOn(850,700,2); return c; };
    const ca = setup(a), cb = setup(b);
    for (let n = 0; n < 60; n++) ca.update(1/60);
    for (let n = 0; n < 30; n++) cb.update(1/30);
    expect(a.x).toBeCloseTo(b.x, 7); expect(a.scale.x).toBeCloseTo(b.scale.x, 7);
    expect(a.x).toBeLessThanOrEqual(0); expect(a.x).toBeGreaterThanOrEqual(500 - 1000 * a.scale.x);
    const x = a.x; ca.nudgeToward(0,0); ca.update(0); expect(a.x).toBe(x);
    ca.fitToScreen(); for (let n = 0; n < 200; n++) ca.update(1/30);
    expect(a.scale.x).toBeCloseTo(.5, 4); expect(a.x).toBeCloseTo(0, 3);
  });
});

describe('authored maps render and navigate using the same coordinates', () => {
  const texture = new Texture({ source: new TextureSource({ width: 128, height: 64 }) });
  for (const theme of Object.values(THEMES)) it(`${theme.id}: layer order, atlas, collisions and round trips`, () => {
    const map = new TiledMapRenderer(resolveThemeMap(theme), [texture]);
    expect(map.getContainer().children.map(c => c.label)).toEqual(['floor','walls','furniture-below','furniture-above',null]);
    const entrance = map.getSpawnPoint('entrance')!;
    expect(map.pixelToTile(map.tileToPixel(entrance.x, entrance.y).x, map.tileToPixel(entrance.x, entrance.y).y)).toEqual(entrance);
    for (const name of theme.primarySeatNames) {
      const seat = map.getSpawnPoint(name)!;
      expect(findPath(map, entrance, seat), name).not.toBeNull();
      expect(map.gidAt('furniture-above', seat.x, seat.y - 2)).toBe(9);
    }
    const outside = map.getAllSpawnPoints(); outside.clear(); expect(map.getSpawnPoint('entrance')).toBeDefined();
    expect(map.isWalkable(-1,0)).toBe(false);
    expect(map.textureForGid(0)).toBeUndefined(); expect(map.textureForGid(999)).toBeUndefined();
    map.getContainer().destroy({ children: true });
  });
  it('handles flipped tiles and rectangular map coordinate conversion', () => {
    const data: TiledMap = { width: 2, height: 1, tilewidth: 16, tileheight: 8,
      tilesets: [{ firstgid: 1, columns: 8, tilecount: 32, tilewidth: 16, tileheight: 8 }],
      layers: [{ name: 'floor', type: 'tilelayer', data: [0x80000001, 0x20000001] }] };
    const map = new TiledMapRenderer(data,[texture]);
    expect(map.tileToPixel(1,2)).toEqual({ x: 16, y: 16 });
    expect(map.gidAt('floor',0,0)).toBe(1);
    expect(map.getContainer().children[0].children).toHaveLength(2);
    map.getContainer().destroy({ children: true });
  });
});

describe('message and renderer lifetime', () => {
  it('a message reaches its recipient and finishes once without a wall-clock timer', () => {
    const flight = new MessageEnvelope({ x: 0, y: 0 }, { x: 100, y: 50 }, 'request', false);
    for (let i = 0; i < 200; i++) flight.update(.02);
    expect(flight.update(0)).toBe(true);
    expect(flight.container.x).toBe(100); expect(flight.container.y).toBe(28);
    expect(flight.container.alpha).toBe(0); flight.destroy();
  });
  it('deduplicates context-loss events and cancels scheduled recovery after disposal', () => {
    const target = new EventTarget(), jobs: (() => void)[] = [], called: string[] = [];
    const dispose = installContextLossRecovery(target, { schedule: callback => jobs.push(callback),
      onRebuild: () => called.push('rebuilt'), onGiveUp: () => called.push('stopped'), maxRebuilds: 1 });
    target.dispatchEvent(new Event('webglcontextlost', { cancelable: true }));
    target.dispatchEvent(new Event('webglcontextlost')); expect(jobs).toHaveLength(1);
    jobs[0](); expect(called).toEqual(['rebuilt']);
    target.dispatchEvent(new Event('webglcontextlost')); expect(called).toEqual(['rebuilt','stopped']); dispose();
    const cancel = installContextLossRecovery(target, { schedule: callback => jobs.push(callback), onRebuild: () => called.push('late') });
    target.dispatchEvent(new Event('webglcontextlost')); cancel(); jobs[1](); expect(called).not.toContain('late');
  });
  it('only retries GPU initialization errors, with a bounded budget and cause cycles', () => {
    expect(planInitFailure(new Error('does not support WebGL'),0)).toMatchObject({ action: 'retry', attempt: 1 });
    expect(planInitFailure(new Error('failed to create rendering context'),3)).toEqual({ action: 'give-up' });
    const cycle: { cause?: unknown } = {}; cycle.cause = cycle;
    expect(planInitFailure(cycle,0)).toEqual({ action: 'report' });
    expect(planInitFailure(new Error('Invalid map'),0)).toEqual({ action: 'report' });
  });
});

describe('task markers remain visible through agent arrival and departure', () => {
  it('places assigned work at its desk and falls back to the wall when the worker leaves', async () => {
    const { taskMarkers } = await import('./TaskBoard');
    const tasks = [{ id: 't', status: 'doing' as const, assignee: 'coder' }];
    const onDesk = taskMarkers(tasks,new Map([['coder',{ x: 4, y: 8 }]]),{ x: 100, y: 16 },16);
    expect(onDesk[0]).toMatchObject({ id: 't', x: 51, y: 120 });
    const onWall = taskMarkers(tasks,new Map(),{ x: 100, y: 16 },16);
    expect(onWall[0]).toMatchObject({ id: 't', x: 137, y: 14 });
  });
  it('separates blocked, queued, desk and archived notes without losing task identities', async () => {
    const { taskMarkers } = await import('./TaskBoard');
    const tasks = [
      { id: 'a', status: 'blocked' as const }, { id: 'b', status: 'todo' as const },
      { id: 'c', status: 'doing' as const, assignee: 'coder' },
      { id: 'd', status: 'doing' as const, assignee: 'coder' }, { id: 'e', status: 'done' as const },
    ];
    const markers = taskMarkers(tasks,new Map([['coder',{ x: 4, y: 8 }]]),{ x: 100, y: 16 },16);
    expect(markers.map(marker => marker.id)).toEqual(['a','b','c','d','e']);
    expect(new Set(markers.map(marker => `${marker.x}/${marker.y}`)).size).toBe(5);
    expect(markers[4]).toMatchObject({ x: 171, y: 20 });
  });
});
