import type { CSSProperties, ReactNode } from 'react';
export type IconName = 'gear' | 'plus' | 'x' | 'check' | 'arrow-right' | 'pause' | 'play' | 'bell' | 'folder' |
  'terminal' | 'code' | 'web' | 'mcp' | 'sparkle' | 'expand' | 'minimize' | 'clock' | 'mic' | 'ledger' | 'info' |
  'sidebar' | 'image' | 'edit' | 'git' | 'trash';
export interface IconProps { name: IconName; size?: number; style?: CSSProperties; }
// All glyphs are constructed here from primitive strokes on a 16-pixel grid.
const lines: Partial<Record<IconName, string>> = {
  plus: 'M8 2V14M2 8H14', x: 'M3 3L13 13M13 3L3 13', check: 'M2 8L6 12L14 3',
  'arrow-right': 'M2 8H14L9 3M14 8L9 13', pause: 'M5 3V13M11 3V13', play: 'M4 2L14 8L4 14Z',
  code: 'M5 3L1 8L5 13M11 3L15 8L11 13', terminal: 'M2 2H14V14H2ZM4 5L7 8L4 11M9 11H12',
  folder: 'M1 4H6L8 6H15V13H1ZM1 4V2H6L8 4H14V6',
  ledger: 'M3 1H13V15H3ZM5 5H11M5 8H11M5 11H9',
  sidebar: 'M1 3H15V13H1ZM6 3V13M3 6H4M3 9H4',
  expand: 'M1 6V1H6M10 1H15V6M15 10V15H10M6 15H1V10',
  minimize: 'M6 1V6H1M10 1V6H15M15 10H10V15M1 10H6V15',
  edit: 'M3 11L11 3L14 6L6 14H3ZM10 4L13 7M2 2H7M2 2V14H14V10',
  image: 'M1 2H15V14H1ZM2 12L6 8L9 11L12 7L15 10M4 5H6',
  trash: 'M2 4H14M5 4V2H11V4M4 6L5 14H11L12 6M7 6V12M9 6V12',
  mic: 'M6 2H10V9H6ZM3 7V9L5 12H11L13 9V7M8 12V15M5 15H11',
  sparkle: 'M8 1L10 6L15 8L10 10L8 15L6 10L1 8L6 6Z',
  mcp: 'M4 4H12V12H4ZM6 1V4M10 1V4M6 12V15M10 12V15M1 6H4M1 10H4M12 6H15M12 10H15',
  git: 'M5 4V12M5 8H8L11 5V4', bell: 'M3 12H13L11 9V5L9 3H7L5 5V9ZM7 14H9',
};
function geometry(name: IconName): ReactNode {
  if (name === 'gear') return <><path d="M5 2H11L14 5V11L11 14H5L2 11V5ZM8 1V3M8 13V15M1 8H3M13 8H15" /><circle cx="8" cy="8" r="2" /></>;
  if (name === 'clock') return <><circle cx="8" cy="8" r="6" /><path d="M8 4V8L11 10" /></>;
  if (name === 'info') return <><circle cx="8" cy="8" r="6" /><path d="M8 7V12M8 4V5" /></>;
  if (name === 'web') return <><circle cx="8" cy="8" r="6" /><ellipse cx="8" cy="8" rx="3" ry="6" /><path d="M2 6H14M2 10H14" /></>;
  if (name === 'git') return <><path d={lines.git} /><circle cx="5" cy="3" r="2" /><circle cx="5" cy="13" r="2" /><circle cx="11" cy="3" r="2" /></>;
  return <path d={lines[name]} />;
}
export function Icon({ name, size = 1, style }: IconProps) {
  return <svg aria-hidden="true" viewBox="0 0 16 16" width={16 * size} height={16 * size}
    style={{ display: 'inline-block', ...style }} fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinejoin="miter" shapeRendering="crispEdges">{geometry(name)}</svg>;
}
