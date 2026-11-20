import { beforeEach, describe, expect, it } from "vitest";
import { fontFamilies, importPatch, profileFont, profileTheme, type ImportProfile } from "./import";
import { parseTermSettings, readTermSettings, resetTermSettings, TERM_DEFAULTS, TERM_KEY, writeTermSettings } from "./settings";
import { ANSI_BRIGHT, ANSI_NORMAL, CUSTOM_THEME_ID, termTheme, termThemePick } from "./themes";

const ANSI = Array.from({ length: 16 }, (_, i) => `#${(i * 16).toString(16).padStart(2, "0")}${(255 - i * 16).toString(16).padStart(2, "0")}40`);
const PROFILE: ImportProfile = {
  name: "Harbor Night",
  default: true,
  ok: true,
  font: { name: "JetBrainsMono-Regular", size: 14 },
  colors: { foreground: "#D8DEE9", background: "#14202b", cursor: "#f5c779", selection: "#2e4a62", ansi: ANSI },
};

describe("import from iTerm2 / Apple Terminal", () => {
  beforeEach(() => {
    const kept = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
      removeItem: (k: string) => void kept.delete(k),
    };
    resetTermSettings();
  });

  it("maps the 16 ANSI colours, foreground, background, cursor and selection onto the theme's slots", () => {
    const th = profileTheme(PROFILE)!;
    expect(th.name).toBe("Harbor Night");
    [...ANSI_NORMAL, ...ANSI_BRIGHT].forEach((k, i) => expect(th.colors[k], k).toBe(ANSI[i]));
    expect(th.colors.foreground).toBe("#d8dee9");
    expect(th.colors.background).toBe("#14202b");
    expect(th.colors.cursor).toBe("#f5c779");
    expect(th.colors.selectionBackground).toBe("#2e4a62");
    // a profile that could not be read gives no theme
    expect(profileTheme({ ...PROFILE, ok: false, colors: null })).toBeNull();
    // anything that is not #rrggbb is dropped, not passed on
    expect(profileTheme({ ...PROFILE, colors: { ...PROFILE.colors!, foreground: "red;}", ansi: [] } })!.colors.foreground).toBeUndefined();
  });

  it("the custom theme persists, is the one a terminal uses, and fills slots it lacks from omher's own", () => {
    const th = profileTheme({ ...PROFILE, colors: { ...PROFILE.colors!, ansi: ANSI.slice(0, 8) } })!;
    writeTermSettings(importPatch(th, null, "dark"));
    const stored = JSON.parse(localStorage.getItem(TERM_KEY)!);
    expect(stored.themeDark).toBe(CUSTOM_THEME_ID);
    expect(stored.custom.name).toBe("Harbor Night");
    resetTermSettings();
    const s = readTermSettings();
    expect(s.custom).toEqual(th);
    const theme = termTheme("dark", s);
    expect(theme.background).toBe("#14202b");
    expect(theme.red).toBe(ANSI[1]);
    expect(theme.brightRed).toBe("#ffa3a3"); // omher Dark's
    expect(theme.cursorAccent).toBe("#14202b");
    expect(termThemePick("dark", s)).toMatchObject({ id: CUSTOM_THEME_ID, name: "Harbor Night", kind: "dark" });
    // the light slot keeps its own pick
    expect(termThemePick("light", s).id).toBe("omher-light");
    // a stored "custom" with no theme behind it falls back to omher's own
    expect(termThemePick("dark", parseTermSettings({ themeDark: "custom" })).id).toBe("omher-dark");
    // a tampered stored theme keeps only #rrggbb colours
    expect(parseTermSettings({ custom: { name: "x", colors: { background: "url(x)", red: "#AABBCC", bogus: "#000000" } } }).custom).toEqual({ name: "x", colors: { red: "#aabbcc" } });
    expect(TERM_DEFAULTS.custom).toBeNull();
  });

  it("uses the profile's font when it is installed, and keeps the current font when it is not", () => {
    const here = new Set(["JetBrains Mono", "Menlo"]);
    const font = profileFont(PROFILE, (f) => here.has(f));
    expect(font).toEqual({ family: "JetBrains Mono", size: 14 });
    expect(importPatch(profileTheme(PROFILE)!, font, "light")).toMatchObject({ themeLight: "custom", fontFamily: "JetBrains Mono", fontSize: 14 });

    writeTermSettings({ fontFamily: "Iosevka", fontSize: 15 });
    const missing = profileFont({ ...PROFILE, font: { name: "NoSuchFont-Bold", size: 11 } }, (f) => here.has(f));
    expect(missing).toEqual({ missing: "NoSuchFont-Bold" });
    const after = writeTermSettings(importPatch(profileTheme(PROFILE)!, missing, "dark"));
    expect(after.fontFamily).toBe("Iosevka");
    expect(after.fontSize).toBe(15);
    expect(after.themeDark).toBe("custom");
    // sizes are kept to the page's range
    expect(profileFont({ ...PROFILE, font: { name: "Menlo-Regular", size: 40 } }, (f) => here.has(f))).toEqual({ family: "Menlo", size: 24 });
    expect(profileFont({ ...PROFILE, font: null }, () => true)).toBeNull();
  });

  it("finds the family a PostScript name belongs to", () => {
    expect(fontFamilies("JetBrainsMono-Regular")).toEqual(["Jet Brains Mono", "JetBrains Mono", "Jet BrainsMono", "JetBrainsMono", "JetBrainsMono-Regular"]);
    expect(fontFamilies("Menlo-Regular")[0]).toBe("Menlo");
    expect(fontFamilies("SFMono-Regular")).toContain("SF Mono");
    expect(fontFamilies("FiraCode-Retina")[0]).toBe("Fira Code");
    expect(fontFamilies("")).toEqual([]);
    expect(fontFamilies("Monaco")[0]).toBe("Monaco");
  });
});
