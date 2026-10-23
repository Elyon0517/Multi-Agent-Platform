export interface ComposingKeyEvent {
  isComposing?: boolean; keyCode?: number; nativeEvent?: { isComposing?: boolean; keyCode?: number };
}
export function isComposingKey(event: ComposingKeyEvent | null | undefined): boolean {
  const keyboard = event?.nativeEvent || event;
  return Boolean(keyboard && (keyboard.keyCode === 229 || keyboard.isComposing));
}
