export const DEFAULT_GOD_NAME = 'Root';
export function resolveGodName(value: string | null | undefined): string {
  return value?.trim() || DEFAULT_GOD_NAME;
}
