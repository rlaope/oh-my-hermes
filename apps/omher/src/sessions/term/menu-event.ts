// The terminal's right-click menu: a terminal sends this (bubbling, from its element) when the person asks for the
// menu, and TermMenu.tsx (mounted once in the app) shows it. Kept apart so the app shell reads it without loading xterm.
import type { Terminal } from "@xterm/xterm";

export const TERM_MENU_EVENT = "omher-term-menu";

export interface TermMenuRequest {
  term: Terminal;
  /** the terminal's element (inside a TERMINALS terminal or a bottom-panel pane) */
  host: HTMLElement;
  x: number;
  y: number;
  /** open the terminal's find bar */
  find: () => void;
}
