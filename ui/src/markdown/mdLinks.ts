/** Link and workspace path resolution for markdown previews. */
import { isImagePath } from '@shared/imageTypes';

/** Resolve href relative to baseRel, clamping parent traversal at the workspace root.
 * File reads must still enforce containment independently. */
export function resolveRel(baseRel: string | undefined, href: string): string {
  const baseDir = (baseRel ?? '').split('/').slice(0, -1);
  const parts = [...baseDir];
  for (const seg of href.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') { parts.pop(); continue; }
    parts.push(seg);
  }
  return parts.join('/');
}

export function isExternal(href: string): boolean {
  return /^(https?:|mailto:)/i.test(href);
}

/** True when `href` carries any URI scheme (http:, data:, file:, javascript:…). */
function hasScheme(href: string): boolean {
  return /^[a-z][a-z0-9+.-]*:/i.test(href);
}

export function isRelativeMd(href: string): boolean {
  return !hasScheme(href) && /\.(md|markdown)(#.*)?$/i.test(href);
}

/** Resolve local image paths; reject URI schemes and unsupported extensions.
 * Leading slashes refer to the workspace root, not the host filesystem. */
export function resolveLocalImageRel(baseRel: string | undefined, src: string | undefined): string | null {
  if (typeof src !== 'string') return null;
  const raw = src.trim();
  if (!raw) return null;
  if (hasScheme(raw)) return null;
  if (!isImagePath(raw)) return null;
  // Strip the query/hash before resolving — they are cache-busters, not path.
  const clean = raw.split('#')[0].split('?')[0];
  const rooted = clean.startsWith('/');
  const rel = resolveRel(rooted ? undefined : baseRel, clean);
  return rel || null;
}
