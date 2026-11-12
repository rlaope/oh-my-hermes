// Colours for the matches find highlights, taken from the terminal's own theme so they read on every one of them:
// a match is the theme's yellow mixed into its background, the active match a stronger mix with the theme's
// foreground as its outline. A mix is eased back toward the background until the theme's text is still readable on
// it (xterm wants plain #rrggbb here, no alpha).
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
  const m = readableAmount(bg, hue, fgHex, 0.38, 0.08, target);
  // the active match: one step stronger than the others, as far as its text stays readable, and outlined in the
  // theme's text colour (which stands out from both mixes on any theme)
  const a = readableAmount(bg, hue, fgHex, Math.min(0.7, m + 0.2), m + 0.08, target - 0.4);
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
