// What a person can change about SESSIONS terminals, kept on this computer (localStorage). One record for every
// terminal: the look reads it when a terminal is made and again when it changes; the engine reads `gpu` and
// `scrollback`. Anything stored that is missing, of the wrong type or out of range falls back to the default.

export type TermGpu = "auto" | "on" | "off";

export interface TermSettings {
  /** Theme ids from the catalog, one per app theme. */
  themeDark: string;
  themeLight: string;
  /** "" = the app's own monospace stack (`--mono`). */
  fontFamily: string;
  fontSize: number;
  lineHeight: number;
  cursorBlink: boolean;
  /** Rows kept above the screen. */
  scrollback: number;
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
  cursorBlink: true,
  scrollback: 5000,
  gpu: "auto",
};

const num = (v: unknown, lo: number, hi: number, d: number) => (typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d);
const str = (v: unknown, d: string, max = 200) => (typeof v === "string" && v.length <= max ? v : d);

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
    fontFamily: str(o.fontFamily, d.fontFamily),
    fontSize: num(o.fontSize, 9, 24, d.fontSize),
    lineHeight: num(o.lineHeight, 1, 2, d.lineHeight),
    cursorBlink: typeof o.cursorBlink === "boolean" ? o.cursorBlink : d.cursorBlink,
    scrollback: Math.round(num(o.scrollback, 1000, 50000, d.scrollback)),
    gpu: o.gpu === "on" || o.gpu === "off" ? o.gpu : "auto",
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
