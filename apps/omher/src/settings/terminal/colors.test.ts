import { beforeEach, describe, expect, it } from "vitest";
import { cleanHex, parseTermSettings, readTermSettings, resetTermSettings, TERM_DEFAULTS, TERM_KEY, writeTermSettings } from "../../sessions/term/settings";
import { EDITED_THEME_ID, TERM_THEMES, termThemeById, termThemePick, themeBorder } from "../../sessions/term/themes";
import { editPatch, resetPatch } from "./TermColors";

describe("Customize colours", () => {
  let kept: Map<string, string>;
  beforeEach(() => {
    kept = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
      removeItem: (k: string) => void kept.delete(k),
    };
    resetTermSettings();
  });

  const edit = (mode: "dark" | "light", key: Parameters<typeof editPatch>[3], hex: string) => {
    const s = readTermSettings();
    return writeTermSettings(editPatch(mode, termThemePick(mode, s), s, key, hex));
  };

  it("a hex field takes #rrggbb (the # optional, any case) and nothing else", () => {
    expect(cleanHex("#FF5F5F")).toBe("#ff5f5f");
    expect(cleanHex(" 00aa11 ")).toBe("#00aa11");
    for (const bad of ["#fff", "#ff5f5", "#ff5f5f00", "red", "#gg0000", "", "rgb(1,2,3)"]) expect(cleanHex(bad)).toBeNull();
  });

  it("nothing edited reads as before: no edit set for either app theme", () => {
    expect(TERM_DEFAULTS.edits).toEqual({ dark: null, light: null });
    expect(parseTermSettings(null).edits).toEqual({ dark: null, light: null });
  });

  it("an edit starts from the theme in force, is picked as the edited theme, and survives a reload (save and read back)", () => {
    edit("dark", "red", "#123456");
    edit("dark", "border", "#abcdef");
    resetTermSettings(); // a reload: read again from storage
    const s = readTermSettings();
    expect(JSON.parse(kept.get(TERM_KEY)!).edits.dark).toEqual({ base: "omher-dark", colors: { red: "#123456", border: "#abcdef" } });
    expect(s.themeDark).toBe(EDITED_THEME_ID);
    const th = termThemePick("dark", s);
    expect(th.id).toBe(EDITED_THEME_ID);
    expect(th.theme.red).toBe("#123456");
    // the other colours are the base theme's
    expect(th.theme.green).toBe(termThemeById("omher-dark")!.theme.green);
    expect(themeBorder(th.theme)).toBe("#abcdef");
    // the border is no xterm colour
    expect((th.theme as Record<string, unknown>).border).toBeUndefined();
  });

  it("editing for the light app theme edits the light set only; the dark one keeps its theme", () => {
    edit("light", "red", "#aa0000");
    const s = readTermSettings();
    expect(s.edits.light?.colors.red).toBe("#aa0000");
    expect(s.edits.dark).toBeNull();
    expect(s.themeDark).toBe("omher-dark");
    expect(termThemePick("light", s).theme.red).toBe("#aa0000");
    expect(termThemePick("dark", s).theme.red).toBe(termThemeById("omher-dark")!.theme.red);
    // and a dark edit leaves the light set as it was
    edit("dark", "blue", "#0000aa");
    expect(readTermSettings().edits.light).toEqual({ base: "omher-light", colors: { red: "#aa0000" } });
  });

  it("Reset goes back to the theme the edits started from and drops them", () => {
    // a catalog light theme other than omher's own
    const tokyo = TERM_THEMES.find((th) => th.kind === "light" && th.id !== "omher-light")!;
    writeTermSettings({ themeLight: tokyo.id });
    edit("light", "foreground", "#111111");
    edit("light", "cursor", "#222222");
    let s = readTermSettings();
    expect(s.edits.light?.base).toBe(tokyo.id);
    s = writeTermSettings(resetPatch("light", s));
    expect(s.edits.light).toBeNull();
    expect(s.themeLight).toBe(tokyo.id);
    expect(termThemePick("light", s).theme).toEqual(tokyo.theme);
  });

  it("a stored edit set is checked: a bad colour or key is dropped, no base is none", () => {
    const s = parseTermSettings({ themeDark: "edited", edits: { dark: { base: "omher-dark", colors: { red: "#ZZ0000", blue: "#0000FF", nope: "#ffffff" } }, light: { colors: { red: "#ff0000" } } } });
    expect(s.edits.dark).toEqual({ base: "omher-dark", colors: { blue: "#0000ff" } });
    expect(s.edits.light).toBeNull();
    // `edited` picked with no set falls back to omher's own
    expect(termThemePick("light", { ...s, themeLight: "edited" }).id).toBe("omher-light");
  });
});
