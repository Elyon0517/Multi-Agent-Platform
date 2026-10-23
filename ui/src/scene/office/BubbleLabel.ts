import { Container, Graphics, Text } from 'pixi.js';

// Both label styles share wrapping, placement and lifetime management.
export class BubbleLabel {
  readonly container = new Container();
  private readonly plate = new Graphics();
  private readonly text: Text;
  private remaining = Infinity;
  private opacity = 0;
  private target = 0;
  private lift = 0;
  private zoom = 1;
  private bounds = { w: Infinity, h: Infinity };
  private origin = { x: 0, y: 0 };
  constructor(private readonly light: boolean) {
    this.text = new Text({ text: '', style: { fontFamily: 'Inter, sans-serif', fontSize: 12,
      fill: light ? 0x3d2e4a : 0xfffdf5, wordWrap: true, wordWrapWidth: light ? 288 : 268, breakWords: true } });
    this.text.position.set(12, 6);
    this.container.addChild(this.plate, this.text);
    this.container.eventMode = 'none'; this.container.zIndex = 100000;
    this.container.visible = false;
  }
  protected display(value: string): void {
    this.text.text = Array.from(value).slice(0, 160).join('');
    this.plate.clear().roundRect(0, 0, this.text.width + 24, this.text.height + 12, 8)
      .fill(this.light ? 0xfffdf5 : 0x1a1320).stroke({ width: 2, color: 0x1a1320 });
    this.target = 1; this.remaining = Infinity; this.container.visible = true; this.place();
  }
  startLinger(): void { this.remaining = this.light ? 1.2 : 2; }
  hide(): void { this.target = 0; this.remaining = 0; }
  isHidden(): boolean { return !this.container.visible; }
  setZoom(value: number): void { this.zoom = Math.max(.01, value); this.place(); }
  setBounds(w: number, h: number): void { this.bounds = { w, h }; this.place(); }
  setLift(pixels: number): void { this.lift = pixels; this.place(); }
  setPosition(x: number, y: number): void { this.origin = { x, y }; this.place(); }
  getLayout(x: number, y: number): { x: number; y: number; w: number; h: number } | null {
    if (this.isHidden()) return null;
    const scale = this.scale(); const w = this.plate.width * scale, h = this.plate.height * scale;
    return { x: Math.max(0, Math.min(this.bounds.w - w, x - w / 2)), y: y - 38 - this.lift - h, w, h };
  }
  private scale(): number { return .5 * Math.max(1, 1 / this.zoom); }
  private place(): void {
    this.container.scale.set(this.scale());
    const layout = this.getLayout(this.origin.x, this.origin.y);
    if (layout) this.container.position.set(layout.x, Math.max(0, layout.y));
  }
  update(seconds: number): void {
    this.remaining -= seconds;
    if (this.remaining <= 0) this.target = 0;
    const step = seconds / (this.target ? .15 : .3);
    this.opacity = this.target ? Math.min(1, this.opacity + step) : Math.max(0, this.opacity - step);
    this.container.alpha = this.opacity;
    if (!this.target && !this.opacity) this.container.visible = false;
  }
  destroy(): void { this.container.destroy({ children: true }); }
}
