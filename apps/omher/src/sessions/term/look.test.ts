import { describe, expect, it } from "vitest";
import type { Terminal } from "@xterm/xterm";
import { applyLook, DARK_BG_MIN_CONTRAST, LIGHT_BG_MIN_CONTRAST, termContrast, termFont, termOptions } from "./look";
import { SAMPLE_COLS, SAMPLE_ROWS, SAMPLE_SELECT, SAMPLE_WIDE_COLS, termSample } from "./look-sample";
import { TERM_DEFAULTS, type TermSettings } from "./settings";
import { TERM_THEMES, termThemeById } from "./themes";

const dark = termThemeById("omher-dark")!.theme;
const light = termThemeById("omher-light")!.theme;

describe("a terminal's look", () => {
  it("with nothing changed, a terminal starts with the options it had before there were settings", () => {
    expect(termOptions(dark, TERM_DEFAULTS)).toEqual({
      fontFamily: "monospace",
      fontSize: 12.5,
      lineHeight: 1.2,
      cursorStyle: "block",
      cursorInactiveStyle: "outline",
      cursorBlink: true,
      allowProposedApi: true,
      scrollback: 5000,
      minimumContrastRatio: 4.5,
      drawBoldTextInBrightColors: true,
      macOptionIsMeta: true,
      theme: dark,
    });
  });

  it("bold text takes the theme's bright colour, except on a theme whose bright slots are greys (Solarized), where it keeps its own", () => {
    for (const th of TERM_THEMES) {
      const keeps = th.id === "solarized-dark" || th.id === "solarized-light";
      expect(termOptions(th.theme, TERM_DEFAULTS).drawBoldTextInBrightColors, th.name).toBe(!keeps);
    }
    // an open terminal takes it with the theme
    const options: Record<string, unknown> = {};
    const term = { options } as unknown as Terminal;
    applyLook(term, termThemeById("solarized-light")!.theme, TERM_DEFAULTS);
    expect(options.drawBoldTextInBrightColors).toBe(false);
    applyLook(term, termThemeById("dracula")!.theme, TERM_DEFAULTS);
    expect(options.drawBoldTextInBrightColors).toBe(true);
  });

  it("maps every setting to its xterm option", () => {
    const s: TermSettings = {
      ...TERM_DEFAULTS,
      fontFamily: "Menlo",
      fontSize: 16,
      lineHeight: 1.5,
      cursorStyle: "bar",
      cursorBlink: false,
      scrollback: 25000,
      contrast: "theme",
      optionIsMeta: false,
    };
    expect(termOptions(light, s)).toMatchObject({
      fontFamily: '"Menlo", monospace',
      fontSize: 16,
      lineHeight: 1.5,
      cursorStyle: "bar",
      cursorInactiveStyle: "bar",
      cursorBlink: false,
      scrollback: 25000,
      minimumContrastRatio: 1,
      macOptionIsMeta: false,
      theme: light,
    });
    expect(termOptions(dark, { ...s, cursorStyle: "underline" })).toMatchObject({ cursorStyle: "underline", cursorInactiveStyle: "underline" });
  });

  it("minimum contrast follows the background: 4.5 on a light one, 3 on a dark one; High is 4.5 and As the theme is 1", () => {
    expect([LIGHT_BG_MIN_CONTRAST, DARK_BG_MIN_CONTRAST]).toEqual([4.5, 3]);
    expect(termContrast("#ffffff", "auto")).toBe(4.5);
    expect(termContrast("#fdf6e3", "auto")).toBe(4.5);
    expect(termContrast("#0b090d", "auto")).toBe(3);
    expect(termContrast("#282a36", "auto")).toBe(3);
    // a background that cannot be read counts as dark
    expect(termContrast(undefined, "auto")).toBe(3);
    for (const bg of ["#ffffff", "#0b090d", undefined]) {
      expect(termContrast(bg, "high")).toBe(4.5);
      expect(termContrast(bg, "theme")).toBe(1);
    }
    // by the theme's background, not by the app theme: every catalog theme gets the floor its kind calls for
    for (const t of TERM_THEMES) expect(termOptions(t.theme, { ...TERM_DEFAULTS, contrast: "auto" }).minimumContrastRatio, t.name).toBe(t.kind === "light" ? 4.5 : 3);
  });

  it("puts the person's fonts first, each quoted, with the app's monospace stack behind", () => {
    expect(termFont("", "M")).toBe("M");
    expect(termFont("   ", "M")).toBe("M");
    expect(termFont("JetBrains Mono", "M")).toBe('"JetBrains Mono", M');
    expect(termFont(`'Fira  Code' , "Menlo",monospace,`, "M")).toBe('"Fira Code", "Menlo", monospace, M');
    // a half-typed list is still a valid one
    expect(termFont('"Fira Co', "M")).toBe('"Fira Co", M');
  });

  it("applies the look again to an open terminal: every option, the scrollback limit too", () => {
    const options: Record<string, unknown> = { scrollback: 5000 };
    const term = { options } as unknown as Terminal;
    const s: TermSettings = { ...TERM_DEFAULTS, fontFamily: "Menlo", fontSize: 18, lineHeight: 1.4, cursorStyle: "underline", cursorBlink: false, scrollback: 50000, contrast: "auto", optionIsMeta: false };
    applyLook(term, light, s);
    expect(options).toEqual({
      scrollback: 50000,
      theme: light,
      fontFamily: '"Menlo", monospace',
      fontSize: 18,
      lineHeight: 1.4,
      cursorStyle: "underline",
      cursorInactiveStyle: "underline",
      cursorBlink: false,
      minimumContrastRatio: 4.5,
      drawBoldTextInBrightColors: true,
      macOptionIsMeta: false,
    });
    applyLook(term, dark, { ...s, contrast: "auto" });
    expect(options.minimumContrastRatio).toBe(3);
  });

  it("sets the padding and the theme's background on the box the terminal sits in", () => {
    const vars = new Map<string, string>();
    const wrap = { style: { setProperty: (k: string, v: string) => void vars.set(k, v), removeProperty: (k: string) => void vars.delete(k) } };
    const term = { options: {}, element: { closest: (sel: string) => (sel.includes(".term-wrap") ? wrap : null) } } as unknown as Terminal;
    applyLook(term, termThemeById("dracula")!.theme, { ...TERM_DEFAULTS, padding: 8 });
    expect(Object.fromEntries(vars)).toEqual({ "--term-pad": "8px", "--term-bg": "#282a36" });
    applyLook(term, {}, { ...TERM_DEFAULTS, padding: 0 });
    expect(Object.fromEntries(vars)).toEqual({ "--term-pad": "0px" });
  });
});

describe("the preview's sample output", () => {
  // SGR codes the sample uses, by line
  const sample = termSample();
  const codes = new Set([...sample.matchAll(/\x1b\[([\d;]+)m/g)].flatMap((m) => m[1].split(";").map(Number)));

  it("uses all eight normal and all eight bright colours, bold and dim", () => {
    for (let i = 0; i < 8; i++) {
      expect(codes.has(40 + i), `normal ${i}`).toBe(true);
      expect(codes.has(100 + i), `bright ${i}`).toBe(true);
    }
    expect(codes.has(1)).toBe(true);
    expect(codes.has(2)).toBe(true);
  });

  it("selects text that is where it says: inside the sample, on the row and column named", () => {
    const rows = sample.split("\r\n").map((l) => l.replace(/\x1b\[[\d;]*m/g, ""));
    expect(rows).toHaveLength(SAMPLE_ROWS);
    expect(rows[SAMPLE_SELECT.row].slice(SAMPLE_SELECT.col, SAMPLE_SELECT.col + SAMPLE_SELECT.length)).toBe("src/theme.ts");
    // no line is wider than the width the preview says it needs
    expect(Math.max(...rows.map((r) => [...r].length))).toBeLessThanOrEqual(SAMPLE_COLS);
  });

  it("a wide preview gets a second pane beside the same lines: nothing wraps, the selection stays where it was", () => {
    expect(termSample(SAMPLE_WIDE_COLS - 1)).toBe(sample);
    const wide = termSample(SAMPLE_WIDE_COLS);
    const rows = wide.split("\r\n");
    expect(rows).toHaveLength(SAMPLE_ROWS);
    const plain = (s: string) => s.replace(/\x1b\[[\d;]*m/g, "").replace(/\x1b[78]/g, "");
    const narrow = sample.split("\r\n");
    let widest = 0;
    for (const [i, row] of rows.entries()) {
      // the first pane is the narrow sample's line, untouched; the second starts at one fixed column
      const [left, right, ...more] = row.split(/\x1b\[(?:\d+)G/);
      expect(more).toEqual([]);
      expect(left.replace(/\x1b7$/, "")).toBe(narrow[i]);
      const col = Number(/\x1b\[(\d+)G/.exec(row)![1]);
      expect(col).toBeGreaterThan(SAMPLE_COLS + 1);
      expect(plain(right).startsWith("│")).toBe(true);
      widest = Math.max(widest, col - 1 + [...plain(right)].length);
    }
    expect(widest).toBeLessThanOrEqual(SAMPLE_WIDE_COLS);
    // the second pane uses the width: its longest line ends in the last tenth of the columns it asks for
    expect(widest).toBeGreaterThanOrEqual(SAMPLE_WIDE_COLS * 0.9);
    // the cursor is put back on the prompt after the last divider
    expect(wide.endsWith("\x1b8")).toBe(true);
  });
});
