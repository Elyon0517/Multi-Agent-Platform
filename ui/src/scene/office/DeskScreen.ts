import { Container, Graphics, Sprite } from 'pixi.js';
import type { TiledMapRenderer } from './TiledMapRenderer';
import type { MonitorConfig } from './themeRegistry';

// Original atlas includes dark and lit 2x2 desk blocks.
export const MONITOR_OFF_TOPLEFT_GID = 9;
const DEFAULT_ON_GIDS: ReadonlyArray<readonly [number, number, number]> = [
  [11, 0, 0], [12, 1, 0], [19, 0, 1], [20, 1, 1],
];

const SCREEN = { x: 3, y: 5, w: 25, h: 12 };

export class DeskScreen {
  readonly container = new Container();
  private anim = new Graphics();
  private on = false;
  private t = 0;

  constructor(mapRenderer: TiledMapRenderer, topLeft: { x: number; y: number }, monitor?: MonitorConfig) {
    const ts = mapRenderer.tileSize;
    const onGids = monitor?.onGids ?? DEFAULT_ON_GIDS;
    for (const [gid, dx, dy] of onGids) {
      const tex = mapRenderer.textureForGid(gid);
      if (!tex) continue;
      const s = new Sprite(tex);
      s.x = dx * ts;
      s.y = dy * ts;
      this.container.addChild(s);
    }
    this.anim.eventMode = 'none';
    this.container.addChild(this.anim);
    this.container.x = topLeft.x * ts;
    this.container.y = topLeft.y * ts;
    // Sort with the characters: the block's bottom edge sits above the seated
    // agent's anchor row, so the avatar's head draws over the keyboard, not
    // under it — same painter's order the map art implies.
    this.container.zIndex = (topLeft.y + 2) * ts - 1;
    this.container.visible = false;
    this.container.eventMode = 'none';
  }

  /** Light the screen (agent sat down) or cut it (stood up / left). */
  setOn(on: boolean): void {
    if (on === this.on) return;
    this.on = on;
    this.container.visible = on;
    if (!on) { this.anim.clear(); this.t = 0; }
  }

  update(dt: number): void {
    if (!this.on) return;
    this.t += dt;
    const g = this.anim;
    g.clear();
    // Two faint "output" lines scrolling up the desktop, wrapping around —
    // the eternal build log — plus a cursor blinking in the lower left.
    for (let i = 0; i < 2; i++) {
      const phase = (this.t * 3.2 + i * (SCREEN.h / 2)) % SCREEN.h;
      const y = SCREEN.y + SCREEN.h - 1 - phase;
      const w = 6 + ((i * 7 + Math.floor(this.t / 1.7)) % 9);
      g.rect(SCREEN.x + 2, Math.round(y), w, 1).fill({ color: 0xcfe6ff, alpha: 0.55 });
    }
    if (Math.floor(this.t / 0.53) % 2 === 0) {
      g.rect(SCREEN.x + 2, SCREEN.y + SCREEN.h - 2, 2, 2).fill({ color: 0xffffff, alpha: 0.9 });
    }
  }

  destroy(): void {
    this.container.destroy({ children: true });
  }
}
