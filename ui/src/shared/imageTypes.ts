const IMAGE_FORMATS = new Map([
  ['png', 'image/png'], ['jpg', 'image/jpeg'], ['jpeg', 'image/jpeg'], ['gif', 'image/gif'],
  ['webp', 'image/webp'], ['bmp', 'image/bmp'], ['ico', 'image/x-icon'], ['avif', 'image/avif'], ['svg', 'image/svg+xml'],
]);
export function extensionOf(path: string): string {
  if (typeof path !== 'string') return '';
  const basename = path.replace(/[?#].*$/, '').split('/').at(-1) ?? '';
  const match = /\.([^.]*)$/.exec(basename);
  return match ? match[1].toLowerCase() : '';
}
export function imageMimeForPath(path: string): string | null { return IMAGE_FORMATS.get(extensionOf(path)) ?? null; }
export function isImagePath(path: string): boolean { return IMAGE_FORMATS.has(extensionOf(path)); }
export function isSvgPath(path: string): boolean { return extensionOf(path) === 'svg'; }
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const power = bytes < 1024 ? 0 : bytes < 1048576 ? 1 : 2;
  return `${power ? (bytes / 1024 ** power).toFixed(1) : bytes} ${['B', 'KB', 'MB'][power]}`;
}
