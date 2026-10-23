import { Container, Graphics } from 'pixi.js';
export type MessageAct = 'request' | 'inform' | 'propose' | 'query' | 'agree' | 'refuse' | 'done';
interface Location { x: number; y: number; }
export class MessageEnvelope {
  readonly container = new Container();
  private readonly letter = new Graphics();
  private readonly ripple = new Graphics();
  private age = 0;
  private readonly duration: number;
  constructor(private readonly from: Location, private readonly to: Location, act: MessageAct, human: boolean) {
    const tint = human || act === 'refuse' ? 0xd96a62 : act === 'done' || act === 'agree' ? 0x5ca97a :
      act === 'query' ? 0x9482d3 : act === 'propose' ? 0xdcab3c : act === 'request' ? 0x4f9faf : 0xf4e9c7;
    this.duration = Math.max(.8, Math.min(2, Math.hypot(to.x - from.x, to.y - from.y) / 230));
    this.letter.rect(-7, -5, 14, 10).fill(tint).stroke({ color: 0x1a1320, width: 1 });
    this.letter.moveTo(-6, -4).lineTo(0, 1).lineTo(6, -4).stroke({ color: 0x1a1320, width: 1 });
    this.container.addChild(this.letter, this.ripple);
    this.container.zIndex = 1000000; this.container.eventMode = 'none';
    this.update(0);
  }
  update(seconds: number): boolean {
    this.age += Math.max(0, seconds);
    const progress = Math.min(1, this.age / this.duration);
    const t = progress * progress * (3 - 2 * progress);
    this.container.position.set(this.from.x * (1 - t) + this.to.x * t,
      this.from.y * (1 - t) + this.to.y * t - 22 - 152 * t * (1 - t));
    this.letter.visible = progress < 1;
    this.container.alpha = Math.min(1, this.age / .14);
    if (progress === 1) {
      const arrival = (this.age - this.duration) / .34;
      this.ripple.clear().circle(0, 0, 3 + 12 * Math.min(1, arrival)).stroke({ color: 0xdcab3c, width: 2 });
      this.container.alpha = Math.max(0, 1 - arrival);
      return arrival >= 1;
    }
    return false;
  }
  destroy(): void { this.container.destroy({ children: true }); }
}
