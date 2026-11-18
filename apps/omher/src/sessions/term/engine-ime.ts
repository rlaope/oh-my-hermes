// Text typed through an input method (Korean, Japanese, Chinese) into a terminal: what reaches the program, exactly
// once and in order. xterm's own handling loses or repeats text in two cases this takes over:
//
// - WebKit (the macOS window) with the 2-Set Korean input source sends no composition events. Each syllable arrives
//   as `insertText` (its first jamo) and is then rewritten in place with `insertReplacementText` edits, each followed by
//   a keyCode 229 keydown. xterm sends only the first jamo, and its keyCode 229 path re-reads the helper textarea and
//   sends all of it again (xterm.js#6284): "안녕" came out as "ㅇ안안ㄴ안녕". Here the syllable is held until it is
//   final (the next syllable starts, a key the input method does not take, or the terminal loses focus) and sent then.
// - A key pressed right after a composition ends (a fast Enter) cancels xterm's pending send of that composition
//   (xterm.js#6089): "한글⏎" came out as "글⏎". Here a composition's text is sent when it ends, from the event itself.
//
// While a composition or a held syllable is open it shows at the cursor in xterm's composition view. Keys the input
// method does not take go on to xterm as before (the program's own keys, shortcuts, Enter).
import type { Terminal } from "@xterm/xterm";

/** Hangul jamo, compatibility jamo, the extended jamo blocks and the syllables. */
const HANGUL = /[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7a3\ud7b0-\ud7ff]/;
/** Keys that never type: they must not end a held syllable. */
const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "AltGraph", "Fn", "OS"]);

export interface ImeOut {
  /** Text for the program. */
  send(text: string): void;
  /** What is being composed, shown at the cursor; null hides it. */
  show(text: string | null): void;
}

/** The rules, without a DOM: each handler says whether xterm must not see the event. */
export class ImeInput {
  private composing = false;
  private preedit = "";
  /** a composition whose text went out before its end arrived (a key ended it): its end sends nothing */
  private sentEarly = false;
  /** WebKit's Korean syllable, still being edited */
  private held: string | null = null;
  constructor(private out: ImeOut) {}

  /** Send the held syllable, if any. */
  flush(): void {
    if (this.held === null) return;
    const h = this.held;
    this.held = null;
    this.out.show(null);
    if (h) this.out.send(h);
  }

  compositionStart(): boolean {
    this.flush();
    this.composing = true;
    this.sentEarly = false;
    this.preedit = "";
    return true;
  }

  compositionUpdate(data: string): boolean {
    this.preedit = data;
    this.out.show(data || null);
    return true;
  }

  compositionEnd(data: string): boolean {
    this.composing = false;
    this.out.show(null);
    if (this.sentEarly) {
      this.sentEarly = false;
      return true;
    }
    if (data) this.out.send(data);
    return true;
  }

  /** An `input` (or `beforeinput`: pass `before`) event. True: xterm must not see it. Text that is not Korean and
   *  not composed stays xterm's (an emoji from the picker, a character a key typed that xterm did not cancel). */
  input(type: string, data: string | null, before = false): boolean {
    // composition text arrives with the composition's end
    if (this.composing || type === "insertCompositionText" || type === "deleteCompositionText" || type === "insertFromComposition") return true;
    const d = data ?? "";
    const korean = type === "insertText" && d.length === 1 && HANGUL.test(d);
    if (before) return korean || (type === "insertReplacementText" && this.held !== null);
    if (type === "insertReplacementText" && this.held !== null) {
      // WebKit editing the syllable being typed
      this.held = d;
      this.out.show(d || null);
      return true;
    }
    if (type === "deleteContentBackward" && this.held !== null) {
      // the input method took the whole syllable back before it was final
      this.held = null;
      this.out.show(null);
      return true;
    }
    this.flush();
    if (korean) {
      this.held = d;
      this.out.show(d);
      return true;
    }
    return false;
  }

  /** A keydown. True: xterm must not see it (the input method took the key, keyCode 229; its text comes as input). A
   *  real key pressed while a composition is open (Enter right after the last syllable) ends it: what was composed
   *  goes out first, then the key is xterm's. */
  keydown(e: { key: string; keyCode: number }): boolean {
    if (MODIFIERS.has(e.key)) return false;
    if (e.keyCode === 229) return true;
    if (this.composing) {
      // a key the input method let through while composing: what was composed goes out first
      this.composing = false;
      this.out.show(null);
      if (this.preedit) {
        this.sentEarly = true;
        this.out.send(this.preedit);
      }
    }
    this.flush();
    return false;
  }
}

/** Put the IME handling in front of xterm's for `term` (open, inside `host`). Returns what undoes it. */
export function attachIme(term: Terminal, host: HTMLElement): () => void {
  const view = () => host.querySelector<HTMLElement>(".composition-view");
  const show = (text: string | null) => {
    const v = view();
    if (!v) return;
    if (text === null) {
      v.classList.remove("active");
      v.textContent = "";
      return;
    }
    // at the cursor, in the terminal's font and colours
    const screen = host.querySelector<HTMLElement>(".xterm-screen");
    const b = term.buffer.active;
    const cw = screen && term.cols ? screen.clientWidth / term.cols : 0;
    const ch = screen && term.rows ? screen.clientHeight / term.rows : 0;
    const o = term.options;
    v.textContent = text;
    v.style.left = `${Math.min(b.cursorX, term.cols - 1) * cw}px`;
    v.style.top = `${b.cursorY * ch}px`;
    v.style.height = `${ch}px`;
    v.style.lineHeight = `${ch}px`;
    v.style.fontFamily = o.fontFamily ?? "";
    v.style.fontSize = `${o.fontSize}px`;
    v.style.color = o.theme?.foreground ?? "";
    v.style.background = o.theme?.background ?? "";
    v.style.textDecoration = "underline";
    v.classList.add("active");
  };
  const ime = new ImeInput({ send: (d) => term.input(d, true), show });
  const textarea = () => term.textarea;
  const mine = (e: Event) => e.target === textarea();
  const stop = (e: Event) => {
    e.stopImmediatePropagation();
    e.stopPropagation();
  };
  const on: [string, (e: Event) => void][] = [
    ["compositionstart", (e) => mine(e) && ime.compositionStart() && stop(e)],
    ["compositionupdate", (e) => mine(e) && ime.compositionUpdate((e as CompositionEvent).data ?? "") && stop(e)],
    ["compositionend", (e) => mine(e) && ime.compositionEnd((e as CompositionEvent).data ?? "") && stop(e)],
    ["beforeinput", (e) => mine(e) && ime.input((e as InputEvent).inputType, (e as InputEvent).data, true) && stop(e)],
    ["input", (e) => mine(e) && ime.input((e as InputEvent).inputType, (e as InputEvent).data) && stop(e)],
    [
      "keydown",
      (e) => {
        const k = e as KeyboardEvent;
        if (mine(e) && ime.keydown({ key: k.key, keyCode: k.keyCode })) stop(e);
      },
    ],
    ["focusout", (e) => mine(e) && ime.flush()],
  ];
  // capture on the terminal's own element: ahead of xterm's listeners on its textarea
  for (const [type, fn] of on) host.addEventListener(type, fn, true);
  return () => {
    for (const [type, fn] of on) host.removeEventListener(type, fn, true);
  };
}
