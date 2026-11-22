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

// ---- review round 1 (fix-overlay): lifecycle, stacking, first frame, gone pictures, shared budget, two-command form

/** `window.__shown()`: the shown terminal's xterm; `window.__eng`: engine-image's exports. */
async function hooks(page: Page) {
  await page.evaluate(async () => {
    const w = window as unknown as Record<string, unknown> & { __omherTerms: Set<{ element?: HTMLElement }> };
    w.__shown = () => [...w.__omherTerms].find((x) => x.element === document.querySelector('[data-testid="terminal"] .xterm'));
    w.__eng = await import("/src/sessions/term/engine-image.ts" as string);
  });
}

/** The overlay's own pixel at the middle of cell (col, screen row) of the shown terminal, null without an overlay. */
const overlayPixel = (page: Page, col: number, row: number) =>
  page.evaluate(
    ([c, r]) => {
      const w = window as unknown as { __shown(): { element: HTMLElement; dimensions: { css: { cell: { width: number; height: number } } } } };
      const t = w.__shown();
      const cv = t.element.querySelector("canvas.xterm-kitty-placeholder-layer") as HTMLCanvasElement | null;
      if (!cv) return null;
      const k = cv.width / cv.clientWidth;
      const { width, height } = t.dimensions.css.cell;
      return [...cv.getContext("2d")!.getImageData(Math.floor((c + 0.5) * width * k), Math.floor((r + 0.5) * height * k), 1, 1).data];
    },
    [col, row] as const,
  );

/** The pixel the page shows (composited: every layer, the GPU renderer's included) at the middle of a cell. */
async function screenPixel(page: Page, col: number, row: number): Promise<number[]> {
  const at = await page.evaluate(
    ([c, r]) => {
      const w = window as unknown as { __shown(): { element: HTMLElement; dimensions: { css: { cell: { width: number; height: number } } } } };
      const t = w.__shown();
      const b = t.element.querySelector(".xterm-screen")!.getBoundingClientRect();
      const { width, height } = t.dimensions.css.cell;
      return { x: Math.floor(b.left + (c + 0.5) * width), y: Math.floor(b.top + (r + 0.5) * height) };
    },
    [col, row] as const,
  );
  const shot = (await page.screenshot({ clip: { x: at.x, y: at.y, width: 1, height: 1 } })).toString("base64");
  return page.evaluate(async (b64) => {
    const img = await createImageBitmap(new Blob([Uint8Array.from(atob(b64), (x) => x.charCodeAt(0))], { type: "image/png" }));
    const g = new OffscreenCanvas(1, 1).getContext("2d")!;
    g.drawImage(img, 0, 0);
    return [...g.getImageData(0, 0, 1, 1).data];
  }, shot);
}

/** Puts the quarter picture as a 2×2 virtual placement at the top-left of the screen (cells 0..1 × 0..1). */
async function quarterAtTop(page: Page) {
  const png = await quarterPng(page);
  await feed(page, "\x1b[2J\x1b[H" + kittyApc(`a=T,U=1,i=${ID},c=2,r=2,f=100,q=2`, png));
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(1);
  await feed(page, "\x1b[H" + placeholderRows(ID, 2, 2) + "\r\n");
  await expect.poll(async () => (await overlayPixel(page, 1, 1)) ?? []).toEqual(expect.arrayContaining([255]));
}

const bgRgb = (page: Page) =>
  page.evaluate(() => {
    const t = (window as unknown as { __shown(): { options: { theme?: { background?: string } } } }).__shown();
    const c = document.createElement("canvas").getContext("2d")!;
    c.fillStyle = t.options.theme?.background ?? "#000";
    c.fillRect(0, 0, 1, 1);
    return [...c.getImageData(0, 0, 1, 1).data];
  });

test("B1: the GPU renderer attached after a picture shows does not cover it (the page's composited pixel)", async ({ page }) => {
  await openApp(page, { term: { gpu: "off" } });
  await newTerminal(page);
  await hooks(page);
  await quarterAtTop(page);
  expect(near(await screenPixel(page, 1, 1), COLOURS.br)).toBe(true);
  await page.evaluate(async () => ((await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void }).writeTermSettings({ gpu: "on" }));
  await expect.poll(() => page.evaluate(async () => (await import("/src/sessions/term/engine.ts" as string)).rendererInUse())).toBe("gpu");
  // the overlay is the last canvas of the screen, above the GPU's
  const order = await page.evaluate(() => [...document.querySelectorAll('[data-testid="terminal"] .xterm-screen canvas')].map((c) => c.className));
  expect(order[order.length - 1]).toBe("xterm-kitty-placeholder-layer");
  await expect.poll(async () => near(await screenPixel(page, 1, 1), COLOURS.br)).toBe(true);
  expect(near(await screenPixel(page, 0, 0), COLOURS.tl)).toBe(true);
});

test("B2: a hidden terminal that gets pictures keeps one overlay canvas, repaints once shown, and has none with pictures off", async ({ page }) => {
  await openApp(page);
  const a = await newTerminal(page);
  await hooks(page);
  await quarterAtTop(page);
  const pa = await page.evaluate((sid) => (window as unknown as { __omherSessions: { ptyOf(id: string): number } }).__omherSessions.ptyOf(sid), a);
  const host = await page.evaluate(() => {
    const t = (window as unknown as { __shown(): { element: HTMLElement } }).__shown();
    (window as unknown as { __hidden: HTMLElement }).__hidden = t.element;
    return true;
  });
  expect(host).toBe(true);
  await newTerminal(page); // the first leaves the page; its program keeps printing
  const layers = () => page.evaluate(() => (window as unknown as { __hidden: HTMLElement }).__hidden.querySelectorAll("canvas.xterm-kitty-placeholder-layer").length);
  expect(await page.evaluate(() => (window as unknown as { __hidden: HTMLElement }).__hidden.isConnected)).toBe(false);
  const png = await quarterPng(page);
  for (const id of [11, 12, 13]) {
    await page.evaluate(([p, d]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, d as string), [pa, kittyApc(`a=T,U=1,i=${id},c=1,r=1,f=100,q=2`, png)] as const);
    await page.waitForTimeout(150);
    expect(await layers()).toBe(1);
  }
  // an empty alternate screen printed while hidden: nothing of the old picture shows when it is back
  await page.evaluate(([p]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, "\x1b[?1049h"), [pa] as const);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
  await expect.poll(() => layers()).toBe(1);
  await expect.poll(async () => (await overlayPixel(page, 1, 1))?.[3]).toBe(0);
  await page.evaluate(async () => ((await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void }).writeTermSettings({ images: false }));
  await expect.poll(() => page.locator("canvas.xterm-kitty-placeholder-layer").count()).toBe(0);
  expect(await layers()).toBe(0);
});

test("NB1: the overlay is right in the first frame xterm draws after a buffer switch", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await hooks(page);
  await quarterAtTop(page);
  const frames = await page.evaluate(async () => {
    type T = { element: HTMLElement; buffer: { active: { type: string } }; onRender(f: () => void): { dispose(): void }; write(d: string, cb: () => void): void; dimensions: { css: { cell: { width: number; height: number } } } };
    const t = (window as unknown as { __shown(): T }).__shown();
    const px = () => {
      const cv = t.element.querySelector("canvas.xterm-kitty-placeholder-layer") as HTMLCanvasElement;
      const k = cv.width / cv.clientWidth;
      return [...cv.getContext("2d")!.getImageData(Math.floor(1.5 * t.dimensions.css.cell.width * k), Math.floor(1.5 * t.dimensions.css.cell.height * k), 1, 1).data];
    };
    const first = (type: string) =>
      new Promise<number[]>((res) => {
        const sub = t.onRender(() => {
          if (t.buffer.active.type !== type) return;
          sub.dispose();
          res(px());
        });
      });
    const alt = first("alternate");
    t.write("\x1b[?1049h", () => undefined);
    const a = await alt;
    const normal = first("normal");
    t.write("\x1b[?1049l", () => undefined);
    return { alt: a, main: await normal };
  });
  expect(frames.alt[3]).toBe(0);
  expect(near(frames.main, COLOURS.br)).toBe(true);
});

test("NB2: placeholder cells whose picture is gone (deleted, or the terminal parked and made again) paint blank background", async ({ page }) => {
  await openApp(page);
  const a = await newTerminal(page);
  await hooks(page);
  await quarterAtTop(page);
  const bg = await bgRgb(page);
  await feed(page, "\x1b_Ga=d,d=A,q=2\x1b\\");
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(0);
  await expect.poll(async () => await overlayPixel(page, 1, 1)).toEqual(bg);
  // parked (its pictures dropped) and made again from the snapshot: the cells are still blank, not the glyph
  await quarterAtTop(page);
  await newTerminal(page);
  await page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherPark: { parked(): number } }).__omherPark.parked())).toBe(1);
  await page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 999_999, idleMs: 999_999, sweepMs: 1000 }));
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(0);
  await expect.poll(async () => await overlayPixel(page, 1, 1)).toEqual(bg);
  await expect.poll(async () => await screenPixel(page, 1, 1)).toEqual(bg);
});

test("B4: ordinary and virtual pictures share one 32 MB per terminal", async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);
  await newTerminal(page);
  await hooks(page);
  const big = await page.evaluate(async () => {
    const cv = new OffscreenCanvas(2000, 2250);
    const g = cv.getContext("2d")!;
    g.fillStyle = "#f00";
    g.fillRect(0, 0, 2000, 2250);
    const bytes = new Uint8Array(await (await cv.convertToBlob({ type: "image/png" })).arrayBuffer());
    let s = "";
    for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(s);
  });
  const used = () => page.evaluate(() => (window as unknown as { __eng: { imageBytes(t: unknown): number }; __shown(): unknown }).__eng.imageBytes((window as unknown as { __shown(): unknown }).__shown()));
  await feed(page, "\r\n" + kittyApc("a=T,f=100,q=2", big) + "\r\n");
  await expect.poll(used).toBe(18_000_000);
  await feed(page, kittyApc("a=T,U=1,i=8,c=1,r=1,f=100,q=2", big));
  await page.waitForTimeout(500);
  expect(await used()).toBeLessThanOrEqual(32_000_000);
  expect((await probe(page, null)).virtual).toBe(0); // 18 MB more does not fit what the add-on left
});

// ---- review round 2 (fix-budget): the budget after the add-on rescales

/** A solid `w`×`h` PNG made by the page's canvas, as base64. */
const solidPng = (page: Page, w: number, h: number, colour: string) =>
  page.evaluate(
    async ([w, h, colour]) => {
      const cv = new OffscreenCanvas(w, h);
      const g = cv.getContext("2d")!;
      g.fillStyle = colour;
      g.fillRect(0, 0, w, h);
      const bytes = new Uint8Array(await (await cv.convertToBlob({ type: "image/png" })).arrayBuffer());
      let s = "";
      for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192));
      return btoa(s);
    },
    [w, h, colour] as const,
  );

test("B4 after rescale: a larger font keeps ordinary and virtual pictures within one 32 MB (both stores read)", async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);
  await newTerminal(page);
  await hooks(page);
  const stores = () =>
    page.evaluate(() => {
      const w = window as unknown as { __shown(): unknown; __eng: { virtualImages(t: unknown): { store: { usage: number; images: Map<number, unknown> } } | null } };
      const t = w.__shown() as { _addonManager: { _addons: { instance: { _storage?: unknown; storageUsage: number } }[] } };
      const addon = t._addonManager._addons.find((a) => a.instance._storage)!.instance;
      const v = w.__eng.virtualImages(t)!.store;
      return { addon: Math.round(addon.storageUsage * 1_000_000), virtual: v.usage, images: v.images.size };
    });
  const small = await solidPng(page, 1500, 1500, "#f00");
  const large = await solidPng(page, 2000, 2250, "#00f");
  await feed(page, "\x1b[2J\x1b[H" + kittyApc("a=T,i=1,f=100,q=2,C=1", small));
  await expect.poll(async () => (await stores()).addon).toBe(9_000_000);
  await feed(page, kittyApc("a=T,U=1,i=8,c=1,r=1,f=100,q=2", large));
  await expect.poll(async () => (await stores()).images).toBe(1);
  expect(await stores()).toMatchObject({ addon: 9_000_000, virtual: 18_000_000 });
  // the add-on keeps a rescaled copy beside its picture at the new cell size, with no new picture added
  const size = await page.evaluate(() => {
    const t = (window as unknown as { __shown(): { options: { fontSize: number }; refresh(a: number, b: number): void; rows: number } }).__shown();
    t.options.fontSize = t.options.fontSize + 4;
    t.refresh(0, t.rows - 1);
    return t.options.fontSize;
  });
  expect(size).toBeGreaterThan(0);
  await expect.poll(async () => (await stores()).addon).toBeGreaterThan(9_000_000);
  await page.waitForTimeout(300);
  const after = await stores();
  expect(after.addon + after.virtual).toBeLessThanOrEqual(32_000_000);
  expect(after.images).toBe(0); // the virtual picture went, the oldest first
});

test("NB3: kitty's two-command form (a=t, then a=p,U=1) paints the add-on's transmitted picture in the placeholders", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await hooks(page);
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(0);
  const png = await quarterPng(page);
  await feed(page, "\x1b[2J\x1b[H" + kittyApc(`a=t,f=100,i=${ID},q=2`, png) + `\x1b_Ga=p,U=1,i=${ID},c=2,r=2,q=2\x1b\\`);
  await expect.poll(async () => (await probe(page, null)).virtual).toBe(1);
  await feed(page, "\x1b[H" + placeholderRows(ID, 2, 2) + "\r\n");
  await expect.poll(async () => near((await overlayPixel(page, 0, 0)) ?? [], COLOURS.tl) && near((await overlayPixel(page, 1, 1)) ?? [], COLOURS.br)).toBe(true);
  expect((await probe(page, null)).addon).toBe(0); // no ordinary placement at the cursor
});
