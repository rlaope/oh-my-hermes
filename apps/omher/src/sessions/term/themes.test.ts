import { describe, expect, it } from "vitest";
import { TERM_DEFAULTS } from "./settings";
import { ANSI_BRIGHT, ANSI_NORMAL, isLightBackground, luminance, TERM_THEMES, termTheme, termThemeById, termThemePick } from "./themes";
import { ORCA_TERM_THEMES } from "./themes-orca";

// Every palette in Orca's five theme files (in its catalog's order), then the five its GitHub theme plugin names.
const ORCA_NAMES = [
  "Ghostty Default Style Dark",
  "Builtin Tango Light",
  "Dracula",
  "One Dark",
  "Nord",
  "Monokai",
  "Tokyo Night",
  "Gruvbox Dark",
  "Catppuccin Mocha",
  "Solarized Dark",
  "Material Dark",
  "Ayu Dark",
  "Nightfox",
  "Kanagawa",
  "Rose Pine",
  "Everforest Dark",
  "Palenight",
  "Horizon Dark",
  "Night Owl",
  "Slatewave",
  "Solarized Light",
  "One Light",
  "Catppuccin Latte",
  "GitHub Light",
  "Rose Pine Dawn",
  "Gruvbox Light",
  "Tokyo Night Light",
  "Everforest Light",
  "Tango Dark",
  "Homebrew",
  "Snazzy",
  "GitHub Light Default",
  "GitHub Light High Contrast",
  "GitHub Dark Default",
  "GitHub Dark High Contrast",
  "GitHub Dark Dimmed",
];
const HEX = /^#(?:[0-9a-f]{6}|[0-9a-f]{8})$/;

describe("terminal theme catalog", () => {
  it("holds omher's own two first, then every Orca theme by name: 38 in all", () => {
    expect(ORCA_NAMES).toHaveLength(36);
    expect(ORCA_TERM_THEMES.map((t) => t.name)).toEqual(ORCA_NAMES);
    expect(TERM_THEMES.map((t) => t.name)).toEqual(["omher Dark", "omher Light", ...ORCA_NAMES]);
    expect(TERM_THEMES).toHaveLength(38);
    expect(TERM_THEMES.filter((t) => t.kind === "dark")).toHaveLength(26);
    expect(TERM_THEMES.filter((t) => t.kind === "light")).toHaveLength(12);
  });

  it("gives every theme its own id and name", () => {
    expect(new Set(TERM_THEMES.map((t) => t.id)).size).toBe(TERM_THEMES.length);
    expect(new Set(TERM_THEMES.map((t) => t.name)).size).toBe(TERM_THEMES.length);
    for (const t of TERM_THEMES) expect(t.id, t.name).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  it("gives every theme a background, a foreground and all 16 ANSI colours as hex, and no colour that is not hex", () => {
    for (const t of TERM_THEMES) {
      const colours = t.theme as Record<string, unknown>;
      for (const k of ["background", "foreground", ...ANSI_NORMAL, ...ANSI_BRIGHT]) expect(colours[k], `${t.name} ${k}`).toMatch(HEX);
      for (const [k, v] of Object.entries(colours)) expect(v, `${t.name} ${k}`).toMatch(HEX);
    }
    expect([...ANSI_NORMAL, ...ANSI_BRIGHT]).toHaveLength(16);
  });

  it("calls a theme light or dark by its background's luminance", () => {
    for (const t of TERM_THEMES) expect(isLightBackground(t.theme.background) ? "light" : "dark", t.name).toBe(t.kind);
  });

  it("keeps the colour keys Orca gives beyond the palette: the cursor, its accent and the selection's two", () => {
    const orca = (name: string) => ORCA_TERM_THEMES.find((t) => t.name === name)!.theme;
    expect(orca("Dracula")).toMatchObject({ background: "#282a36", foreground: "#f8f8f2", cursor: "#f8f8f2", cursorAccent: "#282a36", selectionBackground: "#44475a", selectionForeground: "#f8f8f2" });
    expect(orca("Solarized Light")).toMatchObject({ background: "#fdf6e3" });
    // each of the 31 catalog themes carries all four; the GitHub palettes carry what their files do
    for (const t of ORCA_TERM_THEMES.slice(0, 31)) for (const k of ["cursor", "cursorAccent", "selectionBackground", "selectionForeground"]) expect((t.theme as Record<string, unknown>)[k], `${t.name} ${k}`).toMatch(HEX);
    expect(orca("GitHub Dark Default")).toMatchObject({ background: "#010409", cursor: "#2f81f7" });
    expect(orca("GitHub Dark Default").selectionBackground).toBeUndefined();
    expect(orca("GitHub Light High Contrast")).toMatchObject({ selectionBackground: "#0e1116" });
  });

  it("a terminal uses the pick for the app theme in force, and omher's own when the pick is unknown", () => {
    expect(termThemePick("dark", TERM_DEFAULTS).id).toBe("omher-dark");
    expect(termThemePick("light", TERM_DEFAULTS).id).toBe("omher-light");
    const s = { ...TERM_DEFAULTS, themeDark: "dracula", themeLight: "solarized-light" };
    expect(termTheme("dark", s).background).toBe("#282a36");
    expect(termTheme("light", s).background).toBe("#fdf6e3");
    // either pick may be a theme of the other kind
    expect(termTheme("light", { ...s, themeLight: "dracula" }).background).toBe("#282a36");
    expect(termThemePick("dark", { ...s, themeDark: "gone" }).id).toBe("omher-dark");
    expect(termThemePick("light", { ...s, themeLight: "gone" }).id).toBe("omher-light");
    expect(termThemeById("gone")).toBeUndefined();
  });

  it("reads luminance from 3, 6 and 8 digit hex and nothing else", () => {
    expect(luminance("#000000")).toBe(0);
    expect(luminance("#ffffff")).toBeCloseTo(1, 6);
    expect(luminance("#fff")).toBeCloseTo(1, 6);
    expect(luminance("#ffffff80")).toBeCloseTo(1, 6);
    for (const bad of [undefined, "", "white", "#12", "rgb(0 0 0)"]) expect(luminance(bad)).toBeNull();
    // the split is where black text and white text contrast equally (luminance about 0.179)
    expect(isLightBackground("#777777")).toBe(true);
    expect(isLightBackground("#757575")).toBe(false);
    expect(isLightBackground(undefined)).toBe(false);
  });
});
