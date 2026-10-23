import { Container, Graphics, Text, type Texture } from 'pixi.js';
import { CharacterSprite, type Direction, type AnimState } from './CharacterSprite';
import { ThoughtBubble } from './ThoughtBubble';
import { findPath } from './pathfinding';
import type { TiledMapRenderer, Point } from './TiledMapRenderer';
export type CharacterAnimation = AnimState;
export type StatusGlyph = 'none' | 'blocked' | 'success' | 'compacting' | 'looping';
interface CharacterOptions {
  agentId: string; displayName: string; mapRenderer: TiledMapRenderer; frames: Texture[][];
  seatTile: Point; spawnTile?: Point; glowColor: number; seatDirection?: Direction; onClick?: (id: string) => void;
}
export class Character {
  readonly agentId: string;
  readonly sprite: CharacterSprite;
  isVisible = false;
  private readonly bubble = new ThoughtBubble();
  private readonly label = new Container();
  private readonly labelText: Text;
  private readonly labelPlate = new Graphics();
  private readonly halo = new Graphics();
  private readonly symbol = new Text({ text: '', style: { fontFamily: 'monospace', fontSize: 10, fill: 0xdcab3c } });
  private readonly position: Point;
  private path: Point[] = [];
  private arrival: (() => void) | undefined;
  private seated = false;
  private animation: AnimState = 'idle';
  private direction: Direction = 'down';
  private opacity = 0;
  private fadingOut = false;
  private idleDelay = 0;
  constructor(private readonly options: CharacterOptions) {
    this.agentId = options.agentId;
    this.sprite = new CharacterSprite(options.frames);
    const spawn = options.spawnTile ?? options.seatTile, ts = options.mapRenderer.tileSize;
    this.position = { x: (spawn.x + .5) * ts, y: (spawn.y + 1) * ts };
    this.labelText = new Text({ text: options.displayName, style: { fontFamily: 'Inter, sans-serif', fontSize: 6, fill: 0xfffdf5 } });
    this.labelText.anchor.set(.5, 0); this.labelText.y = 1;
    this.label.addChild(this.labelPlate, this.labelText); this.label.zIndex = 50000;
    this.sprite.container.addChildAt(this.halo, 0);
    this.symbol.position.set(7, -38); this.sprite.container.addChild(this.symbol);
    this.sprite.container.eventMode = 'static'; this.sprite.container.cursor = 'pointer';
    this.sprite.container.on('pointertap', event => { event.stopPropagation(); options.onClick?.(options.agentId); });
    this.setName(options.displayName);
  }
  setName(name: string): void {
    if (this.labelText.text === name && this.labelPlate.width) return;
    this.labelText.text = name;
    this.labelPlate.clear().roundRect(-this.labelText.width / 2 - 2, 0, this.labelText.width + 4, 9, 2)
      .fill({ color: 0x1a1320, alpha: .82 });
  }
  show(parent: Container): void {
    parent.addChild(this.sprite.container, this.label, this.bubble.container);
    this.isVisible = true; this.fadingOut = false;
  }
  hide(): void { this.fadingOut = true; this.bubble.hide(); }
  getPixelPosition(): Point { return { ...this.position }; }
  getTilePosition(): Point {
    const ts = this.options.mapRenderer.tileSize;
    return { x: Math.floor(this.position.x / ts), y: Math.round(this.position.y / ts) - 1 };
  }
  getDeskTile(): Point { return { ...this.options.seatTile }; }
  getAnimation(): AnimState { return this.animation; }
  walkToAndThen(tile: Point, done: () => void): void {
    const route = findPath(this.options.mapRenderer, this.getTilePosition(), tile);
    this.seated = false; this.sprite.setSeatedCrop(0); this.halo.visible = false;
    this.arrival = undefined;
    if (route === null) return;
    this.path = route; this.animation = route.length ? 'walk' : 'idle'; this.arrival = done;
    if (!route.length) { this.arrival = undefined; done(); }
  }
  walkToTile(tile: Point): void { this.walkToAndThen(tile, () => undefined); }
  sitAtDesk(working: boolean): void {
    const sit = () => {
      this.seated = true; this.animation = working ? 'type' : 'idle';
      this.direction = this.options.seatDirection ?? 'up'; this.sprite.setSeatedCrop(2);
      this.halo.clear().ellipse(0, -2, 12, 5).fill({ color: this.options.glowColor, alpha: .2 });
      this.halo.visible = working;
    };
    this.walkToAndThen(this.options.seatTile, sit);
  }
  setIdle(): void { this.path = []; this.arrival = undefined; this.animation = 'idle'; this.halo.visible = false; }
  startWandering(): void { this.setIdle(); this.idleDelay = 30; }
  isSittingAtDesk(): boolean { return this.seated && !this.path.length; }
  setStatusGlyph(status: StatusGlyph): void {
    this.symbol.text = { none: '', blocked: '!', success: '✓', compacting: '▣', looping: '↻' }[status];
  }
  setBaseAlpha(alpha: number): void { this.opacity = Math.min(this.opacity, alpha); }
  showThought(text: string, tool?: string): void { this.bubble.show(text, tool); }
  hideThought(): void { this.bubble.hide(); }
  setBubbleZoom(scale: number): void { this.bubble.setZoom(scale); }
  getThoughtLayout() { return this.bubble.getLayout(this.position.x, this.position.y); }
  setThoughtLift(pixels: number): void { this.bubble.setLift(pixels); }
  update(seconds: number): void {
    const ts = this.options.mapRenderer.tileSize;
    let travel = Math.max(0, seconds) * 320;
    while (travel && this.path.length) {
      const next = this.path[0], target = { x: (next.x + .5) * ts, y: (next.y + 1) * ts };
      const dx = target.x - this.position.x, dy = target.y - this.position.y, distance = Math.hypot(dx, dy);
      if (distance) this.direction = Math.abs(dx) > Math.abs(dy) ? dx > 0 ? 'right' : 'left' : dy > 0 ? 'down' : 'up';
      const step = Math.min(distance, travel);
      if (distance) { this.position.x += dx * step / distance; this.position.y += dy * step / distance; }
      travel -= step;
      if (distance <= step) this.path.shift(); else break;
      if (!this.path.length) { this.animation = 'idle'; const done = this.arrival; this.arrival = undefined; done?.(); }
    }
    if (this.idleDelay > 0 && !this.path.length) {
      this.idleDelay -= seconds;
      if (this.idleDelay <= 0) this.sitAtDesk(false);
    }
    this.opacity = Math.max(0, Math.min(1, this.opacity + seconds * (this.fadingOut ? -2 : 4)));
    if (this.fadingOut && !this.opacity) this.isVisible = false;
    this.sprite.setPosition(this.position.x, this.position.y + (this.seated ? 5 : 0));
    this.sprite.container.zIndex = this.position.y; this.sprite.setAlpha(this.opacity);
    this.sprite.setAnimation(this.animation, this.direction);
    this.label.position.set(this.position.x, this.position.y + 1); this.label.alpha = this.opacity;
    this.bubble.setPosition(this.position.x, this.position.y); this.bubble.update(seconds);
  }
  destroy(): void { this.bubble.destroy(); this.label.destroy({ children: true }); this.sprite.destroy(); }
}
