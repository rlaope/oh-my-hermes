// The omher.app hero's live preview (site/app-preview, built by tools/build_omher_preview.sh): in its 400px chat (the
// Plans panel pinned to 552px) the chat header keeps the bot name, the whole model name, the effort word and the panel
// button, and nothing in it overlaps, through the story loop in which Kami's places chip goes from none to "1 other
// place" to "2 other places", in every site language. The places chip is what gives way. This loads the built site
// from disk over a local server, as a visitor at 1280x900 sees it, and measures the DOM inside the iframe.
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

/** One reading of the chat header inside the preview iframe. */
function readHeader(): Sample | null {
  const h = document.querySelector('[data-testid="header"]');
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

async function watch(page: Page, lang: string): Promise<{ samples: Sample[]; problems: string[] }> {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${base}/?lang=${lang}`, { waitUntil: "load" });
  await page.waitForFunction(() => (window as unknown as { __hero?: { ready: boolean } }).__hero?.ready, null, { timeout: 45_000 });
  const frame = page.frames().find((f) => f.url().includes("app-preview"));
  expect(frame, "the hero mounted the live preview").toBeTruthy();
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

test("the hero preview's chat header shows the whole model name through the story loop, in every language", async ({ browser }) => {
  test.setTimeout(180_000);
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const runs = await Promise.all(["en", "ko", "ja", "zh"].map(async (lang) => watch(await ctx.newPage(), lang)));
  await ctx.close();
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
