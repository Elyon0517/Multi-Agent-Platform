import type { OfficeCharacterName } from './cast';
export const PORTRAIT_W = 18, PORTRAIT_H = 28, SCENE_W = 18, SCENE_H = 32;
export interface SceneFrames { front: Uint8ClampedArray[]; back: Uint8ClampedArray[]; }
// Project-authored cast colors and distinguishing features, independent of renderer state.
const names = ['aster','byte','lumen','quartz','moss','iris','atlas','cedar','fern','ember','coral','nova','sage','flint','river'];
const shirts = [0x4ba6a0,0xd98168,0x8f86c9,0x63a8c1,0xa4b56e,0xc77d9a,0xbd9b64,0x739ac8,0x7aac90,0xc79570,0xb68bce,0x7faca7,0xb8a366,0x7e91ac,0xc58c91];
const complexions = [0xd6a274,0x785038,0x9e704e,0xf7c9aa];
const hairstyles = [0,1,2,3,4,5,6,4,3,7,2,1,0,4,5];

export function characterPixels(name: OfficeCharacterName, height: number, phase = 0, back = false): Uint8ClampedArray {
  const index = Math.max(0, names.indexOf(name));
  const pixels = new Uint8ClampedArray(18 * height * 4);
  const dot = (x: number, y: number, color: number) => {
    if (x < 0 || y < 0 || x >= 18 || y >= height) return;
    pixels.set([color >>> 16 & 255, color >>> 8 & 255, color & 255, 255], (y * 18 + x) * 4);
  };
  const box = (x: number, y: number, w: number, h: number, color: number) => {
    for (let row = y; row < y + h; row++) for (let col = x; col < x + w; col++) dot(col, row, color);
  };
  const skin = complexions[index % 4], shirt = shirts[index], hair = (35 + 5 * index) * 65536 + (40 + 3 * index) * 256 + 65 + 4 * index;
  const shade = (color: number) => ((color >>> 16) * .72 << 16) | (((color >>> 8 & 255) * .72) << 8) | ((color & 255) * .72);
  const bodyY = height === 32 ? 18 : 21;
  box(4, bodyY, 10, height - bodyY - (height === 32 ? 7 : 0), shirt);
  box(3, bodyY + 1, 2, 6, shade(shirt)); box(13, bodyY + 1, 2, 6, shade(shirt));
  box(7, 16, 4, bodyY - 15, skin);
  if (height === 32) {
    const left = phase === 1 ? 1 : 0, right = phase === 2 ? 1 : 0;
    box(5, 25, 3, 5 - left, 0x363846); box(10, 25, 3, 5 - right, 0x363846);
    box(4, 29 - left, 4, 2, 0x26222e); box(10, 29 - right, 4, 2, 0x26222e);
  }
  const silhouette = [6,8,10,10,10,10,10,10,10,10,10,8,6];
  silhouette.forEach((width, row) => box((18 - width) / 2, row + 3, width, 1, back ? hair : skin));
  box(3, 9, 1, 3, skin); box(14, 9, 1, 3, skin);
  const style = hairstyles[index];
  box(5, 3, 8, 2, hair); box(4, 5, 10, 2, hair);
  if (style === 0 || style === 5) for (let n = 0; n < 4; n++) box(4 + n * 3, 2 + n % 2, 2, 3, hair);
  if (style === 1) for (let n = 0; n < 5; n++) box(4 + n * 2, 2 + n % 2, 2, 4, hair);
  if (style === 2) box(7, 0, 5, 4, hair);
  if (style === 3 || style === 5) { box(3, 5, 2, 13, hair); box(13, 5, 2, 13, hair); }
  if (style === 6) box(5, 6, 6, 2, hair);
  if (style === 7) box(7, 4, 4, 2, skin);
  if (back) { box(4, 7, 10, 6, hair); box(6, 13, 6, 2, shade(hair)); }
  else {
    dot(6, 9, 0x2e262a); dot(11, 9, 0x2e262a); dot(8, 12, shade(skin));
    box(7, 14, 4, 1, 0x9e5650); dot(6, 13, 0x9e5650); dot(11, 13, 0x9e5650);
    if (index % 4 === 0 || index === 5) {
      box(4, 8, 4, 1, 0x26222e); box(10, 8, 4, 1, 0x26222e); box(8, 9, 2, 1, 0x26222e);
      box(4, 10, 4, 1, 0x26222e); box(10, 10, 4, 1, 0x26222e);
    }
  }
  const alpha = pixels.slice();
  for (let y = 0; y < height; y++) for (let x = 0; x < 18; x++) {
    if (alpha[(y * 18 + x) * 4 + 3]) continue;
    if ([[x - 1,y],[x + 1,y],[x,y - 1],[x,y + 1]].some(([xx,yy]) =>
      xx >= 0 && yy >= 0 && xx < 18 && yy < height && alpha[(yy * 18 + xx) * 4 + 3])) dot(x,y,0x26222e);
  }
  return pixels;
}
export function sceneFrameBufs(name: OfficeCharacterName): SceneFrames {
  return { front: [0,1,2].map(phase => characterPixels(name, 32, phase)),
    back: [0,1,2].map(phase => characterPixels(name, 32, phase, true)) };
}
export function paintPortrait(context: CanvasRenderingContext2D, name: OfficeCharacterName, scale = 2): void {
  const bitmap = characterPixels(name, 28);
  context.imageSmoothingEnabled = false;
  // Rectangles avoid temporary DOM canvases, so this renderer also works on OffscreenCanvas.
  for (let n = 0; n < bitmap.length; n += 4) if (bitmap[n + 3]) {
    context.fillStyle = `rgb(${bitmap[n]},${bitmap[n + 1]},${bitmap[n + 2]})`;
    const cell = n / 4; context.fillRect(cell % 18 * scale, Math.floor(cell / 18) * scale, scale, scale);
  }
}
