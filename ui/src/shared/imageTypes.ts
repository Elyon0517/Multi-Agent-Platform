/**
 * Image file detection — the ONE place that answers "is this path an image, and
 * what mime does it carry?".
 *
 * Shared on purpose. Three call sites need the same answer and they live on
 * opposite sides of the IPC boundary: the main process stamps a mime onto the
 * bytes it reads (`fs.readFileBinary`), the IDE decides whether a click opens
 * Monaco or the image preview, and the markdown renderer decides whether an
 * `<img src>` is worth resolving. If those three ever disagree, the failure is
 * silent and confusing — a file opens as a preview that then reports "unknown
 * image", or opens in Monaco as mojibake. Keeping the table here makes
 * disagreement impossible.
 *
 * Detection is BY EXTENSION, not by magic bytes. That is deliberate: the
 * renderer must decide how to open a file *before* it has any bytes, so a
 * content sniff isn't available at the moment the decision is made. The mime is
 * only ever used to label a `blob:` URL for the platform's own image decoder —
 * a mislabelled file simply fails to decode and shows the preview's error state,
 * it never becomes a script or a navigation.
 */

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

/**
 * Lower-cased extension of `p` without the dot, or '' when there is none.
 *
 * Strips a `?query` / `#hash` first: markdown authored by an agent routinely
 * carries cache-busting suffixes (`./shot.png?v=2`), and treating `png?v=2` as
 * the extension would silently drop exactly the screenshots we want to render.
 * Only the LAST path segment is considered, so a dotted directory name
 * (`v1.2/report`) can never masquerade as an extension.
 */
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

/**
 * SVG is the one image format that is ALSO source code people edit by hand.
 * Callers use this to keep a "view source" escape hatch: an .svg opens as a
 * picture (that's what you want 95% of the time) but must never become
 * un-editable, which is what routing every image straight to a read-only
 * preview would have done.
 */
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
