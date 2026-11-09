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
  await expect(page.getByTestId("bot-default")).toContainText("Here they are.");

  const media = bubble.getByTestId("media");
  // in the order the lines came: image, video, file
  await expect(media.locator(":scope > *")).toHaveCount(3);
  const img = media.getByTestId("media-image").locator("img");
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.naturalWidth)).toBe(480);
  const box = (await img.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(360);
  expect(box.height).toBeLessThanOrEqual(360);
  expect(await img.evaluate((e) => getComputedStyle(e).objectFit)).toBe("cover");
  expect(await media.getByTestId("media-image").evaluate((e) => getComputedStyle(e).borderRadius)).toBe("8px");

  const video = media.getByTestId("media-video");
  await expect(video).toHaveAttribute("preload", "metadata");
  await expect(video).toHaveAttribute("controls", "");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
  expect((await video.boundingBox())!.width).toBeLessThanOrEqual(420);

  const card = media.getByTestId("media-file");
  await expect(card.getByTestId("media-file-name")).toHaveText("report.zip");
  await expect(card.getByTestId("media-file-size")).toHaveText("136 B");
  await expect(card.getByTestId("media-open")).toBeVisible();
  await expect(card.getByTestId("media-reveal")).toHaveCount(0); // desktop app only
  expect(Math.round((await card.boundingBox())!.width)).toBe(220);

  // the file card asked for name and size only; image and video got their bytes
  const reads = (await mock("mock.calls")).result.calls.filter((c: any) => c.op === "media.read");
  expect(reads.map((c: any) => [c.params.path, c.params.info === true]).sort()).toEqual([
    ["/w/media/chart.png", false],
    ["/w/media/clip.mp4", false],
    ["/w/media/report.zip", true],
  ]);
});

test("the image opens in a lightbox; Escape and a click close it", async ({ page }) => {
  const tl = await openHermes(page);
  const tile = tl.getByTestId("media-image");
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
  await expect(tl.getByTestId("media-file")).toBeVisible();
  await mock("mock.emit", {
    events: [{ event: "message", bot: "default", id: "m-missing", text: "Sorry:\nMEDIA:/w/media/gone.png" }],
  });
  await expect(tl.getByTestId("media-error")).toContainText("Couldn't load file");
  await expect(tl).not.toContainText("MEDIA:");
});

test("screenshots: media in the chat, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  const tl = await openHermes(page);
  await expect.poll(() => tl.getByTestId("media-video").evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);
  await expect(tl.getByTestId("media-file")).toBeInViewport();
  await page.screenshot({ path: join(SHOTS, "T1-media-dark.png") });
  await tl.getByTestId("media-image").click();
  await expect(page.getByTestId("lightbox")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "T1-lightbox-dark.png") });
  await page.keyboard.press("Escape");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(400); // let the theme transition finish
  await page.screenshot({ path: join(SHOTS, "T1-media-light.png") });
});
