/** Suppress actions during IME composition. Read nativeEvent for React events;
 * keyCode 229 covers confirmation keydowns arriving after compositionend. */

/** The structural shape we need from either a React synthetic event or a raw
 *  DOM `KeyboardEvent`. Deliberately all-optional: a hand-built test double or a
 *  partially-populated event must degrade to "not composing", never throw. */
export interface ComposingKeyEvent {
  isComposing?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean; keyCode?: number };
}

/** Whether the keydown belongs to IME composition. */
export function isComposingKey(e: ComposingKeyEvent | null | undefined): boolean {
  if (!e) return false;
  // Prefer the native event: React's SyntheticKeyboardEvent drops `isComposing`.
  const src = e.nativeEvent ?? e;
  return src.isComposing === true || src.keyCode === 229;
}
