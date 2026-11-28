// Enter while an input method is composing (Chinese pinyin, Japanese kana, Korean jamo) only commits the
// composition; it must never submit, save or pick. Browsers mark that key event `isComposing`. Safari/WebKit (the
// macOS webview) ends the composition first and then sends the committing Enter as keyCode 229 with `isComposing`
// false, in the same task as `compositionend`. A later Enter is the person's next key and sends, even when WebKit
// still reports 229 for it (a Korean syllable just committed). So an Enter with 229 alone is not composing: only one
// while a composition is open, or the single one right after it ended.

/** A composition is open in some field (compositionstart seen, compositionend not yet). */
let open = false;
/** A composition ended in this task: a 229 key event now is the one that committed it. */
let justEnded = false;

/** Follows compositions on `target` (the document: every field's composition events reach it). Returns its undo. */
export function watchComposition(target: EventTarget): () => void {
  const start = () => {
    open = true;
    justEnded = false;
  };
  const end = () => {
    open = false;
    justEnded = true;
    // the committing key event comes in this same task; any later one is the next key
    setTimeout(() => (justEnded = false), 0);
  };
  // a field that loses focus mid-composition may never send its compositionend
  const blur = () => (open = false);
  target.addEventListener("compositionstart", start, true);
  target.addEventListener("compositionend", end, true);
  target.addEventListener("focusout", blur, true);
  return () => {
    target.removeEventListener("compositionstart", start, true);
    target.removeEventListener("compositionend", end, true);
    target.removeEventListener("focusout", blur, true);
    open = false;
    justEnded = false;
  };
}

if (typeof document !== "undefined") watchComposition(document);

export function composing(e: { key?: string; nativeEvent?: { isComposing?: boolean }; isComposing?: boolean; keyCode?: number }): boolean {
  if (e.nativeEvent?.isComposing || e.isComposing) return true;
  if (e.keyCode !== 229) return false;
  // any other key the input method took (its "Process" key, a digit picking a candidate) stays the IME's
  if (e.key !== undefined && e.key !== "Enter") return true;
  return open || justEnded;
}

/** onKeyDown for a <form> (or one input): Enter that commits a composition does not submit it. */
export function holdImeEnter(e: { key: string; preventDefault(): void; nativeEvent?: { isComposing?: boolean }; keyCode?: number }): void {
  if (e.key === "Enter" && composing(e)) e.preventDefault();
}
