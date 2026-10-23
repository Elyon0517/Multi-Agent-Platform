import { AnimatedSprite, Container, Graphics, type Texture } from 'pixi.js';
export type Direction = 'down' | 'up' | 'right' | 'left';
export type AnimState = 'walk' | 'type' | 'read' | 'idle';

export class CharacterSprite {
  readonly container = new Container();
  private readonly image: AnimatedSprite;
  private readonly clipping = new Graphics();
  private mode = '';
  constructor(private readonly atlas: Texture[][]) {
    this.image = new AnimatedSprite([atlas[0][0]]);
    this.image.anchor.set(.5, 1);
    this.container.addChild(this.image, this.clipping);
    this.container.scale.set(1.08);
    this.setAnimation('idle', 'down');
  }
  setAnimation(state: AnimState, direction: Direction): void {
    const key = `${state}/${direction}`;
    if (key === this.mode) return;
    this.mode = key;
    const row = this.atlas[direction === 'up' ? 1 : direction === 'down' ? 0 : 2];
    const columns = state === 'idle' ? [0] : state === 'type' ? [3, 4] : state === 'read' ? [5, 6] : [0, 1, 2, 1];
    this.image.textures = columns.map(index => row[index] ?? row[0]);
    this.image.scale.x = direction === 'left' ? -1 : 1;
    this.image.animationSpeed = state === 'walk' ? .15 : .06;
    this.image.gotoAndPlay(0);
  }
  setSeatedCrop(pixels: number): void {
    this.image.mask = null; this.clipping.clear();
    if (pixels <= 0) return;
    const { width, height } = this.image.texture.frame;
    this.clipping.rect(-width / 2, -height, width, Math.max(0, height - pixels)).fill(0xffffff);
    this.image.mask = this.clipping;
  }
  setPosition(x: number, y: number): void { this.container.position.set(x, y); }
  setAlpha(value: number): void { this.container.alpha = Math.max(0, Math.min(1, value)); }
  destroy(): void { this.container.destroy({ children: true }); }
}
