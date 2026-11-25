// The omher.app site and its live app preview (site/app-preview, built by tools/build_omher_preview.sh), loaded from
// disk over a local server as a visitor sees them.
// 1. The home page's hero plays the omher film and keeps playing it, in every site language (1280x900): the live
//    preview that used to crossfade in over the film a moment after load is never mounted (owner request, 2026-11-25,
//    d17fb8dfb).
// 2. The preview page itself, at the 1200px width the hero used to lay it out at: the chat header keeps the bot name,
//    the whole model name, the effort word and the panel button, and nothing in it overlaps, through the story loop in
//    which Kami's places chip goes from none to "1 other place" to "2 other places", whatever the site language and
//    the browser's (the preview stays English). Below a 470px chat the places chip is what gives way.
// 3. The bot chat is the widest column (the Plans panel starts at 352px), and the panel's own handle resizes it: a drag
//    and the arrow keys, both ways, between the app's limits, with the model name still whole in the narrowest chat.
import { expect, test, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const SITE = process.env.OMHER_SITE_DIR || fileURLToPath(new URL("../../../site/", import.meta.url));
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".ico": "image/x-icon", ".mp4": "video/mp4",
  ".woff2": "font/woff2", ".txt": "text/plain",
};
let server: Server;
let base = "";

test.beforeAll(async () => {
  server = createServer(async (req, res) => {
    let u = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
    if (u.endsWith("/")) u += "index.html";
    const p = normalize(u);
    try {
      const body = await readFile(join(SITE, p));
      res.writeHead(200, { "content-type": TYPES[extname(p)] ?? "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end();
    }
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const a = server.address();
  base = `http://127.0.0.1:${typeof a === "object" && a ? a.port : 0}`;
});
test.afterAll(() => new Promise<void>((r) => server.close(() => r())));

type Sample = {
  kids: { cls: string; l: number; r: number }[];
  inner: number;
  model: [string, number, number] | null;
  name: [number, number] | null;
  eff: [number, number] | null;
  places: string | null;
  panelButton: boolean;
  dot: boolean;
};

/** One reading of the chat header inside the preview iframe. The story also passes through a terminal session
    (`ss-head-*`) and pages (`pg-head`), whose headers share the test id; only the chat header is read. */
function readHeader(): Sample | null {
  const h = [...document.querySelectorAll('[data-testid="header"]')].find(
    (el) => !el.querySelector(".ss-head-mark") && !el.classList.contains("pg-head"),
  );
  if (!h) return null;
  const hr = h.getBoundingClientRect();
  const wh = (sel: string): [number, number] | null => {
    const el = h.querySelector(sel);
    return el ? [el.clientWidth, el.scrollWidth] : null;
  };
  const ml = h.querySelector('[data-testid="model-label"]');
  const shown = (el: Element | null) => !!el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).visibility !== "hidden";
  return {
    kids: [...h.children].map((c) => {
      const b = c.getBoundingClientRect();
      return { cls: String(c.className).split(" ")[0], l: b.left, r: b.right };
    }),
    inner: hr.right - parseFloat(getComputedStyle(h).paddingRight),
    model: ml ? [ml.textContent ?? "", ml.clientWidth, ml.scrollWidth] : null,
    name: wh(".head-title"),
    eff: wh('[data-testid="reasoning-label"]'),
    places: h.querySelector('[data-testid="places-label"]')?.textContent ?? null,
    panelButton: shown(h.querySelector('[data-testid="panel-button"]')),
    dot: shown(h.querySelector('[data-testid="panel-button-live"]')),
  };
}

/** The preview page on its own, at the 1200x720 the hero's iframe used, once its story has drawn the run graph. */
async function openPreview(page: Page, lang = "en") {
  await page.setViewportSize({ width: 1200, height: 720 });
  await page.goto(`${base}/app-preview/?lang=${lang}`, { waitUntil: "load" });
  await page.waitForFunction(() => !!(window as unknown as { __omherPreview?: unknown }).__omherPreview, null, { timeout: 45_000 });
  await expect(page.locator('[data-testid="run-node"]').first()).toBeVisible({ timeout: 45_000 });
}

async function watch(page: Page, lang: string): Promise<{ samples: Sample[]; problems: string[] }> {
  await openPreview(page, lang);
  const frame = page.mainFrame();
  // the preview's story is staged in English, so the app stays English whatever the site's and the browser's language
  expect(await frame!.evaluate(() => [document.documentElement.lang, /[\uac00-\ud7a3\u3040-\u30ff]/.test(document.body.innerText)]), `${lang}: preview language`).toEqual(["en", false]);
  const samples: Sample[] = [];
  const problems: string[] = [];
  const t0 = Date.now();
  // the story lands the second place ~40-46 s into a loop; watch until it has been on screen a while, at most 70 s
  let twoAt = 0;
  while (Date.now() - t0 < 70_000 && !(twoAt && Date.now() - twoAt > 4000)) {
    const s = await frame!.evaluate(readHeader);
    if (s) {
      samples.push(s);
      const at = `${lang} @${((Date.now() - t0) / 1000).toFixed(1)}s (places: ${s.places ?? "none"})`;
      if (!s.model || s.model[0] !== "Opus 5.5" || s.model[2] > s.model[1]) problems.push(`${at}: model label ${JSON.stringify(s.model)}`);
      if (!s.name || s.name[1] > s.name[0]) problems.push(`${at}: bot name cut ${JSON.stringify(s.name)}`);
      if (!s.eff || s.eff[1] > s.eff[0]) problems.push(`${at}: effort cut ${JSON.stringify(s.eff)}`);
      if (!s.panelButton) problems.push(`${at}: no panel button`);
      for (let i = 0; i + 1 < s.kids.length; i++)
        if (s.kids[i].r > s.kids[i + 1].l + 0.5) problems.push(`${at}: ${s.kids[i].cls} overlaps ${s.kids[i + 1].cls}`);
      const last = s.kids[s.kids.length - 1];
      if (last && last.r > s.inner + 0.5) problems.push(`${at}: ${last.cls} runs past the header`);
      if (!twoAt && s.places && /2/.test(s.places)) twoAt = Date.now();
    }
    await page.waitForTimeout(400);
  }
  return { samples, problems };
}

const LOCALE: Record<string, string> = { en: "en-US", ko: "ko-KR", ja: "ja-JP", zh: "zh-CN" };

test("the hero plays its film and keeps playing it, in every site language; the live preview is never mounted", async ({ browser }) => {
  test.setTimeout(90_000);
  for (const lang of ["en", "ko", "ja", "zh"]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: LOCALE[lang] });
    const page = await ctx.newPage();
    await page.goto(`${base}/?lang=${lang}`, { waitUntil: "load" });
    // the rim's frame loop is running: the hero's script is up on a desktop-wide page
    await page.waitForFunction(() => ((window as unknown as { __hero?: { frames: number } }).__hero?.frames ?? 0) > 30, null, { timeout: 30_000 });
    const film = page.locator("[data-app-shot] [data-app-win] video[data-app-film]");
    await expect(film, `${lang}: the film is in the window`).toHaveCount(1);
    const at = () => film.evaluate((v: HTMLVideoElement) => ({ paused: v.paused, t: v.currentTime }));
    await expect.poll(async () => (await at()).t, { message: `${lang}: the film starts`, timeout: 15_000 }).toBeGreaterThan(0);
    // past the moment the old hero mounted the preview (after load and an idle moment) and paused the film under it
    await page.waitForTimeout(4000);
    const a = await at();
    await page.waitForTimeout(1000);
    const b = await at();
    expect(a.paused || b.paused, `${lang}: the film is still playing`).toBe(false);
    expect(b.t, `${lang}: the film's clock moves on`).not.toBe(a.t);
    expect(page.frames().filter((f) => f.url().includes("app-preview")), `${lang}: no live preview frame`).toEqual([]);
    expect(await page.locator("iframe, .omher__live").count(), `${lang}: nothing laid over the film`).toBe(0);
    expect(await page.evaluate(() => (window as unknown as { __hero?: { ready?: boolean } }).__hero?.ready), `${lang}: no preview ready flag`).toBeUndefined();
    await ctx.close();
  }
});

test("the preview page's chat header shows the whole model name through the story loop, whatever the language", async ({ browser }) => {
  test.setTimeout(180_000);
  const ctxs = await Promise.all(["en", "ko", "ja", "zh"].map((lang) => browser.newContext({ viewport: { width: 1200, height: 720 }, locale: LOCALE[lang] })));
  const runs = await Promise.all(["en", "ko", "ja", "zh"].map(async (lang, i) => watch(await ctxs[i].newPage(), lang)));
  await Promise.all(ctxs.map((c) => c.close()));
  for (const [i, lang] of ["en", "ko", "ja", "zh"].entries()) {
    const { samples, problems } = runs[i];
    expect(samples.length, `${lang}: header samples`).toBeGreaterThan(40);
    // the loop really reached the tight header: the chip with one place, then two, and the live dot
    expect(samples.some((s) => s.places && /1/.test(s.places)), `${lang}: saw one other place`).toBe(true);
    expect(samples.some((s) => s.places && /2/.test(s.places)), `${lang}: saw two other places`).toBe(true);
    expect(samples.some((s) => s.dot), `${lang}: saw the panel button's live dot`).toBe(true);
    expect(problems.slice(0, 8), `${lang}: ${problems.length} bad samples of ${samples.length}`).toEqual([]);
  }
});

test("the preview page's Plans panel starts narrow and resizes by drag and arrow keys", async ({ browser }) => {
  test.setTimeout(90_000);
  const page = await browser.newPage({ viewport: { width: 1200, height: 720 } });
  // no wheel or click first: the story yields to any input for a while and would not open Kami's plan in the panel
  await openPreview(page);
  const frame = page.mainFrame();
  const handle = frame.locator('[data-testid="panel-resizer"]');
  await expect(handle).toBeVisible({ timeout: 20_000 });
  const cols = () =>
    frame.evaluate(() => {
      const w = (s: string) => Math.round(document.querySelector(s)!.getBoundingClientRect().width);
      const ml = document.querySelector('[data-testid="header"] [data-testid="model-label"]');
      return {
        side: w('[data-testid="sidebar"]'),
        chat: w(".main"),
        panel: w('[data-testid="details"]'),
        model: ml ? [ml.clientWidth, ml.scrollWidth] : null,
        notes: ((window as unknown as { __omherPreviewToasts?: string[] }).__omherPreviewToasts ?? []).length,
      };
    });
  await expect.poll(async () => (await cols()).panel).toBe(352);
  // the handle has stopped moving (the panel has finished opening): a drag that starts while it still slides lands
  // beside the 5px handle
  await expect
    .poll(async () => {
      const a = await handle.boundingBox();
      await page.waitForTimeout(150);
      const b = await handle.boundingBox();
      return !!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.height - b.height) < 0.5;
    })
    .toBe(true);
  const start = await cols();
  expect(start.chat, "the bot chat is the widest column").toBeGreaterThan(Math.max(start.side, start.panel));

  const drag = async (dx: number) => {
    const b = (await handle.boundingBox())!;
    const x = b.x + b.width / 2, y = b.y + b.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let i = 1; i <= 10; i++) await page.mouse.move(x + (dx * i) / 10, y);
    await page.mouse.up();
    await page.waitForTimeout(300);
    return cols();
  };
  const left = await drag(-120);
  expect(left.panel, "dragged left: the panel grows").toBeGreaterThan(start.panel + 100);
  expect(left.chat).toBeLessThan(start.chat - 100);
  const widest = await drag(-600);
  expect(widest.chat, "the chat stops at the app's 360px minimum").toBe(360);
  expect(widest.model && widest.model[1] >= widest.model[0] && widest.model[0] > 0, "model name whole in a 360px chat").toBe(true);
  const narrowest = await drag(700);
  expect(narrowest.panel, "the panel stops at the app's 260px minimum").toBe(260);
  expect(narrowest.chat).toBeGreaterThan(start.chat);

  // keyboard: the handle takes focus; ←/→ move it 16px
  await handle.focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await cols()).panel).toBe(276);
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await cols()).panel).toBe(260);
  await expect(frame.locator('[data-testid="window"]')).toHaveAttribute("style", /--panel-w: 260px/);

  // the drag did not count as an inert action. (On the home page this also checked the drag left the site page's
  // scroll alone; the preview page on its own cannot scroll at all: body is overflow: hidden at the window's height.)
  expect((await cols()).notes).toBe(0);
  expect(await page.evaluate(() => document.scrollingElement!.scrollHeight - innerHeight), "the preview page has no scroll range").toBeLessThanOrEqual(0);
  await page.close();
});
