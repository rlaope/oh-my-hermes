// Enter while an input method is composing (Chinese pinyin, Japanese kana, Korean jamo) only commits the
// composition; it must never submit, save or pick. Browsers mark that key event `isComposing`, and Safari/WebKit
// (the macOS webview) sends the committing Enter as keyCode 229 after compositionend.
export function composing(e: { nativeEvent?: { isComposing?: boolean }; isComposing?: boolean; keyCode?: number }): boolean {
  return !!(e.nativeEvent?.isComposing || e.isComposing || e.keyCode === 229);
}

/** onKeyDown for a <form> (or one input): Enter that commits a composition does not submit it. */
export function holdImeEnter(e: { key: string; preventDefault(): void; nativeEvent?: { isComposing?: boolean }; keyCode?: number }): void {
  if (e.key === "Enter" && composing(e)) e.preventDefault();
}
