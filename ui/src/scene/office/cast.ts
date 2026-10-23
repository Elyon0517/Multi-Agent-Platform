import type { Texture } from 'pixi.js';
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


const pending = new Map<string, Promise<Texture[][]>>();
export function getCastFrames(name: OfficeCharacterName): Promise<Texture[][]> {
  if (!pending.has(name)) pending.set(name, buildFrames(name).catch(error => { pending.delete(name); throw error; }));
  return pending.get(name)!;
}
async function buildFrames(name: OfficeCharacterName): Promise<Texture[][]> {
  const { Texture } = await import('pixi.js');
  const source = sceneFrameBufs(name);
  const upload = (buffer: Uint8ClampedArray) => {
    const canvas = document.createElement('canvas'); Object.assign(canvas, { width: SCENE_W, height: SCENE_H });
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Character canvas unavailable');
    const image = context.createImageData(SCENE_W, SCENE_H); image.data.set(buffer); context.putImageData(image, 0, 0);
    const result = Texture.from(canvas); result.source.scaleMode = 'nearest'; return result;
  };
  const row = (buffers: Uint8ClampedArray[]) => {
    const frames = buffers.map(upload); return [...frames, frames[1], frames[2], frames[0], frames[1]];
  };
  const front = row(source.front); return [front, row(source.back), front];
}
export async function paintCastPortrait(context: CanvasRenderingContext2D, name: OfficeCharacterName, scale = 2): Promise<void> {
  paintPortrait(context, name, scale);
}
