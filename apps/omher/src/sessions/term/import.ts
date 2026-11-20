// Settings › Terminal › Import from… (macOS): another terminal app's profile as an omher theme. The shell reads the
// app's prefs file once, when the person presses the button, and hands back only names, `#rrggbb` colours and a font
// (term_import.rs). Here a profile becomes the custom theme omher keeps; omher never writes back to the other app and
// never reads it again by itself.
import { TERM_FONT_SIZE, cleanTermFont, type TermCustomTheme, type TermSettings } from "./settings";
import { ANSI_BRIGHT, ANSI_NORMAL } from "./themes";

export type ImportApp = "iterm2" | "terminal";
export const IMPORT_APPS: readonly ImportApp[] = ["iterm2", "terminal"];

/** One profile as the shell hands it over. */
export interface ImportProfile {
  name: string;
  /** The app's default profile (the shell puts it first). */
  default: boolean;
  /** False: a colour or the font could not be read; listed greyed out, not usable. */
  ok: boolean;
  /** The PostScript name the app keeps (`Menlo-Regular`) and the size in points. */
  font: { name: string; size: number } | null;
  colors: {
    foreground: string | null;
    background: string | null;
    cursor: string | null;
    selection: string | null;
    /** ANSI 0..15: normal, then bright. */
    ansi: (string | null)[];
  } | null;
}

const HEX = /^#[0-9a-f]{6}$/i;
const hex = (v: unknown): string | undefined => (typeof v === "string" && HEX.test(v) ? v.toLowerCase() : undefined);

/** A profile's colours as the custom theme omher keeps: the sixteen ANSI slots, foreground, background, cursor and
 *  selection. A colour the profile does not have is left out (the theme fills it from omher's own). */
export function profileTheme(p: ImportProfile): TermCustomTheme | null {
  if (!p.ok || !p.colors) return null;
  const c = p.colors;
  const colors: TermCustomTheme["colors"] = {};
  const put = (k: keyof TermCustomTheme["colors"], v: unknown) => {
    const h = hex(v);
    if (h) colors[k] = h;
  };
  put("foreground", c.foreground);
  put("background", c.background);
  put("cursor", c.cursor);
  put("selectionBackground", c.selection);
  [...ANSI_NORMAL, ...ANSI_BRIGHT].forEach((k, i) => put(k, c.ansi?.[i]));
  const name = (p.name ?? "").trim().slice(0, 80);
  return name && Object.keys(colors).length ? { name, colors } : null;
}

const STYLES = /[-_ ]?(Regular|Roman|Book|Medium|Light|Thin|ExtraLight|UltraLight|SemiBold|DemiBold|Bold|ExtraBold|Heavy|Black|Italic|Oblique|Retina|Text|Plain)+$/i;

/** The family names a PostScript font name may go by, most spaced first (the installed one is then picked):
 *  `JetBrainsMono-Regular` -> "Jet Brains Mono", "JetBrains Mono", …, "JetBrainsMono"; `Menlo-Regular` -> "Menlo";
 *  `SFMono-Regular` -> "SF Mono", "SFMono". A word break can sit at each lower-to-upper case change and each hyphen. */
export function fontFamilies(postscript: string): string[] {
  const base = postscript.trim().replace(STYLES, "").replace(/-+$/, "");
  if (!base) return [];
  // the name in words, each word break a place a space may or may not go
  const words = base
    .replace(/-/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .split(/\s+/)
    .filter(Boolean);
  const gaps = Math.min(words.length - 1, 4);
  const ways: string[] = [];
  for (let m = (1 << gaps) - 1; m >= 0; m--) {
    let name = words[0];
    for (let i = 1; i < words.length; i++) name += (i <= gaps && m & (1 << (i - 1)) ? " " : "") + words[i];
    ways.push(name);
  }
  ways.sort((x, y) => y.split(" ").length - x.split(" ").length);
  return [...new Set([...ways, postscript.trim()].map(cleanTermFont).filter(Boolean))];
}

/** What a profile's font becomes: the installed family and size to use, or `missing` (the font is not on this
 *  computer: the font settings stay as they are). */
export type ImportFont = { family: string; size: number } | { missing: string } | null;

export function profileFont(p: ImportProfile, installed: (family: string) => boolean): ImportFont {
  if (!p.font?.name) return null;
  const family = fontFamilies(p.font.name).find(installed);
  if (!family) return { missing: p.font.name };
  const size = Math.round(Math.min(TERM_FONT_SIZE.max, Math.max(TERM_FONT_SIZE.min, p.font.size || 13)) * 2) / 2;
  return { family, size };
}

/** What "Use" writes: the custom theme, picked for the app theme being chosen for, and the font when it is here. */
export function importPatch(theme: TermCustomTheme, font: ImportFont, slot: "dark" | "light"): Partial<TermSettings> {
  const patch: Partial<TermSettings> = { custom: theme, ...(slot === "light" ? { themeLight: "custom" } : { themeDark: "custom" }) };
  if (font && "family" in font) Object.assign(patch, { fontFamily: font.family, fontSize: font.size });
  return patch;
}

/** Whether `family` is a font on this computer: text in it measures differently from text in each of three
 *  generic fallbacks (a missing family falls back to the generic and measures the same). */
export function fontInstalled(family: string): boolean {
  if (typeof document === "undefined") return false;
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return false;
  const sample = "mmmmmmmmmmlli10OQ@#";
  const width = (font: string) => {
    ctx.font = `72px ${font}`;
    return ctx.measureText(sample).width;
  };
  const name = `"${family.replace(/"/g, "")}"`;
  return ["monospace", "serif", "sans-serif"].some((g) => width(`${name}, ${g}`) !== width(g));
}
