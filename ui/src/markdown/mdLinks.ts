import { isImagePath } from '@/shared/imageTypes';
const scheme = (link: string) => /^[a-z][a-z\d+.-]*:/i.test(link);
export function resolveRel(base: string | undefined, link: string): string {
  const segments = (base ?? '').split('/'); segments.pop();
  for (const part of link.split('/')) {
    if (part === '..') segments.pop();
    else if (part && part !== '.') segments.push(part);
  }
  return segments.join('/');
}
export function isExternal(link: string): boolean { return /^(?:https?:|mailto:)/i.test(link); }
export function isRelativeMd(link: string): boolean { return !scheme(link) && /\.(?:md|markdown)(?:#.*)?$/i.test(link); }
export function resolveLocalImageRel(base: string | undefined, value: string | undefined): string | null {
  const link = value?.trim();
  if (!link || scheme(link) || link.startsWith('//') || !isImagePath(link)) return null;
  return resolveRel(link.startsWith('/') ? undefined : base, link.replace(/[?#].*$/, '')) || null;
}
