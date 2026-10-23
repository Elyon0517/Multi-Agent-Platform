import { BubbleLabel } from './BubbleLabel';
export function toolIcon(name: string): string {
  const label = name.toLowerCase();
  if (/read|glob|grep|search/.test(label)) return '?';
  if (/write|edit|patch/.test(label)) return '+';
  if (/bash|shell|terminal/.test(label)) return '>';
  if (/web|fetch/.test(label)) return '@';
  return '*';
}
export class ToolBubble extends BubbleLabel {
  constructor() { super(false); }
  show(tool: string, target: string): void { this.display(`${toolIcon(tool)} ${tool}${target ? ` ${target}` : ''}`); }
  showText(value: string): void { this.display(value); }
}
