import type { ThemeId } from '@/scene/office/themeRegistry';

const KEY = 'agentlab.prefs.v1';

export interface Prefs {
  theme: ThemeId;
  order: string[];
  names: Record<string, string>;
  notes: Record<string, string>;
}

const DEFAULTS: Prefs = { theme: 'studio', order: [], names: {}, notes: {} };

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const saved = JSON.parse(raw) as Partial<Prefs>;
    // Retired or unknown themes migrate to the original default. Keep user names/order.
    const theme = saved.theme === 'atrium' ? 'atrium' : 'studio';
    return { ...DEFAULTS, ...saved, theme };
  } catch {
    return DEFAULTS;
  }
}

export function savePrefs(p: Prefs): void {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* storage full or disabled */ }
}
