// Multi-line paste protection. A line break in pasted text is an Enter: each line runs as it arrives, so a paste
// of several lines (or one that ends in a line break) into a shell prompt runs commands the person may not have
// read. When the program has turned on bracketed paste (DECSET 2004) it gets the text as one marked paste and runs
// none of it by itself, so the paste goes straight through. Otherwise the terminal's pane asks first: how many
// lines, the first few, Paste or Cancel (Enter / Esc). Settings > Terminal "Confirm multi-line paste", on by default.
//
// Every paste path goes through here: Cmd/Ctrl+V and the Edit menu's Paste arrive as a `paste` event on xterm's
// textarea (taken on the terminal's element, in the capture phase, ahead of xterm), and the right-click paste
// (engine-input.ts) calls `guardedPaste`.
import type { Terminal } from "@xterm/xterm";
import "./paste-guard.css";
import { t } from "../../i18n";
import { readTermSettings } from "./settings";

const BREAK = /\r\n|\r|\n/;
/** How many lines of the paste the confirm shows, and how much of each. */
export const PREVIEW_LINES = 3;
export const PREVIEW_COLS = 80;

/** Ask before sending `text`? Only when it holds a line break, the program has not turned bracketed paste on, and
 *  the setting is on. */
export function needsConfirm(text: string, bracketed: boolean, confirmOn: boolean): boolean {
  return confirmOn && !bracketed && /[\r\n]/.test(text);
}

/** The lines a paste holds (a final line break ends the last line, it does not start an empty one). */
export function pasteLines(text: string): string[] {
  const lines = text.split(BREAK);
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** The first lines of a paste as the confirm shows them, each cut to `PREVIEW_COLS` with an ellipsis. */
export function previewOf(text: string): { lines: string[]; total: number } {
  const all = pasteLines(text);
  const cut = (l: string) => {
    const s = l.replace(/\t/g, "  ");
    return s.length > PREVIEW_COLS ? `${s.slice(0, PREVIEW_COLS - 1)}…` : s;
  };
  return { lines: all.slice(0, PREVIEW_LINES).map(cut), total: all.length };
}

/** The program asked for bracketed paste and the terminal honours it. */
const bracketedOn = (term: Terminal) => term.modes.bracketedPasteMode && term.options.ignoreBracketedPasteMode !== true;

interface Guard {
  host: HTMLElement;
  /** the confirm open on this terminal, and what closes it */
  open: { el: HTMLElement; close: () => void } | null;
}
const guards = new WeakMap<Terminal, Guard>();

/** Sent on a terminal's element (bubbling) when the person's own keys or paste reach its program: not the terminal's
 *  replies to a program's queries, which also leave through xterm's onData (sessions.ts `keyed`). */
export const TERM_INPUT_EVENT = "omher-term-input";
export const saidInto = (host: HTMLElement | undefined): void => void host?.dispatchEvent(new Event(TERM_INPUT_EVENT, { bubbles: true }));

function ask(term: Terminal, g: Guard, text: string): void {
  // a second paste while one is waiting replaces it
  g.open?.close();
  const { lines, total } = previewOf(text);
  const el = document.createElement("div");
  el.className = "tpaste";
  el.setAttribute("role", "alertdialog");
  el.setAttribute("aria-label", t("paste.label"));
  el.dataset.testid = "term-paste-confirm";
  const title = document.createElement("div");
  title.className = "tpaste-t";
  title.textContent = total === 1 ? t("paste.titleOne") : t("paste.title", { n: total });
  const hint = document.createElement("div");
  hint.className = "tpaste-h";
  hint.textContent = t("paste.hint");
  const pre = document.createElement("pre");
  pre.className = "tpaste-p";
  pre.dataset.testid = "term-paste-preview";
  pre.textContent = lines.join("\n");
  const more = document.createElement("div");
  more.className = "tpaste-m";
  if (total > lines.length) more.textContent = t("paste.more", { n: total - lines.length });
  const row = document.createElement("div");
  row.className = "tpaste-r";
  const btn = (label: string, id: string, primary: boolean) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = primary ? "tpaste-b tpaste-ok" : "tpaste-b";
    b.textContent = label;
    b.dataset.testid = id;
    return b;
  };
  const cancel = btn(t("paste.cancel"), "term-paste-cancel", false);
  const ok = btn(t("paste.ok"), "term-paste-ok", true);
  row.append(cancel, ok);
  el.append(title, hint, pre);
  if (more.textContent) el.append(more);
  el.append(row);

  const close = () => {
    if (g.open?.el !== el) return;
    g.open = null;
    el.remove();
  };
  const done = (send: boolean) => {
    close();
    term.focus();
    // xterm brackets it if the program turned bracketed paste on meanwhile, and makes every line break a CR
    if (!send) return;
    saidInto(g.host);
    term.paste(text);
  };
  ok.addEventListener("click", () => done(true));
  cancel.addEventListener("click", () => done(false));
  // the keys stay with the confirm: nothing reaches the program, the find shortcut or the app behind it
  el.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.isComposing) return;
    // Enter pastes, wherever the focus is in the confirm (Space still presses the button that has it)
    if (e.key === "Enter") {
      e.preventDefault();
      done(true);
    } else if (e.key === "Escape") {
      e.preventDefault();
      done(false);
    }
  });
  el.addEventListener("mousedown", (e) => e.stopPropagation());
  g.open = { el, close };
  g.host.appendChild(el);
  ok.focus();
}

/** Paste `text` into `term`: at once, or after the person confirms (see the top of this file). */
export function guardedPaste(term: Terminal, text: string): void {
  if (!text) return;
  const g = guards.get(term);
  if (!g || !needsConfirm(text, bracketedOn(term), readTermSettings().confirmPaste)) {
    saidInto(g?.host);
    term.paste(text);
    return;
  }
  ask(term, g, text);
}

/** Put the guard in front of xterm's own paste for `term` (open, inside `host`). Returns what undoes it. */
export function attachPasteGuard(term: Terminal, host: HTMLElement): () => void {
  const g: Guard = { host, open: null };
  guards.set(term, g);
  const paste = (e: ClipboardEvent) => {
    const dt = e.clipboardData;
    // files (a picture) are the session view's; xterm takes text only
    if (!dt || dt.files.length) return;
    const text = dt.getData("text/plain");
    if (text && !needsConfirm(text, bracketedOn(term), readTermSettings().confirmPaste)) saidInto(host);
    if (!text || !needsConfirm(text, bracketedOn(term), readTermSettings().confirmPaste)) return;
    e.preventDefault();
    e.stopPropagation();
    ask(term, g, text);
  };
  host.addEventListener("paste", paste, true);
  return () => {
    host.removeEventListener("paste", paste, true);
    g.open?.close();
    if (guards.get(term) === g) guards.delete(term);
  };
}
