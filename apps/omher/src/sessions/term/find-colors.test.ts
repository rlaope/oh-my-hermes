import { describe, expect, it } from "vitest";
import { contrastRatio, findColors } from "./find-colors";
import { TERM_THEMES } from "./themes";

/** 4.5:1, or a little under the theme's own text-on-background ratio when that is lower (Solarized Light: 4.1:1). */
const target = (fg: string, bg: string) => Math.min(4.5, contrastRatio(fg, bg) - 0.6);

describe("find colours come from the terminal's own theme", () => {
  it("every theme: the theme's text stays readable on a match (4.5:1, or just under the theme's own ratio) and on the active match (3:1 or better, and outlined)", () => {
    expect(TERM_THEMES.length).toBeGreaterThanOrEqual(38);
    for (const th of TERM_THEMES) {
      const c = findColors(th.theme);
      const fg = th.theme.foreground!;
      const bg = th.theme.background!;
      expect(contrastRatio(fg, c.matchBackground), `${th.name}: text on a match`).toBeGreaterThanOrEqual(target(fg, bg) - 0.03);
      expect(contrastRatio(fg, c.activeMatchBackground), `${th.name}: text on the active match`).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(c.activeMatchBorder, c.activeMatchBackground), `${th.name}: the outline on the active match`).toBeGreaterThanOrEqual(3);
      expect(c.activeMatchBorder, th.name).toBe(fg.toLowerCase());
      expect(c.activeMatchBackground, `${th.name}: the active match is not a plain match`).not.toBe(c.matchBackground);
      for (const v of Object.values(c)) expect(v, th.name).toMatch(/^#[0-9a-f]{6}$/);
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
