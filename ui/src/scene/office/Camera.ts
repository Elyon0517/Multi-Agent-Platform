import type { Container } from 'pixi.js';

// Camera state is a world-space center, scale and an optional transient offset.
export class Camera {
  private world = { w: 640, h: 480 };
  private viewport = { w: 960, h: 800 };
  private position = { x: 320, y: 240, z: 1 };
  private destination = { ...this.position };
  private automatic = true;
  private nudge: { x: number; y: number; remaining: number; duration: number } | null = null;
  constructor(private readonly layer: Container) {}
  private fitScale(): number { return Math.min(this.viewport.w / this.world.w, this.viewport.h / this.world.h); }
  setMapSize(w: number, h: number): void {
    this.world = { w: Math.max(1, w), h: Math.max(1, h) };
    if (this.automatic) this.fitToScreen();
  }
  setViewSize(w: number, h: number): void {
    this.viewport = { w: Math.max(1, w), h: Math.max(1, h) };
    if (this.automatic) this.fitToScreen();
  }
  fitToScreen(): void {
    this.automatic = true; this.nudge = null;
    this.destination = { x: this.world.w / 2, y: this.world.h / 2, z: this.fitScale() };
  }
  focusOn(x: number, y: number, zoom = this.position.z): void {
    this.automatic = false; this.nudge = null;
    this.destination = { x, y, z: Math.max(this.fitScale(), Math.min(4, zoom)) };
  }
  nudgeToward(x: number, y: number, milliseconds = 1200): void {
    if (!this.automatic) return;
    const duration = Math.max(0.001, milliseconds / 1000);
    this.nudge = { x: (x - this.destination.x) * .4, y: (y - this.destination.y) * .4, duration, remaining: duration };
  }
  update(seconds: number): void {
    const blend = -Math.expm1(-5 * Math.max(0, seconds));
    for (const axis of ['x', 'y', 'z'] as const) this.position[axis] +=
      (this.destination[axis] - this.position[axis]) * blend;
    let dx = 0, dy = 0;
    if (this.nudge) {
      this.nudge.remaining = Math.max(0, this.nudge.remaining - seconds);
      const weight = this.nudge.remaining / this.nudge.duration;
      dx = this.nudge.x * weight; dy = this.nudge.y * weight;
      if (!weight) this.nudge = null;
    }
    const z = this.position.z;
    const clamp = (center: number, viewport: number, extent: number) => extent * z <= viewport
      ? (viewport - extent * z) / 2 : Math.max(viewport - extent * z, Math.min(0, viewport / 2 - center * z));
    this.layer.scale.set(z);
    this.layer.position.set(clamp(this.position.x + dx, this.viewport.w, this.world.w),
      clamp(this.position.y + dy, this.viewport.h, this.world.h));
  }
}
