// The text inside find's active match (mock host, the engine's real feed()): a highlight's fill does not recolour
// the cell under it, and a program's yellow or green can be the fill's own colour (One Light: 1.00:1). The active
// match names its text colour, so whatever colour or strength the cell had, the text on the fill reads at 4.5:1,
// with the Minimum contrast setting at "As the theme" as well as at "High".
// Chromium, the standard (DOM) renderer; the colour read is the one the page computed for the cell.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, modKey, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

const THEMES = [
  { id: "one-light", app: "light" },
  { id: "dracula", app: "dark" },
  { id: "tango-dark", app: "dark" },
] as const;

const SGR = { yellow: "33", green: "32", dim: "2", "dim yellow": "2;33" } as const;
const KINDS = Object.keys(SGR) as (keyof typeof SGR)[];

/** One line for each kind of text, then a yellow match that starts three cells before the right edge and ends on
 *  the next row, then a yellow line in Korean. */
const output = (cols: number) =>
  "\r\n" + KINDS.map((k) => `\x1b[${SGR[k]}m${k} needle here\x1b[0m\r\n`).join("") + `\x1b[33m${"w".repeat(cols - 3)}needle wrapped\x1b[0m\r\n\x1b[33m노란 바늘 글자\x1b[0m\r\n`;

type Seen = { row: number; rows: number; line: string; text: string; picked: string; fill: string; colours: string[]; least: number };

/** The active match: where xterm has it selected, and each of its cells as the page drew it (the cell's colour laid
 *  over the fill at the cell's own opacity, so text drawn at half strength reads as what it is). */
const active = (page: Page): Promise<Seen | null> =>
  page.evaluate(async () => {
    type Pos = { x: number; y: number };
    type T = { element?: HTMLElement; options: { theme?: object }; getSelectionPosition(): { start: Pos; end: Pos } | undefined; buffer: { active: { getLine(i: number): { translateToString(t: boolean): string } | undefined } } };
    const host = document.querySelector('[data-testid="terminal"] .xterm')!;
    const term = [...((window as unknown as { __omherTerms?: Set<T> }).__omherTerms ?? [])].find((t) => t.element === host)!;
    const sel = term.getSelectionPosition();
    if (!sel) return null;
    const { findColors, contrastRatio } = (await import("/src/sessions/term/find-colors.ts" as string)) as {
      findColors: (t: unknown) => { activeMatchBackground: string; activeMatchForeground: string };
      contrastRatio: (a: string, b: string) => number;
    };
    const picked = findColors(term.options.theme ?? {});
    const parse = (v: string) => {
      const m = /rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?/.exec(v)!;
      return { c: [Number(m[1]), Number(m[2]), Number(m[3])], a: m[4] === undefined ? 1 : Number(m[4]) };
    };
    const hex = (c: number[]) => `#${c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
    const cells: { text: string; colour: string }[] = [];
    for (const s of host.querySelectorAll<HTMLElement>(".xterm-rows span")) {
      if (!/background-color/.test(s.getAttribute("style") ?? "")) continue;
      const cs = getComputedStyle(s);
      const bg = parse(cs.backgroundColor);
      if (hex(bg.c) !== picked.activeMatchBackground) continue;
      const fg = parse(cs.color);
      const a = fg.a * Number(cs.opacity);
      cells.push({ text: s.textContent ?? "", colour: hex(fg.c.map((v, i) => v * a + bg.c[i] * (1 - a))) });
    }
    return {
      row: sel.start.y,
      rows: sel.end.y - sel.start.y + 1,
      line: term.buffer.active.getLine(sel.start.y)?.translateToString(true) ?? "",
      text: cells.map((c) => c.text).join(""),
      picked: picked.activeMatchForeground,
      fill: picked.activeMatchBackground,
      colours: [...new Set(cells.map((c) => c.colour))],
      least: Math.min(...cells.map((c) => contrastRatio(c.colour, picked.activeMatchBackground))),
    };
  });

for (const th of THEMES) {
  for (const contrast of ["theme", "high"] as const) {
    test.describe(`${th.id}, minimum contrast "${contrast}"`, () => {
      test.use({ colorScheme: th.app });

      test(`yellow, green and dim text inside the active match reads at 4.5:1 on ${th.id}; so does a match over two rows and one in Korean`, async ({ page }) => {
        await openApp(page, { theme: th.app, term: { [th.app === "light" ? "themeLight" : "themeDark"]: th.id, contrast } });
        await newTerminal(page);
        const cols = await page.evaluate(() => {
          const host = document.querySelector('[data-testid="terminal"] .xterm');
          return [...((window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; cols: number }> }).__omherTerms ?? [])].find((t) => t.element === host)!.cols;
        });
        await feed(page, output(cols));
        await page.keyboard.press(`${await modKey(page)}+f`);

        // every match of "needle" in turn: one per kind of text, and the one that wraps
        await page.getByTestId("term-find-input").fill("needle");
        await expect(page.getByTestId("term-find-count")).toHaveText(new RegExp(`^\\d of ${KINDS.length + 1}$`));
        const seen: Seen[] = [];
        for (let i = 0; i <= KINDS.length; i++) {
          const last = seen.at(-1)?.row;
          await expect.poll(async () => { const a = await active(page); return a && a.row !== last ? a.text : ""; }).toBe("needle");
          const a = (await active(page))!;
          expect(a.least, `"${a.line.slice(0, 24)}" on the active fill ${a.fill} (${th.id}, ${contrast})`).toBeGreaterThanOrEqual(4.5);
          // one colour for the whole match, the one find-colors.ts picked, whatever the cells had
          expect(a.colours).toEqual([a.picked]);
          seen.push(a);
          await page.keyboard.press("Enter");
        }
        for (const k of KINDS) expect(seen.filter((a) => a.line === `${k} needle here`), k).toHaveLength(1);
        expect(seen.filter((a) => a.rows === 2), "the match that ends on the next row").toHaveLength(1);

        await page.getByTestId("term-find-input").fill("바늘");
        await expect(page.getByTestId("term-find-count")).toHaveText("1 of 1");
        await expect.poll(async () => (await active(page))?.text).toBe("바늘");
        const ko = (await active(page))!;
        expect(ko.least, `Korean text on the active fill (${th.id}, ${contrast})`).toBeGreaterThanOrEqual(4.5);
        expect(ko.colours).toEqual([ko.picked]);
      });
    });
  }
}
