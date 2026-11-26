// Block elements (U+2580-259F) on the GPU renderer at the default 13 px font: Claude Code's mascot is drawn from halves
// and quadrants, and a 7 px cell (1x) puts each half on half a pixel. A solid run of them must tile with no darker
// column inside it (term/look.ts snapBlockGlyphs). Captured at 1x: headless Chromium draws nothing on the WebGL canvas
// above a pixel ratio of 1.25.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, openApp } from "./term-find-helpers";

test.use({ deviceScaleFactor: 1 });

test.beforeEach(async () => {
  await mock("mock.reset");
});

const ORANGE = "\x1b[38;2;217;119;87m";
const MASCOT = `\x1b[2J\x1b[H${ORANGE} ▐▛███▜▌\x1b[0m\r\n${ORANGE}▝▜█████▛▘\x1b[0m\r\n${ORANGE}  ▘▘ ▝▝  \x1b[0m\r\n`;

/** For one pixel row through the solid part of a terminal row, the columns whose colour is not the run's own. */
async function offColumns(page: Page, row: number, from: number, to: number, frac: number): Promise<{ cell: number; off: number[]; run: number[] }> {
  const box = await page.evaluate(() => {
    const t = [...((window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; _core?: { _renderService?: { dimensions: { css: { cell: { width: number; height: number } } } } } }> }).__omherTerms ?? [])].find((x) => x.element?.isConnected)!;
    const s = t.element!.querySelector(".xterm-screen")!.getBoundingClientRect();
    return { x: s.left, y: s.top, ...t._core!._renderService!.dimensions.css.cell };
  });
  const png = await page.screenshot({ clip: { x: box.x, y: box.y, width: box.width * 10, height: box.height * 3 } });
  const y = Math.round((row + frac) * box.height);
  const [x0, x1] = [Math.round(from * box.width), Math.round(to * box.width)];
  return page.evaluate(
    async ([b64, y, x0, x1, cell]) => {
      const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob());
      const c = new OffscreenCanvas(bmp.width, bmp.height);
      const g = c.getContext("2d")!;
      g.drawImage(bmp, 0, 0);
      const px = [...Array(x1 - x0).keys()].map((i) => [...g.getImageData(x0 + i, y, 1, 1).data.slice(0, 3)]);
      const key = (p: number[]) => p.join(",");
      const counts = new Map<string, number>();
      for (const p of px) counts.set(key(p), (counts.get(key(p)) ?? 0) + 1);
      const run = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]![0].split(",").map(Number);
      const off = px.flatMap((p, i) => (Math.abs(p[0]! + p[1]! + p[2]! - run[0]! - run[1]! - run[2]!) > 24 ? [x0 + i] : []));
      return { cell, off, run };
    },
    [png.toString("base64"), y, x0, x1, box.width] as const,
  );
}

for (const theme of ["dark", "light"] as const)
  test(`the block mascot tiles with no seam on the GPU renderer at 13 px (${theme})`, async ({ page }) => {
    await openApp(page, { theme, term: { gpu: "on" } });
    // a Claude Code session opened (the GPU renderer keeps no text in the page to wait on: wait for its program)
    type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
    const id = await page.evaluate(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("claude", "/home/you/code/web-app"));
    await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
    await page.getByTestId(`session-${id}`).locator(".ss-open").click();
    await expect(page.locator(`[data-testid="terminal"][data-session="${id}"]`)).toBeVisible();
    await expect.poll(() => page.evaluate(async () => (await import("/src/sessions/term/engine.ts" as string)).rendererInUse())).toBe("gpu");
    await feed(page, MASCOT);
    await page.mouse.move(5, 5);
    await page.waitForTimeout(300);
    // the head's top half (▛███▜, cells 2-6) and the body's top half (▜█████▛, cells 1-7): solid orange throughout
    const head = await offColumns(page, 0, 2, 7, 0.25);
    const body = await offColumns(page, 1, 1, 8, 0.25);
    // the default cell is an odd number of px: the halves fall on half a pixel, where the seam was
    expect(head.cell % 2).toBe(1);
    expect(head.run).toEqual([217, 119, 87]);
    expect(head.off, JSON.stringify(head)).toEqual([]);
    expect(body.off, JSON.stringify(body)).toEqual([]);
  });
