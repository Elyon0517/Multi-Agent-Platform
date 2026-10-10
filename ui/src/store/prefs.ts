import type { ThemeId } from '@/scene/office/themeRegistry';

const KEY = 'agentlab.prefs.v1';

export interface Prefs {
  theme: ThemeId;
  order: string[];
  names: Record<string, string>;
  notes: Record<string, string>;
}

const DEFAULTS: Prefs = { theme: 'office', order: [], names: {}, notes: {} };

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Prefs>) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

export function savePrefs(p: Prefs): void {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* storage full or disabled */ }
}
