/** Shared image MIME lookup by extension, available before file bytes are loaded. */

/** Extension (lower-case, no dot) → mime type. */
const MIME_BY_EXT: Readonly<Record<string, string>> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  bmp: 'image/bmp',
  ico: 'image/x-icon',
  avif: 'image/avif',
  svg: 'image/svg+xml'
};

/** Extract the final path segment's extension, ignoring query and hash suffixes. */
export function extensionOf(p: string): string {
  if (typeof p !== 'string') return '';
  const clean = p.split('#')[0].split('?')[0];
  const base = clean.split('/').pop() ?? '';
  const dot = base.lastIndexOf('.');
  if (dot < 0 || dot === base.length - 1) return '';
  return base.slice(dot + 1).toLowerCase();
}

/** The image mime for `p`, or null when the extension isn't a known image. */
export function imageMimeForPath(p: string): string | null {
  return MIME_BY_EXT[extensionOf(p)] ?? null;
}

/** True when `p` names a raster or vector image we can render. */
export function isImagePath(p: string): boolean {
  return imageMimeForPath(p) !== null;
}

/** SVG previews also support editing their source. */
export function isSvgPath(p: string): boolean {
  return extensionOf(p) === 'svg';
}

/** Human byte size for a status line: "864 B", "1.4 MB". */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
