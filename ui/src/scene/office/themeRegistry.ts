import type { Texture } from 'pixi.js';
import { CAST_BY_NAME, getCastFrames, DEFAULT_CHARACTER, type CastMember, type OfficeCharacterName } from './cast';
import workspaceUrl from '@/assets/tilesets/workspace.svg?url';
import studioMapRaw from '@/assets/maps/studio.tmj?raw';
import atriumMapRaw from '@/assets/maps/atrium.tmj?raw';
export type ThemeId = 'studio' | 'atrium';
export interface Tile { x: number; y: number; }
export type Facing = 'up' | 'down' | 'left' | 'right';
export type ErrandKind = 'water' | 'window' | 'dispenser' | 'fridge' | 'shelf' | 'bin' | 'smoke';
export interface ErrandSpot { kind: ErrandKind; stand: Tile; facing: Facing; fx: Tile; duration: number; godOnly?: boolean; }
export interface TilesetEntry { url: string; embedded?: boolean; firstgid?: number; image?: string;
  imagewidth?: number; imageheight?: number; tilewidth?: number; tileheight?: number; columns?: number; tilecount?: number; }
export interface MonitorConfig { offTopLeftGid: number; onGids: ReadonlyArray<readonly [number, number, number]>; }
export interface CoffeeConfig { trayTile: Tile; trayStand: Tile; machineStand: Tile; sinkTile: Tile; sinkStand: Tile; maxCups: number; }
export interface AnchorConfig { calendar: Tile; boards: Tile; clock: Tile; }
export interface PaletteConfig { background: number; noteColors: Record<string, number>; }
export interface ThemeCast { byName: Record<string, CastMember>; getFrames: (name: string) => Promise<Texture[][]>; defaultCharacter: string; }
export interface ThemeConfig {
  id: ThemeId; mapRaw: string; tilesets: TilesetEntry[]; primarySeatNames: string[]; cafeSeatNames: string[];
  cafeStands: ReadonlyArray<readonly [string, 'coffee' | 'vending']>; coffee: CoffeeConfig; anchors: AnchorConfig;
  errandSpots: ErrandSpot[]; monitor: MonitorConfig; palette: PaletteConfig; cast: ThemeCast;
}

export const STUDIO_THEME: ThemeConfig = {
  id: 'studio', mapRaw: studioMapRaw,
  tilesets: [{ url: workspaceUrl, embedded: true }],
  primarySeatNames: [
    'desk-ceo', 'pc-1', 'pc-2', 'pc-3', 'pc-4', 'pc-5', 'pc-6',
    'desk-chief-architect', 'desk-product-manager', 'desk-team-lead',
    'desk-backend-engineer', 'desk-ui-ux-expert', 'desk-data-engineer',
    'desk-project-manager', 'desk-market-researcher', 'desk-agent-organizer',
  ],
  cafeSeatNames: ['cafe-seat-1', 'cafe-seat-2', 'cafe-seat-3', 'cafe-seat-4'],
  cafeStands: [['cafe-stand-coffee', 'coffee'], ['cafe-stand-vending', 'vending']],
  coffee: {
    trayTile: { x: 28, y: 20 }, trayStand: { x: 28, y: 21 },
    machineStand: { x: 28, y: 21 }, sinkTile: { x: 31, y: 20 },
    sinkStand: { x: 31, y: 21 }, maxCups: 4,
  },
  anchors: { calendar: { x: 4, y: 1 }, boards: { x: 7, y: 1 }, clock: { x: 1, y: 1 } },
  errandSpots: [
    { kind: 'water', stand: { x: 2, y: 4 }, facing: 'up', fx: { x: 2, y: 3 }, duration: 4.5 },
    { kind: 'water', stand: { x: 24, y: 10 }, facing: 'up', fx: { x: 24, y: 9 }, duration: 4.5 },
    { kind: 'water', stand: { x: 25, y: 21 }, facing: 'up', fx: { x: 25, y: 20 }, duration: 4.5 },
    { kind: 'window', stand: { x: 11, y: 1 }, facing: 'up', fx: { x: 11, y: 0 }, duration: 5 },
    { kind: 'window', stand: { x: 18, y: 1 }, facing: 'up', fx: { x: 18, y: 0 }, duration: 5 },
    { kind: 'dispenser', stand: { x: 33, y: 21 }, facing: 'up', fx: { x: 33, y: 20 }, duration: 3.5 },
    { kind: 'fridge', stand: { x: 32, y: 21 }, facing: 'up', fx: { x: 32, y: 20 }, duration: 3.2 },
    { kind: 'shelf', stand: { x: 33, y: 19 }, facing: 'up', fx: { x: 33, y: 18 }, duration: 4 },
    { kind: 'bin', stand: { x: 24, y: 24 }, facing: 'up', fx: { x: 24, y: 23 }, duration: 2.6 },
  ],
  monitor: { offTopLeftGid: 9, onGids: [[11, 0, 0], [12, 1, 0], [19, 0, 1], [20, 1, 1]] },
  palette: {
    background: 0x1a1320,
    noteColors: { todo: 0xf2df8a, doing: 0x9ecbf0, blocked: 0xf0a3a3, done: 0xa8e0b0 },
  },
  cast: {
    byName: CAST_BY_NAME as Record<string, CastMember>,
    getFrames: (name: string) => getCastFrames(name as OfficeCharacterName),
    defaultCharacter: DEFAULT_CHARACTER,
  },
};

export const ATRIUM_THEME: ThemeConfig = {
  ...STUDIO_THEME, id: 'atrium', mapRaw: atriumMapRaw,
};
export const THEMES: Record<ThemeId, ThemeConfig> = { studio: STUDIO_THEME, atrium: ATRIUM_THEME };

export function getTheme(id: ThemeId): ThemeConfig {
  return Object.prototype.hasOwnProperty.call(THEMES, id) ? THEMES[id] : THEMES.studio;
}
