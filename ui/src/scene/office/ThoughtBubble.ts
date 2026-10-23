import { BubbleLabel } from './BubbleLabel';
export class ThoughtBubble extends BubbleLabel {
  constructor() { super(true); }
  show(message: string, tool?: string): void { this.display(tool ? `${tool}: ${message}` : message); }
}
