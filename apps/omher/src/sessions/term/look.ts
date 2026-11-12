// How a SESSIONS terminal looks: the xterm options a terminal is made with, and the same look applied again to
// a terminal that is already open (a theme switch, a changed setting).
import type { ITerminalOptions, ITheme, Terminal } from "@xterm/xterm";
import type { TermSettings } from "./settings";

const appMono = () => (typeof document === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue("--mono").trim()) || "monospace";

/** The options a new terminal starts with. */
export function termOptions(theme: ITheme, s: TermSettings): ITerminalOptions {
  return {
    fontFamily: s.fontFamily || appMono(),
    fontSize: s.fontSize,
    lineHeight: s.lineHeight,
    cursorBlink: s.cursorBlink,
    allowProposedApi: false,
    scrollback: s.scrollback,
    // dim text (agents use it a lot) stays readable on the light background
    minimumContrastRatio: 4.5,
    macOptionIsMeta: true,
    theme,
  };
}

/** The look again, on an open terminal. */
export function applyLook(term: Terminal, theme: ITheme, _s: TermSettings): void {
  term.options.theme = theme;
}
