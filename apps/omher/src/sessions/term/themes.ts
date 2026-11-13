// The colours of a SESSIONS terminal. A catalog of named themes (xterm `ITheme`), and which one a terminal uses:
// the person's pick for the app theme in force (Settings), else omher's own. omher's two come first; the rest are
// Orca's palettes, carried over by scripts/import-orca-themes.mjs into themes-orca.ts.
import type { ITheme } from "@xterm/xterm";
import type { TermSettings } from "./settings";
import { ORCA_TERM_THEMES } from "./themes-orca";

export interface TermTheme {
  id: string;
  /** The theme's own name, shown as it is (never translated). */
  name: string;
  kind: "dark" | "light";
  theme: ITheme;
}

// Matched to omher's tokens (--bg, --body, --ink) so the terminal reads as part of the page.
const OMHER_DARK: ITheme = {
  background: "#0b090d",
  foreground: "#dcd6de",
  cursor: "#f3eff4",
  cursorAccent: "#0b090d",
  selectionBackground: "#3d364066",
  selectionInactiveBackground: "#3d364044",
  black: "#1b181e",
  red: "#f08a8a",
  green: "#7fd6a4",
  yellow: "#eaaf55",
  blue: "#8cbcff",
  magenta: "#e48fd0",
  cyan: "#7fd1d6",
  white: "#dcd6de",
  brightBlack: "#6f6872",
  brightRed: "#ffa3a3",
  brightGreen: "#9be6b9",
  brightYellow: "#f5c779",
  brightBlue: "#a9ccff",
  brightMagenta: "#f0a8de",
  brightCyan: "#9de2e6",
  brightWhite: "#f3eff4",
};
const OMHER_LIGHT: ITheme = {
  background: "#ffffff",
  foreground: "#2c2630",
  cursor: "#19151b",
  cursorAccent: "#ffffff",
  selectionBackground: "#cbc4cf88",
  selectionInactiveBackground: "#cbc4cf55",
  black: "#19151b",
  red: "#c0392b",
  green: "#1f8a52",
  yellow: "#a86a00",
  blue: "#1d5fd1",
  magenta: "#a8327a",
  cyan: "#0f7f86",
  white: "#e9e5eb",
  brightBlack: "#756d7a",
  brightRed: "#d9534f",
  brightGreen: "#28a065",
  brightYellow: "#c08000",
  brightBlue: "#3a78e0",
  brightMagenta: "#c4367f",
  brightCyan: "#1b97a0",
  brightWhite: "#ffffff",
};

/** Every theme a person can pick. omher's own two come first and are the defaults. */
export const TERM_THEMES: readonly TermTheme[] = [
  { id: "omher-dark", name: "omher Dark", kind: "dark", theme: OMHER_DARK },
  { id: "omher-light", name: "omher Light", kind: "light", theme: OMHER_LIGHT },
  ...ORCA_TERM_THEMES,
];

/** The eight normal ANSI colours, in their order (a theme's swatch shows them). */
export const ANSI_NORMAL = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"] as const;
/** The eight bright ones, in the same order. */
export const ANSI_BRIGHT = ["brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite"] as const;

export const termThemeById = (id: string): TermTheme | undefined => TERM_THEMES.find((t) => t.id === id);

/** The catalog entry a terminal uses under app theme `mode`: the pick for that mode, else omher's own for it. */
export function termThemePick(mode: "dark" | "light", s: TermSettings): TermTheme {
  const picked = termThemeById(mode === "light" ? s.themeLight : s.themeDark);
  return picked ?? termThemeById(mode === "light" ? "omher-light" : "omher-dark")!;
}

/** The theme a terminal uses under app theme `mode`. */
export function termTheme(mode: "dark" | "light", s: TermSettings): ITheme {
  return termThemePick(mode, s).theme;
}

/** `#rgb`, `#rrggbb` or `#rrggbbaa` as channels 0..255; null for anything else. */
function hexRgb(color: string | undefined): [number, number, number] | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec((color ?? "").trim());
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** WCAG relative luminance of a hex colour, 0 (black) to 1 (white); null when it is not a hex colour. */
export function luminance(color: string | undefined): number | null {
  const rgb = hexRgb(color);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** How much colour a hex colour has, 0 (a grey) to 1 (HSL saturation); 0 when it is not a hex colour. */
function saturation(color: string | undefined): number {
  const rgb = hexRgb(color);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((c) => c / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  return max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
}

const HUES = ["Red", "Green", "Yellow", "Blue", "Magenta", "Cyan"] as const;
/** Below this a colour reads as a grey. */
const GREY_BELOW = 0.25;

/** Whether a theme's bright colours are its normal ones, brighter. In Solarized they are not: four of its six
 *  bright slots hold the theme's grey tones (its green's bright slot is a grey). A terminal that draws bold text in
 *  the bright slot, as xterm does by default, then shows a program's bold green as grey. False when half or more
 *  of the six coloured slots have a grey in their bright slot. */
export function brightIsBrighter(theme: ITheme): boolean {
  const t = theme as Record<string, string | undefined>;
  const greys = HUES.filter((h) => saturation(t[h.toLowerCase()]) >= GREY_BELOW && saturation(t[`bright${h}`]) < GREY_BELOW);
  return greys.length < HUES.length / 2;
}

/** A light background is one black text contrasts with at least as well as white text does (Orca's rule). A
 *  colour that cannot be read counts as dark. */
export function isLightBackground(color: string | undefined): boolean {
  const l = luminance(color);
  return l !== null && (l + 0.05) / 0.05 >= 1.05 / (l + 0.05);
}
