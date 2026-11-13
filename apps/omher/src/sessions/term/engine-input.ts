// What a terminal does with the person's keyboard and mouse beyond xterm's own: the find shortcut, and the two
// clipboard settings (both off unless the person turned them on in Settings > Terminal). Settings are read when the
// event happens, so a switch applies to terminals that are already open.
//
// Find shortcut: Cmd+F on macOS. On Windows and Linux Ctrl+F opens find too, except while a full-screen program
// (the alternate screen: vim, less, htop) is showing: there Ctrl+F is the program's (page down) and the alternate
// screen has no scrollback to search anyway. Ctrl+Shift+F opens find everywhere, so the bar is always reachable.
import type { Terminal } from "@xterm/xterm";
import { isMacPlatform } from "./engine-links";
import { readTermSettings } from "./settings";

type KeyLike = { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean };

/** `f` on a Latin layout; on a non-Latin one (Korean, Japanese, Russian...) the key that stands where F does. */
const isF = (e: Pick<KeyLike, "key" | "code">) => e.key.toLowerCase() === "f" || (!/^[a-z]$/i.test(e.key) && e.code === "KeyF");

/** Does this key press ask for find? `altScreen`: a full-screen program is showing. */
export function isFindKey(e: KeyLike, mac: boolean, altScreen: boolean): boolean {
  if (!isF(e) || e.altKey) return false;
  if (mac) return e.metaKey && !e.ctrlKey && !e.shiftKey;
  if (!e.ctrlKey || e.metaKey) return false;
  return e.shiftKey || !altScreen;
}

/** Keyboard and mouse handling for one terminal; `onFind` runs when the person asks for find. Returns what undoes it. */
export function attachInput(term: Terminal, host: HTMLElement, onFind: () => void): () => void {
  const mac = isMacPlatform();
  // find: xterm asks first; `false` keeps the key from the program
  term.attachCustomKeyEventHandler((e) => {
    if (!isFindKey(e, mac, term.buffer.active.type === "alternate")) return true;
    if (e.type === "keydown" && !e.repeat) {
      e.preventDefault();
      onFind();
    }
    return false;
  });

  // copy on select: a selection made with the mouse is copied when the button is let go (find also selects, and
  // that must not touch the clipboard). The mouse may be let go outside the terminal, so that is watched on the page.
  let dragging = false;
  const down = (e: MouseEvent) => {
    dragging = e.button === 0;
  };
  const up = (e: MouseEvent) => {
    if (!dragging || e.button !== 0) return;
    dragging = false;
    if (!readTermSettings().copyOnSelect || !term.hasSelection()) return;
    const text = term.getSelection();
    if (text) void navigator.clipboard?.writeText(text).catch(() => undefined);
  };
  host.addEventListener("mousedown", down);
  document.addEventListener("mouseup", up);

  // right-click pastes: the press is taken before xterm (and a program's mouse reporting) sees it, and the menu
  // does not open. Ctrl+right-click is left alone.
  const claims = (e: MouseEvent) => e.button === 2 && !e.ctrlKey && readTermSettings().rightClickPaste;
  const press = (e: MouseEvent) => {
    if (!claims(e)) return;
    e.preventDefault();
    e.stopPropagation();
    term.focus();
    void navigator.clipboard
      ?.readText()
      .then((text) => {
        if (text) term.paste(text);
      })
      .catch(() => undefined);
  };
  const menu = (e: MouseEvent) => {
    if (!readTermSettings().rightClickPaste || e.ctrlKey) return;
    e.preventDefault();
    e.stopPropagation();
  };
  host.addEventListener("mousedown", press, true);
  host.addEventListener("contextmenu", menu, true);

  return () => {
    host.removeEventListener("mousedown", down);
    document.removeEventListener("mouseup", up);
    host.removeEventListener("mousedown", press, true);
    host.removeEventListener("contextmenu", menu, true);
    term.attachCustomKeyEventHandler(() => true);
  };
}
