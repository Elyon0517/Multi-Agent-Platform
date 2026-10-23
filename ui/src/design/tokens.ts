import appearance from './appearance.json';
export type AccentColorName = 'coral' | 'mint' | 'sky' | 'lemon' | 'lilac' | 'peach';
// These values are the visual compatibility contract for the current console.
// Generation keeps the numeric/color specification separate from the CSS implementation.
export function themeCss(): string {
  return Object.entries(appearance).map(([mode, values]) => {
    const selector = mode === 'default' ? ':root' : `:root[data-cth-theme="${mode}"]`;
    return `${selector}{${Object.entries(values).map(([key, value]) => `--cth-${key}:${value}`).join(';')}}`;
  }).join('\n');
}
export function installThemeTokens(document: Document): void {
  let stylesheet = document.getElementById('agentlab-appearance');
  if (!stylesheet) { stylesheet = document.createElement('style'); stylesheet.id = 'agentlab-appearance'; document.head.appendChild(stylesheet); }
  stylesheet.textContent = themeCss();
}
