import { beforeEach, describe, expect, it } from "vitest";
import { onTermSettings, parseTermSettings, readTermSettings, resetTermSettings, TERM_DEFAULTS, TERM_KEY, writeTermSettings } from "./settings";

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
