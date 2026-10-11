/** Per-browser layout choices: sidebar, console width and the office monitor. Storage may be
 *  unavailable (private windows, blocked site data), so every access falls back to defaults. */
export interface LayoutPrefs {
  sidebarCollapsed: boolean;
  consoleWidth: number;
  officeMinimized: boolean;
}

const KEY = 'agentlab.layout';
export const DEFAULT_CONSOLE_WIDTH = 460;
export const MIN_CONSOLE_WIDTH = 320;
/** The office keeps at least this much room unless it is minimized. */
export const MIN_MAIN_WIDTH = 360;
const DEFAULTS: LayoutPrefs = { sidebarCollapsed: false, consoleWidth: DEFAULT_CONSOLE_WIDTH, officeMinimized: false };

export function loadLayout(): LayoutPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<LayoutPrefs>) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

export function saveLayout(prefs: LayoutPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* layout still works for this session */
  }
}
