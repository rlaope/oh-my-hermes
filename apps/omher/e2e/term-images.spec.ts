// Pictures a program prints (src/sessions/term/engine-image.ts), on the mock host: a tiny sixel and a tiny iTerm2
// OSC 1337 PNG are drawn by xterm's image add-on (its canvas layer is on the screen, and its store holds them) and
// nothing is printed as text. With Settings > Terminal > Show images off, the add-on is not loaded and the same
// bytes leave no picture (and still no text). The store is capped at 32 MB a terminal.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** a 1x1 red PNG, as iTerm2's inline image protocol carries it */
const PNG_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==";
const PNG_BYTES = 70;
const OSC_1337 = `\x1b]1337;File=inline=1;size=${PNG_BYTES}:${PNG_1x1}\x07`;
/** a 2x6 red sixel */
const SIXEL = "\x1bPq#0;2;100;0;0#0~~\x1b\\";

type Probe = { layer: boolean; usage: number; images: number; text: string };
/** The shown terminal: its image layer, what the add-on stores (MB) and holds, and its screen as text. */
const probe = (page: Page) =>
  page.evaluate(async (): Promise<Probe> => {
    type Addon = { constructor: { name: string }; storageUsage?: number; storageLimit?: number; _storage?: { _images?: Map<unknown, unknown> } };
    type T = { element?: HTMLElement; rows: number; buffer: { active: { viewportY: number; getLine(i: number): { translateToString(t: boolean): string } | undefined } }; _addonManager?: { _addons?: { instance: Addon }[] } };
    const host = document.querySelector('[data-testid="terminal"] .xterm') as HTMLElement;
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    const addon = (t._addonManager?._addons ?? []).map((a) => a.instance).find((a) => typeof a.storageUsage === "number" && "storageLimit" in a);
    const b = t.buffer.active;
    const lines: string[] = [];
    for (let i = 0; i < t.rows; i++) lines.push(b.getLine(b.viewportY + i)?.translateToString(true) ?? "");
    return {
      layer: !!host.querySelector("canvas.xterm-image-layer-top"),
      usage: addon?.storageUsage ?? -1,
      images: addon?._storage?._images?.size ?? -1,
      text: lines.join("\n"),
    };
  });

const storageLimit = (page: Page) =>
  page.evaluate(() => {
    type T = { element?: HTMLElement; _addonManager?: { _addons?: { instance: { storageLimit?: number } }[] } };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    return (t._addonManager?._addons ?? []).map((a) => a.instance.storageLimit).find((n) => typeof n === "number") ?? null;
  });

test("a sixel and an OSC 1337 PNG are drawn by the image add-on, and nothing is printed as text", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  // the add-on's chunk loads lazily: it is on the terminal once its store is there
  await expect.poll(() => storageLimit(page)).toBe(32);
  await feed(page, `\r\nbefore-sixel${SIXEL}after-sixel\r\n`);
  await expect.poll(async () => (await probe(page)).images).toBe(1);
  await feed(page, `before-png${OSC_1337}after-png\r\n`);
  await expect.poll(async () => (await probe(page)).images).toBe(2);
  // the layer goes onto the screen with the next frame that draws a picture
  await expect.poll(async () => (await probe(page)).layer).toBe(true);
  const p = await probe(page);
  expect(p.usage).toBeGreaterThan(0);
  expect(p.text).toContain("before-sixel");
  expect(p.text).toContain("after-png");
  expect(p.text).not.toMatch(/1337|File=|inline=|iVBOR|#0;2|~~/);
});

test("with Show images off, no add-on and no picture: the same bytes still print no text", async ({ page }) => {
  await openApp(page, { term: { images: false } });
  await newTerminal(page);
  await feed(page, `\r\nbefore-sixel${SIXEL}after-sixel\r\nbefore-png${OSC_1337}after-png\r\n`);
  const p = await probe(page);
  expect(p.layer).toBe(false);
  expect(p.images).toBe(-1);
  expect(await storageLimit(page)).toBeNull();
  expect(p.text).toContain("before-sixelafter-sixel");
  expect(p.text).not.toMatch(/1337|File=|inline=|iVBOR|#0;2|~~/);
});

test("Settings > Terminal: Show images is on by default; off drops an open terminal's pictures, on brings the add-on back", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await expect.poll(() => storageLimit(page)).toBe(32);
  await feed(page, `\r\n${SIXEL}\r\n`);
  await expect.poll(async () => (await probe(page)).images).toBe(1);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-images-row")).toContainText("Show images in the terminal");
  const sw = page.getByTestId("term-images");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Off" }).click();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ images: false });
  await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect.poll(() => storageLimit(page)).toBeNull();
  expect((await probe(page)).layer).toBe(false);
  // and on again: new pictures are drawn
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ images: true });
  });
  await expect.poll(() => storageLimit(page)).toBe(32);
  await feed(page, `${SIXEL}\r\n`);
  await expect.poll(async () => (await probe(page)).images).toBe(1);
});
