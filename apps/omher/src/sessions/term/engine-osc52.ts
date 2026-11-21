// OSC 52: a program in the terminal puts text on the clipboard (tmux and Neovim yanks, a copy over SSH), as Ghostty,
// kitty, WezTerm and Windows Terminal allow. Copy only: a query (`?`) is never answered, so no program reads the
// clipboard (Neovim's OSC 52 paste then waits and gives up, as with Windows Terminal). Settings › Terminal › Programs
// may copy turns it off. Only the decoded text goes to the clipboard, at most OSC52_MAX_CHARS of it; it is not shown,
// kept or sent anywhere else.
//
// A copy counts only as the answer to the person: the terminal must have the keyboard, and they must have pressed a
// key or clicked in the page within OSC52_ACTIVE_MS (a yank answers its key at once). omher holds that itself, so it is
// the same on every webview (WKWebView alone also refuses after a few seconds: 3 s yes, 5.5 s no, measured under
// Tauri's scheme). A program writing the clipboard from a hidden or unfocused terminal, or with nobody at the keys, is
// refused, and a terminal that shows says so for a moment instead of failing unseen. Text holding control characters
// (other than tab and line breaks) is dropped: a pasted ESC or Ctrl-O would act in a shell without bracketed paste.
import type { Terminal } from "@xterm/xterm";
import "./engine-osc52.css";
import { t } from "../../i18n";
import { readTermSettings } from "./settings";

/** The most text one OSC 52 puts on the clipboard, in UTF-16 units (a longer one is dropped whole, not cut). */
export const OSC52_MAX_CHARS = 1_000_000;
/** How long after the person's last key or click a program's copy is taken. */
export const OSC52_ACTIVE_MS = 3000;

/** The text an OSC 52 payload (`<targets>;<base64>`) asks to copy, or null: a query, an empty or malformed payload,
 *  text that is not UTF-8 or holds control characters, or more than OSC52_MAX_CHARS. The targets (c, p, q, s, 0-7)
 *  all mean the one clipboard. */
export function parseOsc52(data: string): string | null {
  const semi = data.indexOf(";");
  if (semi < 0) return null;
  const targets = data.slice(0, semi);
  const b64 = data.slice(semi + 1).replace(/\s+/g, "");
  if (!/^[cpqs0-7]*$/.test(targets) || !b64 || b64 === "?") return null;
  // at most 3 UTF-8 bytes per UTF-16 unit, 4 base64 characters per 3 bytes
  if (b64.length > 4 * OSC52_MAX_CHARS + 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(b64)) return null;
  let bin: string;
  try {
    bin = atob(b64);
  } catch {
    return null;
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
  } catch {
    return null;
  }
  // eslint-disable-next-line no-control-regex
  if (!text || text.length > OSC52_MAX_CHARS || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/.test(text)) return null;
  return text;
}

/** When the person last pressed a key or clicked anywhere in the page. */
let lastActive = -Infinity;
let watching = false;
function watchActivity(): void {
  if (watching || typeof window === "undefined") return;
  watching = true;
  const mark = () => (lastActive = performance.now());
  addEventListener("keydown", mark, true);
  addEventListener("pointerdown", mark, true);
}

/** Does a copy now answer the person? `focused`: the terminal has the keyboard. */
export const osc52Allowed = (focused: boolean, now: number, last: number): boolean => focused && now - last <= OSC52_ACTIVE_MS;

/** How long the "could not copy" note stays. */
const NOTE_MS = 2600;

/** Hear OSC 52 in `term`, whose element is inside `host`. Returns what stops it. */
export function attachOsc52(term: Terminal, host: HTMLElement): () => void {
  watchActivity();
  let off = false;
  let note: HTMLElement | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const refused = () => {
    if (off) return;
    // a terminal out of sight has no box to say it in
    const box = host.closest<HTMLElement>(".term-wrap");
    if (!box) return;
    if (!note) {
      note = document.createElement("div");
      note.className = "osc52-note";
      note.setAttribute("role", "status");
      note.dataset.testid = "term-osc52-refused";
    }
    note.textContent = t("term.osc52Refused");
    box.appendChild(note);
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => note?.remove(), NOTE_MS);
  };
  const h = term.parser.registerOscHandler(52, (data) => {
    if (!readTermSettings().osc52) return true;
    const text = parseOsc52(data);
    if (text === null) return true;
    const focused = !!term.textarea && term.textarea === document.activeElement && document.hasFocus();
    if (!osc52Allowed(focused, performance.now(), lastActive)) {
      refused();
      return true;
    }
    void navigator.clipboard?.writeText(text).catch((e: unknown) => {
      if ((e as { name?: string } | null)?.name === "NotAllowedError") refused();
    });
    return true;
  });
  return () => {
    off = true;
    h.dispose();
    if (timer) clearTimeout(timer);
    note?.remove();
  };
}
