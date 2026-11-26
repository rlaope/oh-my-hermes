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
// Off macOS Ctrl+K is the program's (it kills to the line end), so Ctrl+Shift+K clears (as Konsole), and Ctrl+Shift+A
// selects the whole buffer (Windows Terminal and GNOME Terminal) where Cmd+A does on macOS.
//
// Scrolling: Cmd+Home / Cmd+End (Fn+Cmd+Left / Right on a laptop) on macOS, Ctrl+Home / Ctrl+End elsewhere (as in VS
// Code), go to the top / bottom of the scrollback; Shift+PageUp / Shift+PageDown page through it (xterm's own). A
// full-screen program (the alternate screen) has no scrollback, so there the keys stay the program's.
//
// Copy and paste off macOS: Ctrl+Shift+C or Ctrl+Insert copies the selection (never a Ctrl+C to the program, selection
// or not), Ctrl+Shift+V or Shift+Insert pastes through the page's own paste (the multi-line confirm and a pasted
// picture's path included). On Windows, as Windows Terminal does by default, Ctrl+V pastes the same way and Ctrl+C
// copies while there is a selection (and clears it, so the next Ctrl+C reaches the program); with no selection Ctrl+C
// is the program's ^C. Linux keeps the GNOME Terminal and Konsole convention: plain Ctrl+C and Ctrl+V are the
// program's (^C, and ^V for a literal next key in a shell or block select in vim). macOS keeps Cmd+C / Cmd+V from the
// Edit menu. None of these keys is taken with Alt or AltGr held (AltGr reads as Ctrl+Alt on Windows: ć, @ or €).
//
// On macOS every other Cmd key is the app's (Copy, Paste, Select All and the rest of the menu, the app's shortcuts),
// as in Terminal.app and iTerm2, and never reaches the program. Without this, a program that turned the Kitty
// keyboard protocol on (Claude Code and Codex do) would get Cmd+V as CSI 118;9 u, and xterm would cancel the key, so
// the Edit menu's Paste never ran.
import type { Terminal } from "@xterm/xterm";
import { isMacPlatform } from "./engine-links";
import { readTermSettings, TERM_DEFAULTS, writeTermSettings } from "./settings";
import { kittyKeysOn } from "./park";
import { TERM_MENU_EVENT, type TermMenuRequest } from "./menu-event";
import { historyChanged } from "./history";
import { attachPasteGuard, guardedPaste, saidInto } from "./paste-guard";
import type { FindOptions } from "./engine-find";

type KeyLike = { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; getModifierState?(key: "AltGraph"): boolean };

/** Which keyboard convention a terminal follows: macOS, Windows (Windows Terminal's) or Linux (GNOME Terminal's). */
export type KeyOs = "mac" | "win" | "linux";
export const keyOs = (): KeyOs =>
  isMacPlatform() ? "mac" : typeof navigator !== "undefined" && /^Win/.test(navigator.platform) ? "win" : "linux";

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

/** Agents that read Shift+Enter only as the Kitty code even when they did not turn the protocol on (pi and the TUIs
 *  built on its reader: oh-my-pi, Droid). They take `ESC CR` as Enter and send, so they get `CSI 13;2 u`. Orca keeps
 *  the same list (`windowsShiftEnterEncoding: 'csi-u'`, MIT, stablyai/orca tui-agent-config.ts). */
const CSI_U_AGENTS = new Set(["pi", "omp", "droid"]);
export const SHIFT_ENTER_CSI_U = "\x1b[13;2u";
export const SHIFT_ENTER_ESC_CR = "\x1b\r";

/** What Shift+Enter sends instead of xterm's `\r`, or null to leave it to xterm. `kitty`: the program turned the Kitty
 *  keyboard protocol on (xterm then sends `CSI 13;2 u` itself). `agent`: the coding agent in the terminal's foreground
 *  (null: a shell or any other program).
 *
 *  Without the Kitty protocol xterm sends Shift+Enter as `\r`, the same byte as Enter, so an agent sends the prompt
 *  where the person wanted a new line. That is every agent on Windows (ConPTY does not pass the protocol's request
 *  through, so Claude Code never turns it on there; anthropics/claude-code#92771) and the agents that never ask for it
 *  on any OS (omh, Hermes, Claude Code before 2.1.269). `ESC CR` (Alt+Enter) is a new line in every agent measured:
 *  Claude Code, Codex, Antigravity, omh, Hermes, and it is what Claude Code's own /terminal-setup binds Shift+Enter
 *  to. A shell keeps `\r`: zsh and bash run the line on it, and `ESC CR` would insert a raw CR there instead. */
export function shiftEnterBytes(e: KeyLike, kitty: boolean, agent: string | null): string | null {
  if (e.key !== "Enter" || !e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
  if (kitty || !agent) return null;
  return CSI_U_AGENTS.has(agent) ? SHIFT_ENTER_CSI_U : SHIFT_ENTER_ESC_CR;
}

/** The coding agent in each terminal's foreground, by the terminal's element (it outlives a parked terminal). The
 *  owner (sessions.ts for TERMINALS, terminal/terms.ts for the bottom panel) says how to find it. */
const agentOf = new WeakMap<HTMLElement, () => string | null>();
export function setTermAgent(host: HTMLElement, find: () => string | null): void {
  agentOf.set(host, find);
}

/** Cmd+K on macOS, Ctrl+Shift+K elsewhere: clear the screen and the scrollback. Off macOS Ctrl+K is the program's (it
 *  kills to the line end). */
export function isClearKey(e: KeyLike, mac: boolean): boolean {
  if (e.altKey || !isKey(e, "k")) return false;
  return mac ? e.metaKey && !e.ctrlKey && !e.shiftKey : e.ctrlKey && e.shiftKey && !e.metaKey;
}

/** Cmd+Home / Cmd+End (macOS), Ctrl+Home / Ctrl+End (elsewhere): the top or bottom of the scrollback, or null. */
export function scrollKey(e: KeyLike, mac: boolean): "top" | "bottom" | null {
  if (e.altKey || e.shiftKey || (mac ? !e.metaKey || e.ctrlKey : !e.ctrlKey || e.metaKey)) return null;
  if (e.key === "Home") return "top";
  if (e.key === "End") return "bottom";
  return null;
}

/** Copy or paste keys off macOS, or null. `selection`: the terminal has a selection (Ctrl+C copies only then, on
 *  Windows; otherwise it is the program's ^C). */
export function clipboardKey(e: KeyLike, os: KeyOs, selection: boolean): "copy" | "paste" | null {
  if (os === "mac" || e.metaKey || e.altKey || e.getModifierState?.("AltGraph")) return null;
  if (e.ctrlKey && e.shiftKey && isKey(e, "c")) return "copy";
  if (e.ctrlKey && e.shiftKey && isKey(e, "v")) return "paste";
  if (os === "win" && e.ctrlKey && !e.shiftKey && isKey(e, "c")) return selection ? "copy" : null;
  if (os === "win" && e.ctrlKey && !e.shiftKey && isKey(e, "v")) return "paste";
  if (e.key === "Insert" && e.ctrlKey && !e.shiftKey) return "copy";
  if (e.key === "Insert" && e.shiftKey && !e.ctrlKey) return "paste";
  return null;
}

/** A Cmd key on macOS that the app keeps (the menu's Copy, Paste and the rest): never sent to the program. */
export function isAppKey(e: KeyLike, mac: boolean): boolean {
  return mac && e.metaKey;
}

/** Cmd+A on macOS, Ctrl+Shift+A elsewhere (Ctrl+A is the program's: line start): select the terminal's whole buffer.
 *  xterm does this itself only for a key it is handed, and the Edit menu's Select All would select the hidden input
 *  field instead, so the page does it. */
export function isSelectAllKey(e: KeyLike, mac: boolean): boolean {
  if (e.altKey || !isKey(e, "a")) return false;
  return mac ? e.metaKey && !e.ctrlKey && !e.shiftKey : e.ctrlKey && e.shiftKey && !e.metaKey;
}

/** The character Option types on a Mac layout where it is how you reach a plain ASCII sign: @ [ ] { } | \\ ~ on a
 *  German, French, Swiss or Nordic layout. Those are typed, even with Option as Meta on, which would otherwise send
 *  Esc and the key's letter. On a US layout Option never types ASCII (∫ ƒ ≠ or a dead key), so Meta keeps working. */
export function optionTyped(e: KeyLike, mac: boolean): string | null {
  if (!mac || !e.altKey || e.metaKey || e.ctrlKey) return null;
  return e.key.length === 1 && e.key >= "!" && e.key <= "~" && !/^[a-z0-9]$/i.test(e.key) ? e.key : null;
}

const MODIFIERS = ["Shift", "Control", "Alt", "Meta", "CapsLock"];

/** Keyboard and mouse handling for one terminal; `onFind` runs when the person asks for find. Returns what undoes it. */
export function attachInput(term: Terminal, host: HTMLElement, onFind: () => void): () => void {
  const os = keyOs();
  const mac = os === "mac";
  const linux = !mac && typeof navigator !== "undefined" && /Linux/.test(navigator.platform);
  // a Ctrl+C that copied (Windows): its repeats and its key-up are not the program's either, though the selection may
  // be gone. Only that key's own key-up (or the terminal losing the keyboard) ends it: another key pressed meanwhile
  // does not, so the C's key-up never reaches the program alone.
  let copyHeld = false;
  const letGo = () => {
    copyHeld = false;
  };
  host.addEventListener("focusout", letGo);
  // find: xterm asks first; `false` keeps the key from the program
  term.attachCustomKeyEventHandler((e) => {
    if (copyHeld && isKey(e, "c")) {
      if (e.type === "keyup") {
        copyHeld = false;
        return false;
      }
      if (e.type !== "keydown" || e.repeat) return false;
      copyHeld = false; // a new press: the last one's key-up never came
    }
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
        saidInto(host);
        term.input(bytes, true);
      }
      return false;
    }
    // Shift+Enter is a new line in an agent, not a send (shiftEnterBytes)
    const newline = shiftEnterBytes(e, kittyKeysOn(term), agentOf.get(host)?.() ?? null);
    if (newline !== null) {
      if (e.type === "keydown") {
        e.preventDefault();
        saidInto(host);
        term.input(newline, true);
      }
      return false;
    }
    const typed = optionTyped(e, mac);
    if (typed !== null) {
      if (e.type === "keydown") {
        e.preventDefault();
        saidInto(host);
        term.input(typed, true);
      }
      return false;
    }
    const clip = clipboardKey(e, os, term.hasSelection());
    if (clip === "copy") {
      if (e.type === "keydown") {
        e.preventDefault();
        const text = term.hasSelection() ? term.getSelection() : "";
        // plain Ctrl+C (Windows) clears what it copied, as Windows Terminal does, once the clipboard took it: a copy
        // that failed keeps the selection, so the next Ctrl+C copies again instead of interrupting the program
        const clears = !e.shiftKey && e.key !== "Insert";
        if (clears) copyHeld = true;
        if (text && navigator.clipboard?.writeText) {
          void navigator.clipboard
            .writeText(text)
            .then(() => {
              if (clears && term.getSelection() === text) term.clearSelection();
            })
            .catch(() => undefined);
        }
      }
      return false;
    }
    if (clip === "paste") {
      // Windows (WebView2) pastes on these keys by itself (Ctrl+V too): its one paste event reaches the paste guard and
      // the file paste, so the page reads no clipboard here, and the paste happens once.
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
    if (isSelectAllKey(e, mac)) {
      if (e.type === "keydown") {
        e.preventDefault();
        term.selectAll();
      }
      return false;
    }
    if (!isFindKey(e, mac, term.buffer.active.type === "alternate")) {
      if (isAppKey(e, mac)) return false;
      // a key xterm sends to the program (a modifier alone sends nothing)
      if (e.type === "keydown" && !MODIFIERS.includes(e.key)) saidInto(host);
      return true;
    }
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
    host.removeEventListener("focusout", letGo);
    host.removeEventListener("mousedown", down);
    document.removeEventListener("mouseup", up);
    host.removeEventListener("mousedown", press, true);
    host.removeEventListener("contextmenu", menu, true);
    term.attachCustomKeyEventHandler(() => true);
  };
}
