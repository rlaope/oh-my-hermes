// What a person can change about SESSIONS terminals, kept on this computer (localStorage). One record for every
// terminal: the look reads it when a terminal is made and again when it changes; the engine reads `gpu` and
// `scrollback`. Anything stored that is missing, of the wrong type or out of range falls back to the default.

export type TermGpu = "auto" | "on" | "off";
export type TermCursor = "block" | "bar" | "underline";
/** How far faint text is lifted from the background: `high` is 4.5:1 everywhere, `auto` is 4.5:1 on a light
 *  background and 3:1 on a dark one, `theme` leaves the theme's colours as they are. */
export type TermContrast = "auto" | "high" | "theme";

export const TERM_CURSORS: readonly TermCursor[] = ["block", "bar", "underline"];
export const TERM_CONTRASTS: readonly TermContrast[] = ["auto", "high", "theme"];
export const TERM_GPUS: readonly TermGpu[] = ["auto", "on", "off"];
/** The scrollback sizes Settings offers. */
export const TERM_SCROLLBACKS: readonly number[] = [5000, 10000, 25000, 50000];
export const TERM_FONT_SIZE = { min: 9, max: 24 } as const;
export const TERM_LINE_HEIGHT = { min: 1, max: 2 } as const;
export const TERM_PADDING = { min: 0, max: 24 } as const;

export interface TermSettings {
  /** Theme ids from the catalog, one per app theme. */
  themeDark: string;
  themeLight: string;
  /** "" = the app's own monospace stack (`--mono`). */
  fontFamily: string;
  fontSize: number;
  lineHeight: number;
  cursorStyle: TermCursor;
  cursorBlink: boolean;
  /** Rows kept above the screen. A terminal takes it when it is made. */
  scrollback: number;
  contrast: TermContrast;
  /** Space around the terminal, in px, measured on its left side (the other sides keep their proportion). */
  padding: number;
  /** macOS: Option sends Meta (Alt) to the program instead of typing a character. */
  optionIsMeta: boolean;
  /** The GPU renderer: `auto` uses it where it is known to work and falls back by itself. */
  gpu: TermGpu;
}

export const TERM_KEY = "omher.term";

export const TERM_DEFAULTS: TermSettings = {
  themeDark: "omher-dark",
  themeLight: "omher-light",
  fontFamily: "",
  fontSize: 12.5,
  lineHeight: 1.2,
  cursorStyle: "block",
  cursorBlink: true,
  scrollback: 5000,
  contrast: "high",
  padding: 16,
  optionIsMeta: true,
  gpu: "auto",
};

const num = (v: unknown, lo: number, hi: number, d: number) => (typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d);
const str = (v: unknown, d: string, max = 200) => (typeof v === "string" && v.length <= max ? v : d);
/** A font list as a person types it, kept to what a font name is made of (letters, digits, spaces, commas, quotes,
 *  dots, hyphens): the value ends up in a stylesheet, so nothing that could end a rule is kept. */
export const cleanTermFont = (v: string): string => v.replace(/[^\p{L}\p{N} ,'"._-]/gu, "").slice(0, 200);
const one = <T extends string>(v: unknown, list: readonly T[], d: T): T => (list.includes(v as T) ? (v as T) : d);
const bool = (v: unknown, d: boolean) => (typeof v === "boolean" ? v : d);

/** Stored text or object -> settings, every field checked. */
export function parseTermSettings(raw: unknown): TermSettings {
  let v: unknown = raw;
  if (typeof raw === "string") {
    try {
      v = JSON.parse(raw);
    } catch {
      v = null;
    }
  }
  const o = (v && typeof v === "object" && !Array.isArray(v) ? v : {}) as Record<string, unknown>;
  const d = TERM_DEFAULTS;
  return {
    themeDark: str(o.themeDark, d.themeDark) || d.themeDark,
    themeLight: str(o.themeLight, d.themeLight) || d.themeLight,
    fontFamily: cleanTermFont(str(o.fontFamily, d.fontFamily)),
    fontSize: num(o.fontSize, TERM_FONT_SIZE.min, TERM_FONT_SIZE.max, d.fontSize),
    lineHeight: num(o.lineHeight, TERM_LINE_HEIGHT.min, TERM_LINE_HEIGHT.max, d.lineHeight),
    cursorStyle: one(o.cursorStyle, TERM_CURSORS, d.cursorStyle),
    cursorBlink: bool(o.cursorBlink, d.cursorBlink),
    scrollback: Math.round(num(o.scrollback, 1000, 50000, d.scrollback)),
    contrast: one(o.contrast, TERM_CONTRASTS, d.contrast),
    padding: Math.round(num(o.padding, TERM_PADDING.min, TERM_PADDING.max, d.padding)),
    optionIsMeta: bool(o.optionIsMeta, d.optionIsMeta),
    gpu: one(o.gpu, TERM_GPUS, d.gpu),
  };
}

let current: TermSettings | null = null;
const listeners = new Set<(s: TermSettings) => void>();

export function readTermSettings(): TermSettings {
  if (current) return current;
  let raw: string | null = null;
  try {
    raw = typeof localStorage !== "undefined" ? localStorage.getItem(TERM_KEY) : null;
  } catch {
    /* no storage */
  }
  return (current = parseTermSettings(raw));
}

/** Change some settings: checked, saved, and handed to every open terminal. */
export function writeTermSettings(patch: Partial<TermSettings>): TermSettings {
  const next = parseTermSettings({ ...readTermSettings(), ...patch });
  current = next;
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(TERM_KEY, JSON.stringify(next));
  } catch {
    /* no storage */
  }
  for (const fn of listeners) fn(next);
  return next;
}

export function onTermSettings(fn: (s: TermSettings) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Tests: forget what was read. */
export function resetTermSettings(): void {
  current = null;
}
