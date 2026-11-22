// Kitty Unicode placeholders (src/sessions/term/kitty-placeholders.ts + kitty-overlay.ts), on the mock host: Hermes'
// exact virtual transmit (`a=T,U=1,i=<id>,c=2,r=2,f=100,q=2`, chunked as `_kitty_apc` chunks) and its placeholder
// rows (`kitty_placeholder_rows`, fg = `kitty_color_hex(id)`) paint the picture over those cells at device pixels:
// each cell of the overlay holds that quarter's colour, not blank and not a half-block mosaic. A Kitty picture placed
// at the cursor (no U=1) still goes to xterm's image add-on, and with Show images off nothing is kept or painted.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

const ID = 0x8000 + 4242; // inside Hermes' _IMAGE_ID_BASE span
const COLOURS = { tl: [230, 20, 20], tr: [20, 200, 40], bl: [30, 60, 230], br: [240, 210, 0] } as const;

/** A 16×32 PNG with four solid quarters, made by the page's own canvas, as base64. */
const quarterPng = (page: Page) =>
  page.evaluate(async (c) => {
    const cv = new OffscreenCanvas(16, 32);
    const g = cv.getContext("2d")!;
    const fill = (rgb: readonly number[], x: number, y: number) => {
      g.fillStyle = `rgb(${rgb.join(",")})`;
      g.fillRect(x, y, 8, 16);
    };
    fill(c.tl, 0, 0);
    fill(c.tr, 8, 0);
    fill(c.bl, 0, 16);
    fill(c.br, 8, 16);
    const bytes = new Uint8Array(await (await cv.convertToBlob({ type: "image/png" })).arrayBuffer());
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s);
  }, COLOURS);

/** Hermes' `_kitty_apc`: ≤4096-byte pieces, the control on the first only. */
function kittyApc(ctrl: string, data: string, size = 4096): string {
  const pieces: string[] = [];
  for (let i = 0; i < data.length; i += size) pieces.push(data.slice(i, i + size));
  if (!pieces.length) pieces.push("");
  return pieces.map((p, i) => `\x1b_G${i === 0 ? ctrl + "," : ""}m=${i === pieces.length - 1 ? 0 : 1};${p}\x1b\\`).join("");
}

const DIACRITICS = [0x305, 0x30d];
/** Hermes' `kitty_placeholder_rows(cols, rows)`, painted in the id's colour, one row per line. */
function placeholderRows(id: number, cols: number, rows: number): string {
  const P = String.fromCodePoint(0x10eeee);
  const fg = `\x1b[38;2;${(id >> 16) & 255};${(id >> 8) & 255};${id & 255}m`;
  const out: string[] = [];
  for (let r = 0; r < rows; r++) out.push(`${fg}${P}${String.fromCodePoint(DIACRITICS[r])}${P.repeat(cols - 1)}\x1b[39m`);
  return out.join("\r\n");
}

type Probe = { layer: boolean; virtual: number; addon: number; px: number[][] | null; cell: { w: number; h: number } };
/** The shown terminal: its overlay canvas, the virtual and add-on stores, and the overlay's pixel at the middle of
 *  each of the four placeholder cells (found where the text "@@" ends on the screen). */
const probe = (page: Page, at: { row: number; col: number } | null) =>
  page.evaluate(async (at): Promise<Probe> => {
    type T = { element?: HTMLElement; dimensions?: { css: { cell: { width: number; height: number } } }; buffer: { active: { viewportY: number } } };
    const host = document.querySelector('[data-testid="terminal"] .xterm') as HTMLElement;
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    const { virtualImages } = (await import("/src/sessions/term/engine-image.ts" as string)) as { virtualImages: (t: unknown) => { store: { images: Map<number, unknown> } } | null };
    const v = virtualImages(t);
    const addon = ((t as unknown as { _addonManager?: { _addons?: { instance: { _storage?: { _images?: Map<unknown, unknown> } } }[] } })._addonManager?._addons ?? [])
      .map((a) => a.instance._storage?._images?.size)
      .find((n) => typeof n === "number");
    const canvas = host.querySelector("canvas.xterm-kitty-placeholder-layer") as HTMLCanvasElement | null;
    const cw = t.dimensions!.css.cell.width;
    const ch = t.dimensions!.css.cell.height;
    let px: number[][] | null = null;
    if (canvas && at) {
      const g = canvas.getContext("2d")!;
      const k = canvas.width / canvas.clientWidth;
      const y0 = at.row - t.buffer.active.viewportY;
      px = [
        [0, 0],
        [1, 0],
        [0, 1],
        [1, 1],
      ].map(([dx, dy]) => [...g.getImageData(Math.floor((at.col + dx + 0.5) * cw * k), Math.floor((y0 + dy + 0.5) * ch * k), 1, 1).data]);
    }
    return { layer: !!canvas, virtual: v?.store.images.size ?? -1, addon: addon ?? -1, px, cell: { w: cw, h: ch } };
  }, at);

/** Where the cursor is (absolute buffer row, column). */
const cursor = (page: Page) =>
  page.evaluate(() => {
    type T = { element?: HTMLElement; buffer: { active: { baseY: number; cursorY: number; cursorX: number } } };
    const host = document.querySelector('[data-testid="terminal"] .xterm') as HTMLElement;
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    return { row: t.buffer.active.baseY + t.buffer.active.cursorY, col: t.buffer.active.cursorX };
  });

const near = (got: number[], want: readonly number[]) => want.every((v, i) => Math.abs(got[i] - v) <= 6) && got[3] === 255;

test("Hermes' virtual transmit and placeholder rows paint the picture's own colours in those cells", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(0); // Show images is on: the store is there
  const png = await quarterPng(page);
  await feed(page, "\r\n" + kittyApc(`a=T,U=1,i=${ID},c=2,r=2,f=100,q=2`, png));
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(1);
  await feed(page, "  ");
  const at = await cursor(page);
  await feed(page, placeholderRows(ID, 2, 2).replace("\r\n", "\r\n  ") + "\r\nafter\r\n");
  await expect.poll(async () => (await probe(page, at)).layer).toBe(true);
  await expect
    .poll(async () => {
      const p = await probe(page, at);
      return !!p.px && near(p.px[0], COLOURS.tl) && near(p.px[1], COLOURS.tr) && near(p.px[2], COLOURS.bl) && near(p.px[3], COLOURS.br);
    })
    .toBe(true);
  // nothing went to the add-on: the transmit was ours, and no reply was typed back (q=2)
  expect((await probe(page, at)).addon).toBe(0);
  await page.getByTestId("terminal").screenshot({ path: `${process.env.TMPDIR ?? "/tmp"}/omher-kitty-placeholder.png` });
});

test("a Kitty picture placed at the cursor (no U=1) is still drawn by the image add-on", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(0);
  const png = await quarterPng(page);
  await feed(page, "\r\n" + kittyApc("a=T,f=100,q=2", png) + "\r\n");
  await expect.poll(async () => (await probe(page, null)).addon).toBe(1);
  expect((await probe(page, null)).virtual).toBe(0);
});

test("with Show images off, a virtual transmit keeps nothing and paints nothing", async ({ page }) => {
  await openApp(page, { term: { images: false } });
  await newTerminal(page);
  const png = await quarterPng(page);
  await feed(page, "\r\n" + kittyApc(`a=T,U=1,i=${ID},c=2,r=2,f=100,q=2`, png) + placeholderRows(ID, 2, 2) + "\r\n");
  await page.waitForTimeout(300);
  const p = await probe(page, null);
  expect(p.virtual).toBe(-1);
  expect(p.layer).toBe(false);
});
