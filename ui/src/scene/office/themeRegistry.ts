// Office themes define map assets, furniture anchors, palettes and cast.

import type { Texture } from 'pixi.js';
import { colors } from '@/design/tokens';
import {
  CAST_BY_NAME,
  getCastFrames,
  DEFAULT_CHARACTER,
  type CastMember,
  type OfficeCharacterName,
} from './cast';

import workspaceUrl from '@/assets/tilesets/workspace.svg?url';
import studioMapRaw from '@/assets/maps/studio.tmj?raw';
import atriumMapRaw from '@/assets/maps/atrium.tmj?raw';

export type ThemeId = 'studio' | 'atrium';

export interface Tile { x: number; y: number; }
export type Facing = 'up' | 'down' | 'left' | 'right';

/** Kinds of small idle errands around the office (incl. plant watering).
 *  'smoke' is the boss special: cigar at the open window, god only. */
export type ErrandKind =
  | 'water' | 'window' | 'dispenser' | 'fridge' | 'shelf' | 'bin' | 'smoke';

/** One idle-errand anchor: a stand tile + facing, an `fx` tile for the ambient
 *  animation, a duration, and an optional god-only restriction. */
export interface ErrandSpot {
  kind: ErrandKind;
  stand: Tile;
  facing: Facing;
  fx: Tile;
  duration: number;
  godOnly?: boolean;
}

/** One tileset atlas + its placement in the global gid space. `embedded` marks
 *  the atlas whose metadata already lives inline in the map's own `tilesets[0]`
 *  (the loader keeps the map's copy and only patches the appended atlases). */
export interface TilesetEntry {
  url: string;
  embedded?: boolean;
  firstgid?: number;
  image?: string;
  imagewidth?: number;
  imageheight?: number;
  tilewidth?: number;
  tileheight?: number;
  columns?: number;
  tilecount?: number;
}

/** Desk-monitor overlay gids. The map paints an OFF monitor block; DeskScreen
 *  overlays the matching ON tiles while the desk's agent is seated. */
export interface MonitorConfig {
  /** gid of the OFF monitor block's top-left tile, as painted in the map. */
  offTopLeftGid: number;
  /** Matching ON tiles as [gid, dx, dy] relative to the block's top-left. */
  onGids: ReadonlyArray<readonly [number, number, number]>;
}

/** The coffee economy's fixed tiles: sideboard (mug rack) → counter machine →
 *  sink → back to the sideboard. `maxCups` caps the clean-mug stock. */
export interface CoffeeConfig {
  trayTile: Tile;
  trayStand: Tile;
  machineStand: Tile;
  sinkTile: Tile;
  sinkStand: Tile;
  maxCups: number;
}

/** Clickable prop anchors (tile coords). calendar → TRIGGERS, boards → TASKS,
 *  clock → CLOSING TIME. */
export interface AnchorConfig {
  calendar: Tile;
  boards: Tile;
  clock: Tile;
}

/** Theme palette. `background` is the canvas clear color; `noteColors` are the
 *  kanban note colors keyed by task status. */
export interface PaletteConfig {
  background: number;
  noteColors: Record<string, number>;
}

/** Per-theme cast loader — the indirection point so a future show can swap its
 *  own roster + sprite frames. The office theme points at cast.ts's exports. */
export interface ThemeCast {
  byName: Record<string, CastMember>;
  getFrames: (name: string) => Promise<Texture[][]>;
  defaultCharacter: string;
}

/** The full contract a theme must supply. See report §A (theme contract). */
export interface ThemeConfig {
  id: ThemeId;
  /** Raw Tiled JSON text; parsed + tileset-patched by themeLoader. */
  mapRaw: string;
  /** Ordered atlases — order matches both the texture load order and the map's
   *  tileset array (texture[i] ↔ tilesets[i]). */
  tilesets: TilesetEntry[];
  /** Desk-claim order, by spawn-point name (seat 0 = god / desk-ceo). */
  primarySeatNames: string[];
  /** Paired café table seats, in order. */
  cafeSeatNames: string[];
  /** Café standing spots: [spawn-point name, kind]. */
  cafeStands: ReadonlyArray<readonly [string, 'coffee' | 'vending']>;
  coffee: CoffeeConfig;
  anchors: AnchorConfig;
  errandSpots: ErrandSpot[];
  monitor: MonitorConfig;
  palette: PaletteConfig;
  cast: ThemeCast;
}

/** Original workspace art; functional anchors match the authored maps. */
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
    background: colors.ink[900],
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
  return THEMES[id] ?? STUDIO_THEME;
}
