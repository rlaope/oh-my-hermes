// Files the bot sends: `MEDIA:/path` lines in an answer become an image tile (with a lightbox), a video
// player and a file card, read through the read-only `media.read` op. The line itself is never shown.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-v02");

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return reply;
}

async function openHermes(page: Page) {
  await page.goto("/");
  await page.getByTestId("bot-default").click();
  await expect(page.getByTestId("header").getByText("Hermes", { exact: true })).toBeVisible();
  return page.getByTestId("timeline");
}

test.beforeEach(async () => {
  expect((await mock("mock.reset")).ok).toBe(true);
});

test("MEDIA lines become an image tile, a video and a file card, never literal text", async ({ page }) => {
  const tl = await openHermes(page);
  const bubble = tl.getByTestId("bubble-bot").filter({ hasText: "Here they are." });
  await expect(bubble).toBeVisible();
  await expect(tl).not.toContainText("MEDIA:");
  await expect(page.getByTestId("bot-default")).toContainText("Before and after:");

  const media = bubble.getByTestId("media");
  // in the order the lines came: image, video, file
  await expect(media.locator(":scope > *")).toHaveCount(3);
  const img = media.getByTestId("media-image").locator("img");
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.naturalWidth)).toBe(480);
  // one picture and one video: each keeps its own shape (480×300 → 420×262.5), no crop
  const box = (await img.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(420);
  expect(Math.abs(box.width / box.height - 480 / 300)).toBeLessThan(0.02);
  expect(await media.getByTestId("media-image").evaluate((e) => getComputedStyle(e).borderRadius)).toBe("8px");

  const video = media.getByTestId("media-video");
  await expect(video).toHaveAttribute("preload", "metadata");
  await expect(video).toHaveAttribute("controls", "");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
  expect((await video.boundingBox())!.width).toBeLessThanOrEqual(420);

  // a file is one compact row: icon, name, size, Open, all on one line
  const card = media.getByTestId("media-file");
  await expect(card.getByTestId("media-file-name")).toHaveText("report.zip");
  await expect(card.getByTestId("media-file-size")).toHaveText("136 B");
  await expect(card.getByTestId("media-open")).toBeVisible();
  await expect(card.getByTestId("media-reveal")).toHaveCount(0); // desktop app only
  const parts = await Promise.all(
    [card.locator("svg.media-ic"), card.getByTestId("media-file-name"), card.getByTestId("media-file-size"), card.getByTestId("media-open")].map(
      async (l) => (await l.boundingBox())!,
    ),
  );
  const cardBox = (await card.boundingBox())!;
  expect(cardBox.height).toBeLessThanOrEqual(40);
  for (let i = 1; i < parts.length; i++) expect(parts[i].x).toBeGreaterThan(parts[i - 1].x + parts[i - 1].width - 1);
  for (const b of parts) expect(Math.abs(b.y + b.height / 2 - (cardBox.y + cardBox.height / 2))).toBeLessThanOrEqual(2);

  // the file card asked for name and size only; image and video got their bytes
  const reads = (await mock("mock.calls")).result.calls.filter((c: any) => c.op === "media.read");
  expect(reads.map((c: any) => [c.params.path, c.params.info === true]).sort()).toEqual([
    ["/w/media/chart-after.png", false],
    ["/w/media/chart-after.png", false],
    ["/w/media/chart.png", false],
    ["/w/media/chart.png", false],
    ["/w/media/clip.mp4", false],
    ["/w/media/report.zip", true],
  ]);
});

/** Left/top/right/bottom of an element, rounded to 0.5px. */
const rect = (l: import("@playwright/test").Locator) =>
  l.evaluate((e) => {
    const r = e.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width };
  });

test("files stack under the caption in the bubble column: same left edge, 6px below, one face per run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const tl = await openHermes(page);
  await expect(tl.getByTestId("media-image")).toHaveCount(4);
  await expect.poll(() => tl.getByTestId("media-loading").count()).toBe(0);

  // the caption bubble and its files: tile left == bubble left (±1px), tile top below the bubble
  const msg = tl.getByTestId("bubble-bot").filter({ hasText: "Here they are." });
  const bub = await rect(msg.locator(".b"));
  const first = await rect(msg.getByTestId("media").locator(":scope > *").first());
  expect(Math.abs(first.left - bub.left)).toBeLessThanOrEqual(1);
  expect(first.top).toBeGreaterThan(bub.bottom);
  expect(Math.round(first.top - bub.bottom)).toBe(6);
  // every file in the message starts on that same edge, and the caption is one line (not squeezed beside a tile)
  for (const el of await msg.getByTestId("media").locator(":scope > *").all()) expect(Math.abs((await rect(el)).left - bub.left)).toBeLessThanOrEqual(1);
  expect(await msg.locator(".b").evaluate((e) => e.getClientRects().length)).toBe(1);
  const face = await rect(msg.locator(".msg-face"));
  expect(bub.left - face.right).toBe(10);

  // a files-only answer still gets the face (first of its run) and the same column
  const only = tl.getByTestId("bubble-bot").filter({ has: page.locator('img[alt="chart-after.png"]') }).first();
  await expect(only.locator(".b")).toHaveCount(0);
  await expect(only.locator(".msg-face:not(.blank)")).toHaveCount(1);
  expect(Math.abs((await rect(only.getByTestId("media-image"))).left - bub.left)).toBeLessThanOrEqual(1);
  // one picture: at most min(420px, column), its own shape
  const one = await rect(only.getByTestId("media-image"));
  expect(one.width).toBeLessThanOrEqual(420);
  expect(Math.abs(one.width / (one.bottom - one.top) - 480 / 300)).toBeLessThan(0.02);

  // the next answer in the run hides its face but keeps the column; its two pictures sit side by side
  const two = tl.getByTestId("bubble-bot").filter({ hasText: "Before and after:" });
  await expect(two.locator(".msg-face.blank")).toHaveCount(1);
  const twoBub = await rect(two.locator(".b"));
  const [a, b] = await Promise.all(
    (await two.getByTestId("media-image").all()).map((l) => rect(l)),
  );
  expect(Math.abs(a.left - twoBub.left)).toBeLessThanOrEqual(1);
  expect(a.top).toBeGreaterThan(twoBub.bottom);
  expect(Math.abs(a.top - b.top)).toBeLessThanOrEqual(1);
  expect(b.left).toBeGreaterThan(a.right);
  expect(b.right - a.left).toBeLessThanOrEqual(421);
  expect(await two.getByTestId("media").getAttribute("data-grid")).toBe("2");

  // the face column of that run holds exactly one face
  const run = tl.locator(".row-assistant").filter({ has: page.getByTestId("media") });
  await expect(run).toHaveCount(3);
  await expect(run.locator(".msg-face:not(.blank)")).toHaveCount(2); // the "Here they are." run, then the files-only run
  const runFaces = await run.evaluateAll((rows) =>
    rows.map((r) => r.querySelectorAll(".msg-face:not(.blank)").length),
  );
  expect(runFaces).toEqual([1, 1, 0]);

  // style: radius ≤10px, 12-13px type, no gradient
  for (const sel of ['[data-testid="media-image"]', '[data-testid="media-file"]', ".media-video"]) {
    const st = await tl.locator(sel).first().evaluate((e) => {
      const cs = getComputedStyle(e);
      return { r: parseFloat(cs.borderTopLeftRadius), img: cs.backgroundImage };
    });
    expect(st.r).toBeLessThanOrEqual(10);
    expect(st.img).toBe("none");
  }
  const sizes = await tl.getByTestId("media-file").first().evaluate((e) =>
    [".media-name", ".media-size", "button"].map((s) => parseFloat(getComputedStyle(e.querySelector(s)!).fontSize)),
  );
  for (const px of sizes) expect(px >= 12 && px <= 13).toBe(true);
});

test("the image opens in a lightbox; Escape and a click close it", async ({ page }) => {
  const tl = await openHermes(page);
  const tile = tl.getByTestId("media-image").first();
  await tile.click();
  const box = page.getByTestId("lightbox");
  await expect(box).toBeVisible();
  const full = await box.boundingBox();
  const vp = page.viewportSize()!;
  expect(Math.round(full!.width)).toBe(vp.width);
  expect(Math.round(full!.height)).toBe(vp.height);
  await page.keyboard.press("Escape");
  await expect(box).toHaveCount(0);
  await tile.click();
  await expect(box).toBeVisible();
  await box.click({ position: { x: 10, y: 10 } });
  await expect(box).toHaveCount(0);
});

test("media.read serves only files the bot named; anything else says it couldn't load", async ({ page }) => {
  const denied = await mock("media.read", { bot: "default", path: "/etc/hosts" });
  expect(denied.ok).toBe(false);
  expect(denied.error.code).toBe("not_found");
  const otherBot = await mock("media.read", { bot: "kami", path: "/w/media/chart.png" });
  expect(otherBot.error.code).toBe("not_found");

  const tl = await openHermes(page);
  await expect(tl.getByTestId("media-file").first()).toBeVisible();
  await mock("mock.emit", {
    events: [{ event: "message", bot: "default", id: "m-missing", text: "Sorry:\nMEDIA:/w/media/gone.png" }],
  });
  await expect(tl.getByTestId("media-error")).toContainText("Couldn't load file");
  await expect(tl).not.toContainText("MEDIA:");
});

test("screenshots: media in the chat, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  const tl = await openHermes(page);
  await expect.poll(() => tl.getByTestId("media-video").evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);
  await expect.poll(() => tl.getByTestId("media-loading").count()).toBe(0);
  const caption = tl.getByTestId("bubble-bot").filter({ hasText: "Here they are." });
  // two frames per theme: the image, video and file answer; then the files-only answer and the two pictures
  const shoot = async (theme: string) => {
    await caption.evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.mouse.move(1400, 880);
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, `T1-media-${theme}.png`) });
    await tl.evaluate((e) => (e.scrollTop = e.scrollHeight));
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, `T1-media-grid-${theme}.png`) });
  };
  await shoot("dark");
  await tl.getByTestId("media-image").first().click();
  await expect(page.getByTestId("lightbox")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "T1-lightbox-dark.png") });
  await page.keyboard.press("Escape");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(400); // let the theme transition finish
  await shoot("light");
});
