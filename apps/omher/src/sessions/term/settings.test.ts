import { beforeEach, describe, expect, it } from "vitest";
import { cleanTermFont, onTermSettings, parseTermSettings, readTermSettings, resetTermSettings, TERM_DEFAULTS, TERM_KEY, TERM_SCROLLBACKS, writeTermSettings } from "./settings";

describe("terminal settings", () => {
  beforeEach(() => {
    const kept = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
      removeItem: (k: string) => void kept.delete(k),
    };
    resetTermSettings();
  });

  it("nothing stored reads as the defaults a terminal had before there were settings", () => {
    expect(readTermSettings()).toEqual(TERM_DEFAULTS);
    expect(TERM_DEFAULTS).toMatchObject({ fontSize: 12.5, lineHeight: 1.2, cursorBlink: true, scrollback: 5000, gpu: "auto" });
  });

  it("a stored value of the wrong type or out of range falls back or is clamped, field by field", () => {
    const s = parseTermSettings(JSON.stringify({ fontSize: 400, lineHeight: "big", scrollback: 12, gpu: "turbo", themeDark: 7, cursorBlink: "yes", fontFamily: "Menlo" }));
    expect(s).toEqual({ ...TERM_DEFAULTS, fontSize: 24, scrollback: 1000, fontFamily: "Menlo" });
    for (const bad of ["", "{", "[]", "null", "42"]) expect(parseTermSettings(bad)).toEqual(TERM_DEFAULTS);
  });

  it("the look options added with the Terminal page default to what a terminal did before them", () => {
    // a block cursor, 4.5:1 contrast everywhere, the 14 6 8 16 padding (16 is its left side), Option as Meta
    expect(TERM_DEFAULTS).toMatchObject({ cursorStyle: "block", contrast: "high", padding: 16, optionIsMeta: true, themeDark: "omher-dark", themeLight: "omher-light", fontFamily: "" });
    // settings saved before these fields existed read as those defaults
    const old = { themeDark: "omher-dark", themeLight: "omher-light", fontFamily: "", fontSize: 14, lineHeight: 1.2, cursorBlink: false, scrollback: 5000, gpu: "off" };
    expect(parseTermSettings(JSON.stringify(old))).toEqual({ ...TERM_DEFAULTS, fontSize: 14, cursorBlink: false, gpu: "off" });
    expect(TERM_SCROLLBACKS).toEqual([5000, 10000, 25000, 50000]);
  });

  it("cursor style: one of block, bar, underline; anything else is the default", () => {
    for (const ok of ["block", "bar", "underline"]) expect(parseTermSettings({ cursorStyle: ok }).cursorStyle).toBe(ok);
    for (const bad of ["beam", "", 1, null, true, ["bar"]]) expect(parseTermSettings({ cursorStyle: bad }).cursorStyle).toBe("block");
    expect(parseTermSettings({}).cursorStyle).toBe("block");
  });

  it("contrast: one of auto, high, theme; anything else is the default", () => {
    for (const ok of ["auto", "high", "theme"]) expect(parseTermSettings({ contrast: ok }).contrast).toBe(ok);
    for (const bad of ["low", "", 4.5, null, false]) expect(parseTermSettings({ contrast: bad }).contrast).toBe("high");
    expect(parseTermSettings({}).contrast).toBe("high");
  });

  it("padding: a whole number from 0 to 24; out of range is clamped, a wrong type is the default", () => {
    expect(parseTermSettings({ padding: 0 }).padding).toBe(0);
    expect(parseTermSettings({ padding: 24 }).padding).toBe(24);
    expect(parseTermSettings({ padding: 7.6 }).padding).toBe(8);
    expect(parseTermSettings({ padding: -3 }).padding).toBe(0);
    expect(parseTermSettings({ padding: 400 }).padding).toBe(24);
    for (const bad of ["8", null, NaN, Infinity, true]) expect(parseTermSettings({ padding: bad }).padding).toBe(16);
    expect(parseTermSettings({}).padding).toBe(16);
  });

  it("Option as Meta: a boolean; anything else is the default (on)", () => {
    expect(parseTermSettings({ optionIsMeta: false }).optionIsMeta).toBe(false);
    expect(parseTermSettings({ optionIsMeta: true }).optionIsMeta).toBe(true);
    for (const bad of ["no", 0, null]) expect(parseTermSettings({ optionIsMeta: bad }).optionIsMeta).toBe(true);
    expect(parseTermSettings({}).optionIsMeta).toBe(true);
  });

  it("copy on select and right-click paste: booleans, off by default; anything else is the default (off)", () => {
    expect(TERM_DEFAULTS).toMatchObject({ copyOnSelect: false, rightClickPaste: false });
    expect(parseTermSettings({ copyOnSelect: true, rightClickPaste: true })).toMatchObject({ copyOnSelect: true, rightClickPaste: true });
    expect(parseTermSettings({ copyOnSelect: false, rightClickPaste: false })).toMatchObject({ copyOnSelect: false, rightClickPaste: false });
    for (const bad of ["yes", 1, null, [true], {}]) {
      expect(parseTermSettings({ copyOnSelect: bad }).copyOnSelect).toBe(false);
      expect(parseTermSettings({ rightClickPaste: bad }).rightClickPaste).toBe(false);
    }
    // settings saved before these fields existed read as off: nothing changes for people today
    const old = { themeDark: "dracula", fontSize: 14, gpu: "off", optionIsMeta: false };
    expect(parseTermSettings(JSON.stringify(old))).toMatchObject({ copyOnSelect: false, rightClickPaste: false });
    // one does not switch the other
    expect(writeTermSettings({ copyOnSelect: true })).toMatchObject({ copyOnSelect: true, rightClickPaste: false });
    expect(writeTermSettings({ rightClickPaste: true })).toMatchObject({ copyOnSelect: true, rightClickPaste: true });
  });

  it("font size 9 to 24, line height 1 to 2, scrollback 1,000 to 50,000 rows: clamped, or the default for a wrong type", () => {
    expect(parseTermSettings({ fontSize: 2, lineHeight: 0.4, scrollback: 9e9 })).toMatchObject({ fontSize: 9, lineHeight: 1, scrollback: 50000 });
    expect(parseTermSettings({ fontSize: 99, lineHeight: 7, scrollback: 25000.4 })).toMatchObject({ fontSize: 24, lineHeight: 2, scrollback: 25000 });
    expect(parseTermSettings({ fontSize: "16", lineHeight: null, scrollback: "many" })).toMatchObject({ fontSize: 12.5, lineHeight: 1.2, scrollback: 5000 });
  });

  it("a font name keeps only what a font name is made of, and a theme id of the wrong type is omher's own", () => {
    expect(cleanTermFont(`"Fira Code", Menlo-Regular, D2Coding 가`)).toBe(`"Fira Code", Menlo-Regular, D2Coding 가`);
    expect(cleanTermFont("Menlo; } body { display: none")).toBe("Menlo  body  display none");
    expect(cleanTermFont("x".repeat(500))).toHaveLength(200);
    expect(parseTermSettings({ fontFamily: "Menlo;{}<>()\\" }).fontFamily).toBe("Menlo");
    expect(parseTermSettings({ fontFamily: 12 }).fontFamily).toBe("");
    expect(parseTermSettings({ fontFamily: "y".repeat(201) }).fontFamily).toBe("");
    expect(parseTermSettings({ themeDark: "", themeLight: null })).toMatchObject({ themeDark: "omher-dark", themeLight: "omher-light" });
    expect(parseTermSettings({ themeDark: "dracula", themeLight: "solarized-light" })).toMatchObject({ themeDark: "dracula", themeLight: "solarized-light" });
  });

  it("a change is saved, read back after a restart, and handed to listeners until they leave", () => {
    const seen: number[] = [];
    const off = onTermSettings((s) => seen.push(s.fontSize));
    expect(writeTermSettings({ fontSize: 14, gpu: "off" })).toMatchObject({ fontSize: 14, gpu: "off" });
    off();
    writeTermSettings({ fontSize: 15 });
    expect(seen).toEqual([14]);
    resetTermSettings();
    expect(JSON.parse(localStorage.getItem(TERM_KEY) ?? "{}")).toMatchObject({ fontSize: 15, gpu: "off" });
    expect(readTermSettings()).toMatchObject({ fontSize: 15, gpu: "off" });
  });
});
