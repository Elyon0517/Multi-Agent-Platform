import { Container, Graphics, Sprite } from 'pixi.js';
import type { TiledMapRenderer, Point } from './TiledMapRenderer';
import type { MonitorConfig } from './themeRegistry';
export const MONITOR_OFF_TOPLEFT_GID = 9;
export class DeskScreen {
  readonly container = new Container();
  private readonly log = new Graphics();
  private clock = 0;
  constructor(map: TiledMapRenderer, at: Point, config?: MonitorConfig) {
    const frames = config?.onGids ?? [[11,0,0],[12,1,0],[19,0,1],[20,1,1]];
    for (const [gid, x, y] of frames) {
      const texture = map.textureForGid(gid);
      if (texture) { const tile = new Sprite(texture); tile.position.set(x * map.tileSize, y * map.tileSize); this.container.addChild(tile); }
    }
    this.container.addChild(this.log);
    this.container.position.set(at.x * map.tileSize, at.y * map.tileSize);
    this.container.zIndex = (at.y + 2) * map.tileSize - 1;
    this.container.eventMode = 'none'; this.setOn(false);
  }
  setOn(visible: boolean): void { this.container.visible = visible; if (!visible) { this.clock = 0; this.log.clear(); } }
  update(seconds: number): void {
    if (!this.container.visible) return;
    this.clock += seconds; this.log.clear();
    for (const offset of [0, 6]) this.log.rect(5, 5 + (offset + Math.floor(this.clock * 3)) % 12, 9 + offset, 1)
      .fill({ color: 0xcfe6ff, alpha: .55 });
    if (this.clock % 1 < .5) this.log.rect(5, 15, 2, 2).fill(0xffffff);
  }
  destroy(): void { this.container.destroy({ children: true }); }
}
