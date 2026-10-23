import type { TiledMap } from './TiledMapRenderer';
import { getTheme, STUDIO_THEME, type ThemeId, type ThemeConfig } from './themeRegistry';
export function resolveThemeMap(theme: ThemeConfig): TiledMap {
  const data = JSON.parse(theme.mapRaw) as TiledMap;
  if (![data.width, data.height, data.tilewidth, data.tileheight].every(n => Number.isInteger(n) && n > 0) ||
    !Array.isArray(data.layers) || !Array.isArray(data.tilesets)) throw new Error(`Invalid workspace map: ${theme.id}`);
  const tilesets = theme.tilesets.map((entry, index) => {
    if (entry.embedded) {
      if (!data.tilesets[index]) throw new Error('Missing embedded atlas');
      return data.tilesets[index];
    }
    const { url: _url, embedded: _embedded, ...metadata } = entry;
    return metadata as TiledMap['tilesets'][number];
  });
  return { ...data, tilesets };
}
export function themeTilesetUrls(theme: ThemeConfig): string[] { return Array.from(theme.tilesets, entry => entry.url); }
export async function loadTheme(id: ThemeId): Promise<ThemeConfig> {
  const requested = getTheme(id);
  try { resolveThemeMap(requested); return requested; }
  catch { resolveThemeMap(STUDIO_THEME); return STUDIO_THEME; }
}
