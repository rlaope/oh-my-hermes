import { describe, expect, it } from "vitest";
import { ACTIVE_FOREGROUND_CONTRAST, contrastRatio, findColors } from "./find-colors";
import { TERM_THEMES, luminance } from "./themes";

/** 4.5:1, or a little under the theme's own text-on-background ratio when that is lower (Solarized Light: 4.1:1). */
const target = (fg: string, bg: string) => Math.min(4.5, contrastRatio(fg, bg) - 0.6);

describe("find colours come from the terminal's own theme", () => {
  it("every theme: the theme's text stays readable on a match (4.5:1, or just under the theme's own ratio); the active match is outlined in its own text colour", () => {
    expect(TERM_THEMES.length).toBeGreaterThanOrEqual(38);
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      const fg = th.theme.foreground!;
      const bg = th.theme.background!;
      expect(contrastRatio(fg, c.matchBackground), `${th.name}: text on a match`).toBeGreaterThanOrEqual(target(fg, bg) - 0.03);
      expect(contrastRatio(c.activeMatchBorder, c.activeMatchBackground), `${th.name}: the outline on the active match`).toBeGreaterThanOrEqual(7);
      expect(c.activeMatchBorder, th.name).toBe(c.activeMatchForeground);
      expect(c.activeMatchBackground, `${th.name}: the active match is not a plain match`).not.toBe(c.matchBackground);
      for (const v of Object.values(c)) expect(v, th.name).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("every theme: the colour the active match's text is drawn in reads at 7:1 on its fill, where the theme's own yellow and green often do not", () => {
    expect(ACTIVE_FOREGROUND_CONTRAST).toBe(7);
    expect(TERM_THEMES.length).toBeGreaterThanOrEqual(38);
    let unreadable = 0;
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      expect(c.activeMatchForeground, th.name).toMatch(/^#[0-9a-f]{6}$/);
      expect(contrastRatio(c.activeMatchForeground, c.activeMatchBackground), `${th.name}: the active match's text on its fill`).toBeGreaterThanOrEqual(7);
      // what a cell's own colour would give: the reason the match names its text colour
      if (Math.min(contrastRatio(th.theme.yellow!, c.activeMatchBackground), contrastRatio(th.theme.green!, c.activeMatchBackground)) < 4.5) unreadable += 1;
    }
    expect(unreadable).toBeGreaterThan(30);
    // One Light: its yellow is all but the fill itself
    const one = TERM_THEMES.find((t) => t.id === "one-light")!;
    expect(contrastRatio(one.theme.yellow!, findColors(one.theme).activeMatchBackground)).toBeLessThan(1.2);
  });

  it("every theme, dark or light: the active match is a ground for dark text, and stands at least 2:1 from the background", () => {
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      expect(luminance(c.activeMatchForeground)!, `${th.name}: the active match's text is the darker of the two`).toBeLessThan(luminance(c.activeMatchBackground)!);
      // 7:1 under black is a luminance of 0.30: a mid amber, never a brown close to a dark theme's background
      expect(luminance(c.activeMatchBackground)!, th.name).toBeGreaterThanOrEqual(0.3);
      expect(luminance(c.activeMatchBackground)!, th.name).toBeLessThan(0.36);
      expect(contrastRatio(c.activeMatchBackground, th.theme.background!), `${th.name}: the active fill against the background`).toBeGreaterThanOrEqual(1.95);
    }
  });

  it("a match can be told from the background on every theme, the active one more than a plain one", () => {
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      const bg = th.theme.background!;
      const m = contrastRatio(c.matchBackground, bg);
      const a = contrastRatio(c.activeMatchBackground, bg);
      expect(m, `${th.name}: match vs background`).toBeGreaterThan(1.1);
      expect(a, `${th.name}: active vs background`).toBeGreaterThan(m);
    }
  });

  it("the active match is the one the eye lands on: its fill is apart from a plain match's and stands well further from the background, on every theme", () => {
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      const bg = th.theme.background!;
      const plain = contrastRatio(c.matchBackground, bg) - 1;
      const active = contrastRatio(c.activeMatchBackground, bg) - 1;
      expect(active, `${th.name}: the active fill against the background, beside a plain match's`).toBeGreaterThanOrEqual(plain * 1.5);
      expect(contrastRatio(c.activeMatchBackground, c.matchBackground), `${th.name}: active against plain`).toBeGreaterThanOrEqual(1.15);
    }
  });

  it("the colours follow the theme: a dark and a light theme get different ones, and no one pair is hard-coded", () => {
    const dark = TERM_THEMES.find((t) => t.kind === "dark")!;
    const light = TERM_THEMES.find((t) => t.kind === "light")!;
    expect(findColors(dark.theme).matchBackground).not.toBe(findColors(light.theme).matchBackground);
    expect(new Set(TERM_THEMES.map((t) => findColors(t.theme).matchBackground)).size).toBeGreaterThan(10);
  });

  it("a theme without a yellow or with a missing background still gets valid colours", () => {
    const c = findColors({ foreground: "#cccccc" });
    for (const v of Object.values(c)) expect(v).toMatch(/^#[0-9a-f]{6}$/);
  });
});
