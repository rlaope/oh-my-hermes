// Colours for the matches find highlights, taken from the terminal's own theme so they read on every one of them:
// a match is a quiet tint of the theme's yellow over its background, eased back toward the background until the
// theme's text is still readable on it. The active match is the one the eye lands on: the theme's yellow at full
// strength (its hue, saturated), made just light or dark enough for the theme's text to read on it, with the
// theme's foreground as its outline. A highlight does not recolour the text under it, and a program's yellow or
// green can sit at 1:1 on that fill, so the active match also names the colour its text is drawn in: the theme's
// text colour, moved toward black or white until it reads at 4.5:1 on the fill. (xterm wants plain #rrggbb here,
// no alpha.)
import type { ITheme } from "@xterm/xterm";
import { luminance } from "./themes";

export interface FindColors {
  matchBackground: string;
  matchOverviewRuler: string;
  activeMatchBackground: string;
  /** what the text inside the active match is drawn in, whatever colour its cell had (engine-find.ts applies it;
   *  the search add-on has no such option and ignores it) */
  activeMatchForeground: string;
  activeMatchBorder: string;
  activeMatchColorOverviewRuler: string;
}

const rgb = (hex: string | undefined): [number, number, number] | null => {
  const m = /^#([0-9a-f]{6})$/i.exec((hex ?? "").trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const hex = (c: number[]) => `#${c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
/** `amount` of `top` over `base` (0 = base). */
const mix = (base: [number, number, number], top: [number, number, number], amount: number) => hex(base.map((b, i) => b + (top[i] - b) * amount));

/** How much of the theme's yellow a plain match takes at most. Kept low so the active match, which takes as much as
 *  its text allows, is plainly the strongest thing on the screen. */
const PLAIN_AMOUNT = 0.22;
/** The active match's fill is at least this saturated, whatever the theme's yellow is. */
const ACTIVE_SATURATION = 0.85;
/** Under dark text (a light theme) the active fill is no darker than this: a deep amber, not a brown. */
const ACTIVE_LIGHTNESS_UNDER_DARK_TEXT = 0.38;
/** The least contrast the theme's text keeps on the active match. */
export const ACTIVE_TEXT_CONTRAST = 3.05;
/** The least contrast the active match's own text colour keeps on its fill. */
export const ACTIVE_FOREGROUND_CONTRAST = 4.5;

/** WCAG contrast ratio of two hex colours (1 when either is not a hex colour). */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return 1;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** How much of `hue` is mixed into the background so the theme's text, which a highlight does not recolour, still
 *  reads at `target` (down to `floor`). */
function readableAmount(bg: [number, number, number], hue: [number, number, number], fg: string, start: number, floor: number, target: number): number {
  let amount = start;
  while (amount > floor && contrastRatio(fg, mix(bg, hue, amount)) < target) amount = Math.max(floor, amount - 0.01);
  return amount;
}

/** A colour's hue (degrees) and saturation, as HSL has them. */
function hueOf([r, g, b]: [number, number, number]): { h: number; s: number } {
  const [x, y, z] = [r / 255, g / 255, b / 255];
  const max = Math.max(x, y, z);
  const min = Math.min(x, y, z);
  const d = max - min;
  if (d === 0) return { h: 0, s: 0 };
  const l = (max + min) / 2;
  const h = max === x ? ((y - z) / d) % 6 : max === y ? (z - x) / d + 2 : (x - y) / d + 4;
  return { h: (h * 60 + 360) % 360, s: d / (1 - Math.abs(2 * l - 1)) };
}
function hsl(h: number, s: number, l: number): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return hex([r, g, b].map((v) => (v + m) * 255));
}

/** The strongest fill of `hue`'s own colour the theme's text reads on at `target`: saturated, and as far from the
 *  background as the text allows. It starts as a deep amber under dark text and at the colour's full strength under
 *  light text, and moves away from the text only as far as the text needs to read. Null when the hue is a grey,
 *  which has no colour to strengthen. */
function strongFill(hue: [number, number, number], fgHex: string, bgHex: string, target: number): string | null {
  const { h, s } = hueOf(hue);
  if (s < 0.15) return null;
  const sat = Math.max(s, ACTIVE_SATURATION);
  const textIsDark = (luminance(fgHex) ?? 1) < (luminance(bgHex) ?? 0);
  for (let i = 0; i <= 55; i++) {
    const c = hsl(h, sat, textIsDark ? ACTIVE_LIGHTNESS_UNDER_DARK_TEXT + i / 100 : 0.5 - i / 100);
    if (contrastRatio(fgHex, c) >= target) return c;
  }
  return null;
}

/** The colour for the text inside the active match: the theme's text colour when that reads at `target` on the
 *  fill; otherwise that colour moved toward black or white, first the way it already leans from the fill, until it
 *  does. One of the two ends always gets there: black and white cannot both be under 4.58:1 on one colour. */
function readableOn(fill: string, fg: [number, number, number], target: number): string {
  if (contrastRatio(hex(fg), fill) >= target) return hex(fg);
  const black: [number, number, number] = [0, 0, 0];
  const white: [number, number, number] = [255, 255, 255];
  const textIsDark = (luminance(hex(fg)) ?? 1) < (luminance(fill) ?? 0);
  for (const end of textIsDark ? [black, white] : [white, black]) {
    for (let i = 1; i <= 20; i++) {
      const c = mix(fg, end, i / 20);
      if (contrastRatio(c, fill) >= target) return c;
    }
  }
  return contrastRatio("#000000", fill) >= contrastRatio("#ffffff", fill) ? "#000000" : "#ffffff";
}

export function findColors(theme: ITheme): FindColors {
  const bg = rgb(theme.background) ?? [0, 0, 0];
  const fgHex = theme.foreground ?? "#ffffff";
  const fg = rgb(fgHex) ?? [255, 255, 255];
  const hue = rgb(theme.yellow) ?? fg;
  // 4.5:1 for the text on a match; a theme whose own text is lower than that on its background (Solarized Light is
  // 4.1:1) gets a little under its own, since no highlight is more readable than the page it sits on
  const target = Math.min(4.5, Math.max(1, contrastRatio(fgHex, hex(bg)) - 0.6));
  // a plain match is a quiet tint (there can be hundreds on a screen, and dim text has to read on it too)
  const m = readableAmount(bg, hue, fgHex, PLAIN_AMOUNT, 0.08, target);
  // the active match: the strongest fill the theme's text still reads on (3:1, large-text contrast: it is one
  // word, outlined), so it stands out from the other matches instead of sitting among them; outlined in the
  // theme's text colour (which stands out from both fills on any theme). A theme with no colour in its yellow
  // gets the strongest mix instead.
  const activeTarget = Math.min(ACTIVE_TEXT_CONTRAST, target);
  const a = readableAmount(bg, hue, fgHex, Math.min(0.95, m + 0.5), m + 0.08, activeTarget);
  const match = mix(bg, hue, m);
  const active = strongFill(hue, fgHex, hex(bg), activeTarget) ?? mix(bg, hue, a);
  return {
    matchBackground: match,
    matchOverviewRuler: match,
    activeMatchBackground: active,
    activeMatchForeground: readableOn(active, fg, ACTIVE_FOREGROUND_CONTRAST),
    activeMatchBorder: hex(fg),
    activeMatchColorOverviewRuler: active,
  };
}
