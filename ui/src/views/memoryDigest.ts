import type { MemoryItem } from '@/api/client';

export function memoryDigest(items: MemoryItem[]): string {
  return items.map((i) => `## ${i.source || i.kind}\n${i.text}`).join('\n\n');
}
