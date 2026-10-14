// Cast metadata and procedural frames share the recipes in portraitArt.ts.
// See assets/ATTRIBUTION.md.

import { Texture } from 'pixi.js';
import { paintPortrait, sceneFrameBufs, SCENE_W, SCENE_H } from './portraitArt';

export type OfficeCharacterName =
  | 'aster' | 'byte' | 'lumen' | 'quartz' | 'moss' | 'iris'
  | 'atlas' | 'cedar' | 'fern' | 'ember' | 'coral' | 'nova'
  | 'sage' | 'flint' | 'river';

export interface CastMember {
  name: OfficeCharacterName;
  displayName: string;
  /** Signature accent color (hex) — used for the in-scene selection glow. */
  shirt: string;
  /** Blurb shown when this character is picked / has no description yet. */
  blurb: string;
}

/** Selectable roster, in display order. */
export const OFFICE_CAST: CastMember[] = [
  { name: 'aster', displayName: 'Aster', shirt: '#4ba6a0', blurb: 'Conversation coordinator' },
  { name: 'byte', displayName: 'Byte', shirt: '#d98168', blurb: 'Implementation explorer' },
  { name: 'lumen', displayName: 'Lumen', shirt: '#8f86c9', blurb: 'Plan designer' },
  { name: 'quartz', displayName: 'Quartz', shirt: '#63a8c1', blurb: 'Correctness specialist' },
  { name: 'moss', displayName: 'Moss', shirt: '#a4b56e', blurb: 'Memory gardener' },
  { name: 'iris', displayName: 'Iris', shirt: '#c77d9a', blurb: 'Test craftsperson' },
  { name: 'atlas', displayName: 'Atlas', shirt: '#bd9b64', blurb: 'Architecture cartographer' },
  { name: 'cedar', displayName: 'Cedar', shirt: '#739ac8', blurb: 'Workflow coordinator' },
  { name: 'fern', displayName: 'Fern', shirt: '#7aac90', blurb: 'Research companion' },
  { name: 'ember', displayName: 'Ember', shirt: '#c79570', blurb: 'Build engineer' },
  { name: 'coral', displayName: 'Coral', shirt: '#b68bce', blurb: 'Interface designer' },
  { name: 'nova', displayName: 'Nova', shirt: '#7faca7', blurb: 'General explorer' },
  { name: 'sage', displayName: 'Sage', shirt: '#b8a366', blurb: 'Decision steward' },
  { name: 'flint', displayName: 'Flint', shirt: '#7e91ac', blurb: 'Gate keeper' },
  { name: 'river', displayName: 'River', shirt: '#c58c91', blurb: 'Documentation guide' },
];

export const CAST_BY_NAME: Record<OfficeCharacterName, CastMember> =
  Object.fromEntries(OFFICE_CAST.map((c) => [c.name, c])) as Record<OfficeCharacterName, CastMember>;

export const DEFAULT_CHARACTER: OfficeCharacterName = 'byte';

export function hexToNumber(hex: string): number {
  return parseInt(hex.replace('#', ''), 16);
}

// ─── scene frames ────────────────────────────────────────────────────────────
const frameCache = new Map<OfficeCharacterName, Texture[][]>();

function bufToTexture(buf: Uint8ClampedArray): Texture {
  const canvas = document.createElement('canvas');
  canvas.width = SCENE_W; canvas.height = SCENE_H;
  const ctx = canvas.getContext('2d')!;
  const img = ctx.createImageData(SCENE_W, SCENE_H);
  img.data.set(buf);
  ctx.putImageData(img, 0, 0);
  const tex = Texture.from(canvas);
  tex.source.scaleMode = 'nearest';
  return tex;
}

/**
 * Frame grid CharacterSprite expects: 3 rows (down, up, right) × 7 frames
 * [walk1, walk2, walk3, type1, type2, read1, read2]. We provide a front view
 * (down — and reused for the side row, so left/right walkers still show a face)
 * and a back view (up — agents seated facing their desk show their back). The
 * three walk frames are stand / step-left / step-right.
 */
export async function getCastFrames(name: OfficeCharacterName): Promise<Texture[][]> {
  const cached = frameCache.get(name);
  if (cached) return cached;
  const { front, back } = sceneFrameBufs(name);
  const toRow = (bufs: Uint8ClampedArray[]): Texture[] => {
    const [stand, stepL, stepR] = bufs.map(bufToTexture);
    return [stand, stepL, stepR, stand, stand, stand, stand];
  };
  const frontRow = toRow(front);
  const frames: Texture[][] = [frontRow, toRow(back), frontRow]; // down, up, right
  frameCache.set(name, frames);
  return frames;
}

/** Paint a static cast portrait. */
export async function paintCastPortrait(
  ctx: CanvasRenderingContext2D,
  name: OfficeCharacterName,
  scale = 2,
): Promise<void> {
  paintPortrait(ctx, name, scale);
}
