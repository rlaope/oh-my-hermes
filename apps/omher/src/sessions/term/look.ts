// How a SESSIONS terminal looks: the xterm options a terminal is made with, and the same look applied again to
// a terminal that is already open (a theme switch, a changed setting).
import type { ITerminalOptions, ITheme, Terminal } from "@xterm/xterm";
import type { TermContrast, TermSettings } from "./settings";
import { isLightBackground } from "./themes";

const appMono = () => (typeof document === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue("--mono").trim()) || "monospace";

/** Orca's floors: 4.5:1 keeps white ANSI text readable on a light background; 3:1 on a dark one lifts text that
 *  sits near the background without washing out saturated colours. */
export const LIGHT_BG_MIN_CONTRAST = 4.5;
export const DARK_BG_MIN_CONTRAST = 3;

/** xterm's `minimumContrastRatio` for a theme background: `auto` goes by the background's luminance (not by the
 *  app theme: either pick may be a light or a dark theme), `high` is 4.5 everywhere, `theme` is 1 (no change). */
export function termContrast(background: string | undefined, c: TermContrast): number {
  if (c === "theme") return 1;
  if (c === "high") return LIGHT_BG_MIN_CONTRAST;
  return isLightBackground(background) ? LIGHT_BG_MIN_CONTRAST : DARK_BG_MIN_CONTRAST;
}

const GENERIC = new Set(["monospace", "ui-monospace", "serif", "sans-serif", "ui-serif", "ui-sans-serif", "system-ui", "cursive", "fantasy"]);

/** The person's fonts first, omher's monospace stack behind them (a name that is not installed falls through).
 *  Each name is written quoted, whatever quotes it was typed with, so a half-typed list is still valid CSS. */
export function termFont(family: string, mono: string = appMono()): string {
  const names = family
    .split(",")
    .map((n) => n.replace(/['"]/g, "").trim().replace(/\s+/g, " "))
    .filter(Boolean)
    .map((n) => (GENERIC.has(n.toLowerCase()) ? n.toLowerCase() : `"${n}"`));
  return names.length ? `${names.join(", ")}, ${mono}` : mono;
}

/** The options a new terminal starts with. */
export function termOptions(theme: ITheme, s: TermSettings): ITerminalOptions {
  return {
    fontFamily: termFont(s.fontFamily),
    fontSize: s.fontSize,
    lineHeight: s.lineHeight,
    cursorStyle: s.cursorStyle,
    // without the keyboard a block cursor is an outline; a bar or an underline keeps its shape (an outline
    // around either reads as a block)
    cursorInactiveStyle: s.cursorStyle === "block" ? "outline" : s.cursorStyle,
    cursorBlink: s.cursorBlink,
    // the engine's add-ons (Unicode widths) register through xterm's proposed API
    allowProposedApi: true,
    scrollback: s.scrollback,
    // text colours near the background are lifted; dim (SGR 2) text is not held to this (xterm halves its target)
    minimumContrastRatio: termContrast(theme.background, s.contrast),
    macOptionIsMeta: s.optionIsMeta,
    theme,
  };
}

/** The space around a terminal for a padding setting: the setting is the left side; the top, the bottom and the
 *  right (where the scrollbar already stands off the text) keep the proportions omher's terminal always had. */
const TERM_PAD_VAR = "--term-pad";
/** The picked theme's background, so the space around the terminal is the terminal's colour, not the page's. */
const TERM_BG_VAR = "--term-bg";

type DevWindow = { __omherTerms?: Set<Terminal> };
/** e2e reads the terminals (their real options and size) through this; a release build has no such thing. A
 *  disposed terminal (xterm takes its element out of its parent) drops out at the next look. */
function expose(term: Terminal): void {
  if (!import.meta.env?.DEV || typeof window === "undefined") return;
  const set = ((window as unknown as DevWindow).__omherTerms ??= new Set());
  for (const t of set) if (t !== term && !t.element?.parentNode) set.delete(t);
  set.add(term);
}

/** The look again, on an open terminal. Scrollback is not here: a terminal keeps the rows it was made with. */
export function applyLook(term: Terminal, theme: ITheme, s: TermSettings): void {
  const next = termOptions(theme, s);
  const o = term.options;
  o.theme = theme;
  o.fontFamily = next.fontFamily;
  o.fontSize = next.fontSize;
  o.lineHeight = next.lineHeight;
  o.cursorStyle = next.cursorStyle;
  o.cursorInactiveStyle = next.cursorInactiveStyle;
  o.cursorBlink = next.cursorBlink;
  o.minimumContrastRatio = next.minimumContrastRatio;
  o.macOptionIsMeta = next.macOptionIsMeta;
  // the box the terminal sits in: a session's (sessions.css) or the Settings preview's; both read these two
  const wrap = term.element?.closest<HTMLElement>(".term-wrap, .term-pv");
  if (wrap) {
    wrap.style.setProperty(TERM_PAD_VAR, `${s.padding}px`);
    if (theme.background) wrap.style.setProperty(TERM_BG_VAR, theme.background);
    else wrap.style.removeProperty(TERM_BG_VAR);
  }
  expose(term);
}
