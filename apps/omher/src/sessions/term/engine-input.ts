// What a terminal does with the person's keyboard and mouse beyond xterm's own: the find shortcut, the two
// clipboard settings (both off unless the person turned them on in Settings > Terminal) and the multi-line paste
// confirm (paste-guard.ts, on unless turned off). Settings are read when the event happens, so a switch applies to
// terminals that are already open.
//
// Find shortcut: Cmd+F on macOS. On Windows and Linux Ctrl+F opens find too, except while a full-screen program
// (the alternate screen: vim, less, htop) is showing: there Ctrl+F is the program's (page down) and the alternate
// screen has no scrollback to search anyway. Ctrl+Shift+F opens find everywhere, so the bar is always reachable.
//
// Font size: Cmd+= (or Cmd++) larger, Cmd+- smaller, Cmd+0 back to the default, on macOS; Ctrl with the same keys on
// Windows and Linux (as Windows Terminal and VS Code). It is the Settings > Terminal font size, so every terminal
// follows and the size is kept. The keys are matched by where they stand too, so a Korean or German layout works.
//
// Line editing on macOS, as Terminal.app, iTerm2, Ghostty and Orca send it: Cmd+Left / Cmd+Right go to the start / end
// of the line (Ctrl+A / Ctrl+E), Cmd+Backspace deletes to the start (Ctrl+U), Cmd+Delete to the end (Ctrl+K), and
// Option+Left / Option+Right move a word (ESC b / ESC f; xterm's own ESC[1;3D is bound in no stock zsh or bash). A
// program that turned the Kitty keyboard protocol on gets Option+arrows as xterm encodes them: it reads them itself.
// Cmd+K clears the screen and the scrollback (as in Terminal.app and iTerm2); the prompt stays, the program sees no key.
//
// Scrolling: Cmd+Home / Cmd+End (Fn+Cmd+Left / Right on a laptop) on macOS, Ctrl+Home / Ctrl+End elsewhere (as in VS
// Code), go to the top / bottom of the scrollback; Shift+PageUp / Shift+PageDown page through it (xterm's own). A
// full-screen program (the alternate screen) has no scrollback, so there the keys stay the program's.
//
// Copy and paste off macOS, as Windows Terminal and GNOME Terminal: Ctrl+Shift+C or Ctrl+Insert copies the selection
// (never a Ctrl+C to the program, selection or not), Ctrl+Shift+V or Shift+Insert pastes through the page's own paste
// (the multi-line confirm and a pasted picture's path included). macOS keeps Cmd+C / Cmd+V from the Edit menu.
import type { Terminal } from "@xterm/xterm";
import { isMacPlatform } from "./engine-links";
import { readTermSettings, TERM_DEFAULTS, writeTermSettings } from "./settings";
import { kittyKeysOn } from "./park";
import { TERM_MENU_EVENT, type TermMenuRequest } from "./menu-event";
import { historyChanged } from "./history";
import { attachPasteGuard, guardedPaste } from "./paste-guard";
import type { FindOptions } from "./engine-find";

type KeyLike = { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean };

/** The key that stands for `letter`: itself on a Latin layout; otherwise (a non-Latin layout, or Option on a Mac,
 *  which types ç or ®) the key in its place. */
const isKey = (e: Pick<KeyLike, "key" | "code">, letter: string) =>
  e.key.toLowerCase() === letter || (!/^[a-z]$/i.test(e.key) && e.code === `Key${letter.toUpperCase()}`);

/** `f` on a Latin layout; on a non-Latin one (Korean, Japanese, Russian...) the key that stands where F does. */
const isF = (e: Pick<KeyLike, "key" | "code">) => isKey(e, "f");

/** Does this key press ask for find? `altScreen`: a full-screen program is showing. */
export function isFindKey(e: KeyLike, mac: boolean, altScreen: boolean): boolean {
  if (!isF(e) || e.altKey) return false;
  if (mac) return e.metaKey && !e.ctrlKey && !e.shiftKey;
  if (!e.ctrlKey || e.metaKey) return false;
  return e.shiftKey || !altScreen;
}

/** In the find bar, Alt+C flips Match case and Alt+R flips Regular expression; null for any other key. */
export function findOptionKey(e: KeyLike): keyof FindOptions | null {
  if (!e.altKey || e.ctrlKey || e.metaKey) return null;
  if (isKey(e, "c")) return "caseSensitive";
  if (isKey(e, "r")) return "regex";
  return null;
}

export type FontKey = "bigger" | "smaller" | "reset";

/** Does this key press change the terminal font size? Shift is allowed for bigger (Cmd++ is Cmd+Shift+= on a US layout). */
export function fontKey(e: KeyLike, mac: boolean): FontKey | null {
  if (e.altKey || (mac ? !e.metaKey || e.ctrlKey : !e.ctrlKey || e.metaKey)) return null;
  if (e.code === "Equal" || e.code === "NumpadAdd" || e.key === "=" || e.key === "+") return "bigger";
  // Shift stays out of the other two: Ctrl+Shift+- is Ctrl+_, readline's undo
  if (e.shiftKey) return null;
  if (e.code === "Minus" || e.code === "NumpadSubtract" || e.key === "-") return "smaller";
  if (e.code === "Digit0" || e.code === "Numpad0" || e.key === "0") return "reset";
  return null;
}

/** The font size after `k`: one point a step, within the Settings range (writeTermSettings clamps). */
export function nextFontSize(size: number, k: FontKey): number {
  if (k === "reset") return TERM_DEFAULTS.fontSize;
  return Math.round(size) + (k === "bigger" ? 1 : -1);
}

/** The bytes a macOS line-editing key sends instead of xterm's, or null. `kitty`: the program has Kitty keys on. */
export function lineEditBytes(e: KeyLike, mac: boolean, kitty: boolean): string | null {
  if (!mac || e.ctrlKey || e.shiftKey) return null;
  if (e.metaKey && !e.altKey) {
    if (e.key === "ArrowLeft") return "\x01";
    if (e.key === "ArrowRight") return "\x05";
    if (e.key === "Backspace") return "\x15";
    if (e.key === "Delete") return "\x0b";
    return null;
  }
  if (e.altKey && !e.metaKey && !kitty) {
    if (e.key === "ArrowLeft") return "\x1bb";
    if (e.key === "ArrowRight") return "\x1bf";
  }
  return null;
}

/** Cmd+K on macOS: clear the screen and the scrollback. Off macOS Ctrl+K is the program's (it kills to the line end). */
export function isClearKey(e: KeyLike, mac: boolean): boolean {
  return mac && e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey && isKey(e, "k");
}

/** Cmd+Home / Cmd+End (macOS), Ctrl+Home / Ctrl+End (elsewhere): the top or bottom of the scrollback, or null. */
export function scrollKey(e: KeyLike, mac: boolean): "top" | "bottom" | null {
  if (e.altKey || e.shiftKey || (mac ? !e.metaKey || e.ctrlKey : !e.ctrlKey || e.metaKey)) return null;
  if (e.key === "Home") return "top";
  if (e.key === "End") return "bottom";
  return null;
}

/** Copy or paste keys off macOS, or null. */
export function clipboardKey(e: KeyLike, mac: boolean): "copy" | "paste" | null {
  if (mac || e.metaKey || e.altKey) return null;
  if (e.ctrlKey && e.shiftKey && isKey(e, "c")) return "copy";
  if (e.ctrlKey && e.shiftKey && isKey(e, "v")) return "paste";
  if (e.key === "Insert" && e.ctrlKey && !e.shiftKey) return "copy";
  if (e.key === "Insert" && e.shiftKey && !e.ctrlKey) return "paste";
  return null;
}

/** Keyboard and mouse handling for one terminal; `onFind` runs when the person asks for find. Returns what undoes it. */
export function attachInput(term: Terminal, host: HTMLElement, onFind: () => void): () => void {
  const mac = isMacPlatform();
  const linux = !mac && typeof navigator !== "undefined" && /Linux/.test(navigator.platform);
  // find: xterm asks first; `false` keeps the key from the program
  term.attachCustomKeyEventHandler((e) => {
    const font = fontKey(e, mac);
    if (font) {
      if (e.type === "keydown") {
        e.preventDefault();
        writeTermSettings({ fontSize: nextFontSize(readTermSettings().fontSize, font) });
      }
      return false;
    }
    const bytes = lineEditBytes(e, mac, kittyKeysOn(term));
    if (bytes !== null) {
      if (e.type === "keydown") {
        e.preventDefault();
        term.input(bytes, true);
      }
      return false;
    }
    const clip = clipboardKey(e, mac);
    if (clip === "copy") {
      if (e.type === "keydown") {
        e.preventDefault();
        const text = term.hasSelection() ? term.getSelection() : "";
        if (text) void navigator.clipboard?.writeText(text).catch(() => undefined);
      }
      return false;
    }
    if (clip === "paste") {
      // Windows (WebView2) pastes on these keys by itself: its paste event reaches the paste guard and the file paste.
      // WebKitGTK has no Ctrl+Shift+V binding, so on Linux that one reads the clipboard's text and pastes it here
      if (linux && e.shiftKey && e.ctrlKey && e.type === "keydown") {
        e.preventDefault();
        void navigator.clipboard
          ?.readText()
          .then((text) => {
            if (text) guardedPaste(term, text);
          })
          .catch(() => undefined);
      }
      return false;
    }
    const scroll = term.buffer.active.type === "normal" ? scrollKey(e, mac) : null;
    if (scroll) {
      if (e.type === "keydown") {
        e.preventDefault();
        if (scroll === "top") term.scrollToTop();
        else term.scrollToBottom();
      }
      return false;
    }
    if (isClearKey(e, mac)) {
      if (e.type === "keydown") {
        e.preventDefault();
        // the app's own Cmd+K (the bot search) is not wanted with the keyboard in a terminal
        e.stopPropagation();
        if (!e.repeat) {
          term.clear();
          historyChanged(term);
        }
      }
      return false;
    }
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
  // (not on the paste confirm, which keeps its own clicks)
  const claims = (e: MouseEvent) => e.button === 2 && !e.ctrlKey && readTermSettings().rightClickPaste && !(e.target as Element | null)?.closest?.(".tpaste");
  const press = (e: MouseEvent) => {
    if (!claims(e)) return;
    e.preventDefault();
    e.stopPropagation();
    term.focus();
    void navigator.clipboard
      ?.readText()
      .then((text) => {
        if (text) guardedPaste(term, text);
      })
      .catch(() => undefined);
  };
  // otherwise (and Ctrl+right-click with right-click pastes on) the terminal's own menu (TermMenu.tsx): copy, paste,
  // select all, find, clear, reset, split; the paste confirm keeps its own clicks
  // A program that reads the mouse (tmux with mouse on, htop, vim mouse=a) gets the right click, as in Terminal.app
  // and iTerm2; Shift+right-click still opens the menu there.
  const menu = (e: MouseEvent) => {
    if ((e.target as Element | null)?.closest?.(".tpaste")) return;
    e.preventDefault();
    e.stopPropagation();
    if (term.modes.mouseTrackingMode !== "none" && !e.shiftKey) return;
    if (readTermSettings().rightClickPaste && !e.ctrlKey) return;
    const detail: TermMenuRequest = { term, host, x: e.clientX, y: e.clientY, find: onFind };
    host.dispatchEvent(new CustomEvent<TermMenuRequest>(TERM_MENU_EVENT, { bubbles: true, detail }));
  };
  host.addEventListener("mousedown", press, true);
  host.addEventListener("contextmenu", menu, true);
  // Cmd/Ctrl+V and the Edit menu's Paste: a paste of several lines asks first
  const undoPaste = attachPasteGuard(term, host);

  return () => {
    undoPaste();
    host.removeEventListener("mousedown", down);
    document.removeEventListener("mouseup", up);
    host.removeEventListener("mousedown", press, true);
    host.removeEventListener("contextmenu", menu, true);
    term.attachCustomKeyEventHandler(() => true);
  };
}
