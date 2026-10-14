/** Default identity before customization. */
export const DEFAULT_GOD_NAME = 'Root';

/** Use the persisted name on respawn, falling back to the default. */
export function resolveGodName(persistedName: string | undefined | null): string {
  const trimmed = persistedName?.trim();
  return trimmed ? trimmed : DEFAULT_GOD_NAME;
}
