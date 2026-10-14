import { describe, expect, it } from 'vitest';
import { THEMES } from './themeRegistry';
import { resolveThemeMap } from './themeLoader';
import { OFFICE_CAST } from './cast';
import { sceneFrameBufs, SCENE_W, SCENE_H } from './portraitArt';

describe('original workspace assets', () => {
  it('ships only the documented original atlas and maps', () => {
    const atlasFiles = import.meta.glob('../../assets/tilesets/*', { eager: true, query: '?raw', import: 'default' });
    const mapFiles = import.meta.glob('../../assets/maps/*', { eager: true, query: '?raw', import: 'default' });
    expect(Object.keys(atlasFiles)).toEqual(['../../assets/tilesets/workspace.svg']);
    expect(Object.keys(mapFiles).sort()).toEqual(['../../assets/maps/atrium.tmj', '../../assets/maps/studio.tmj']);
    const sceneFiles = import.meta.glob('./*.{ts,tsx}', { eager: true, query: '?raw', import: 'default' });
    const sources = Object.entries(sceneFiles).filter(([name]) => !name.endsWith('.test.ts'))
      .map(([, text]) => text).join('\n');
    const retiredReferences = /brooklyn99|hogwarts|dunder|schrute|battlestar|\bmichael\b|\bdwight\b/i;
    expect(sources).not.toMatch(retiredReferences);
    const locales = import.meta.glob('../../i18n/locales/*.json', { eager: true, query: '?raw', import: 'default' });
    for (const text of Object.values(locales)) expect(text).not.toMatch(retiredReferences);
  });
  for (const theme of Object.values(THEMES)) {
    it(`${theme.id}: every activity anchor is reachable and desks have both monitor states`, () => {
      const map = resolveThemeMap(theme);
      const layer = (name: string) => map.layers.find((l) => l.name === name)!;
      const objects = layer('spawn-points').objects!;
      const at = (name: string) => {
        const p = objects.find((o) => o.name === name)!;
        expect(p, name).toBeDefined();
        return { x: p.x / 16, y: p.y / 16 };
      };
      const collision = layer('collision').data!;
      const index = (p: { x: number; y: number }) => p.y * map.width + p.x;
      const origin = at('entrance');
      const visited = new Set<number>([index(origin)]);
      const queue = [origin];
      for (let i = 0; i < queue.length; i++) {
        const { x, y } = queue[i];
        for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
          const p = { x: x + dx, y: y + dy };
          if (p.x < 0 || p.y < 0 || p.x >= map.width || p.y >= map.height) continue;
          const n = index(p);
          if (visited.has(n) || collision[n]) continue;
          visited.add(n); queue.push(p);
        }
      }
      const anchors = [
        ...theme.primarySeatNames.map(at), ...theme.cafeSeatNames.map(at),
        ...theme.cafeStands.map(([name]) => at(name)),
        ...theme.errandSpots.map((s) => s.stand),
        theme.coffee.trayStand, theme.coffee.machineStand, theme.coffee.sinkStand,
      ];
      for (const anchor of anchors) expect(visited.has(index(anchor)), JSON.stringify(anchor)).toBe(true);
      const furniture = layer('furniture-above').data!;
      for (const name of theme.primarySeatNames) {
        const { x, y } = at(name);
        expect(furniture[(y - 2) * map.width + x], name).toBe(theme.monitor.offTopLeftGid);
      }
      for (const l of map.layers.filter((l) => l.type === 'tilelayer')) {
        expect(l.data).toHaveLength(map.width * map.height);
        for (const gid of l.data!) expect(gid).toBeLessThanOrEqual(map.tilesets[0].tilecount!);
      }
      expect(theme.monitor.onGids).toHaveLength(4);
      for (const [gid] of theme.monitor.onGids) expect(gid).toBeLessThanOrEqual(map.tilesets[0].tilecount!);
    });
  }

  it('every original character produces visible walking frames', () => {
    expect(new Set(OFFICE_CAST.map((c) => c.name)).size).toBe(15);
    for (const c of OFFICE_CAST) {
      const { front, back } = sceneFrameBufs(c.name);
      for (const frame of [...front, ...back]) {
        expect(frame).toHaveLength(SCENE_W * SCENE_H * 4);
        expect(frame.some((v, i) => i % 4 === 3 && v > 0)).toBe(true);
      }
    }
  });
});
