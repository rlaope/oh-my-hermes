// Colours for the matches find highlights, taken from the terminal's own theme so they read on every one of them:
// a match is a quiet tint of the theme's yellow over its background, the active match a much stronger mix with the
// theme's foreground as its outline, so it is the one the eye lands on. A mix is eased back toward the background until the
// theme's text is still readable on it (xterm wants plain #rrggbb here, no alpha).
import type { ITheme } from "@xterm/xterm";
import { luminance } from "./themes";

export interface FindColors {
  matchBackground: string;
  matchOverviewRuler: string;
  activeMatchBackground: string;
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
/** The least contrast the theme's text keeps on the active match. */
export const ACTIVE_TEXT_CONTRAST = 3.05;

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
  // theme's text colour (which stands out from both mixes on any theme)
  const a = readableAmount(bg, hue, fgHex, Math.min(0.95, m + 0.5), m + 0.08, Math.min(ACTIVE_TEXT_CONTRAST, target));
  const match = mix(bg, hue, m);
  const active = mix(bg, hue, a);
  return {
    matchBackground: match,
    matchOverviewRuler: match,
    activeMatchBackground: active,
    activeMatchBorder: hex(fg),
    activeMatchColorOverviewRuler: active,
  };
}
