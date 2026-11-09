// Appearance: colour sets, bubble styles and text size change the chat live and are remembered.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

test.use({ colorScheme: "dark" });

async function mock(op: string): Promise<any> {
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
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
  return reply.result;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

const css = (page: Page, testId: string, prop: string) =>
  page
    .getByTestId(testId)
    .first()
    .locator(".b")
    .evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

async function appearance(page: Page) {
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("appearance")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await mock("mock.reset");
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("kept")) {
      localStorage.removeItem("omher.look");
      localStorage.removeItem("omher.theme");
    }
  });
});

test("defaults: OMH colours, soft bubbles, small text", async ({ page }) => {
  await open(page);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-palette", "omh");
  await expect(html).toHaveAttribute("data-bubbles", "soft");
  await expect(html).toHaveAttribute("data-text", "small");
  expect(await css(page, "bubble-bot", "font-size")).toBe("13px");
  expect(await css(page, "bubble-bot", "background-color")).toBe("rgb(29, 26, 32)");
});

test("colour set: picking one repaints your bubble, links and accent, and the logo stays", async ({ page }) => {
  await open(page);
  const logoBefore = await page.locator(".brand b").evaluate((e) => getComputedStyle(e).backgroundImage);
  const meBefore = await css(page, "bubble-user", "background-color");
  await appearance(page);
  await expect(page.getByTestId("palette-omh")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("palette-ocean").click();
  await expect(page.locator("html")).toHaveAttribute("data-palette", "ocean");
  await expect(page.getByTestId("palette-ocean")).toHaveAttribute("aria-checked", "true");
  // the selected swatch is gray-framed, never filled with the accent
  expect(await page.getByTestId("palette-ocean").evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
  // preview follows
  const send = await page.locator(".ap-pv-send").evaluate((e) => getComputedStyle(e).backgroundImage);
  expect(send).toContain("rgb(47, 111, 228)"); // #2f6fe4
  await page.getByRole("button", { name: "Close settings" }).click();
  expect(await css(page, "bubble-user", "background-color")).not.toBe(meBefore);
  expect(await css(page, "bubble-user", "background-color")).toBe("rgb(31, 49, 80)"); // #1f3150
  expect(await page.locator(".brand b").evaluate((e) => getComputedStyle(e).backgroundImage)).toBe(logoBefore);
  // light theme has its own tint for the same set
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await css(page, "bubble-user", "background-color")).toBe("rgb(216, 231, 250)"); // #d8e7fa
});

test("bubble styles: solid puts your bubble in the accent; open drops the bot's bubble", async ({ page }) => {
  await open(page);
  await appearance(page);
  await page.getByTestId("bubbles-seg").getByRole("radio", { name: "Solid" }).click();
  await expect(page.getByTestId("bubbles-hint")).toHaveText("Your messages in the accent colour");
  await page.getByRole("button", { name: "Close settings" }).click();
  expect(await css(page, "bubble-user", "background-image")).toContain("linear-gradient");
  expect(await css(page, "bubble-user", "color")).toBe("rgb(255, 255, 255)");

  await appearance(page);
  await page.getByTestId("bubbles-seg").getByRole("radio", { name: "Open" }).click();
  await page.getByRole("button", { name: "Close settings" }).click();
  expect(await css(page, "bubble-bot", "background-color")).toBe("rgba(0, 0, 0, 0)");
  expect(await css(page, "bubble-bot", "padding-left")).toBe("0px");
  // your bubble is back to the soft tint under "open"
  expect(await css(page, "bubble-user", "background-image")).toBe("none");
  // elsewhere answers follow the bot's bubble (same element classes)
  const away = page.getByTestId("timeline").locator("[data-testid=away]").first().locator(".b");
  expect(await away.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
});

test("text size changes messages and the composer; every choice survives a reload", async ({ page }) => {
  await open(page);
  await appearance(page);
  await page.getByTestId("text-seg").getByRole("radio", { name: "Large" }).click();
  await page.getByTestId("palette-forest").click();
  await page.getByTestId("bubbles-seg").getByRole("radio", { name: "Open" }).click();
  await page.getByRole("button", { name: "Close settings" }).click();
  expect(await css(page, "bubble-user", "font-size")).toBe("15px");
  expect(await page.getByTestId("composer").evaluate((e) => getComputedStyle(e).fontSize)).toBe("15px");
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.look"))) ?? "{}")).toEqual({
    palette: "forest",
    bubbles: "open",
    text: "large",
  });
  await page.evaluate(() => sessionStorage.setItem("kept", "1"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-palette", "forest");
  await expect(page.locator("html")).toHaveAttribute("data-bubbles", "open");
  await expect(page.locator("html")).toHaveAttribute("data-text", "large");
});

test("a bad saved look falls back to the defaults", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.look", '{"palette":"neon","bubbles":"round","text":9}'));
  await open(page);
  await expect(page.locator("html")).toHaveAttribute("data-palette", "omh");
  await expect(page.locator("html")).toHaveAttribute("data-bubbles", "soft");
  await expect(page.locator("html")).toHaveAttribute("data-text", "small");
});

test("screenshots: the chat in several looks, and the Appearance page", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1200, height: 760 });
  await open(page);
  await page.getByTestId("composer").fill("Check the 502s please");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "expired keep-alive" })).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("composer").blur();
  const set = (look: Record<string, string>, theme: string) =>
    page.evaluate(
      async ([l, t]) => {
        const m = await import(/* @vite-ignore */ "/src/state/store.ts");
        m.getStore().actions.setLook(l);
        m.getStore().actions.setTheme(t);
      },
      [look, theme] as const,
    );
  const looks: [string, Record<string, string>, string][] = [
    ["look-omh-soft-dark", { palette: "omh", bubbles: "soft", text: "small" }, "dark"],
    ["look-ocean-solid-dark", { palette: "ocean", bubbles: "solid", text: "small" }, "dark"],
    ["look-graphite-open-dark", { palette: "graphite", bubbles: "open", text: "medium" }, "dark"],
    ["look-sunset-soft-light", { palette: "sunset", bubbles: "soft", text: "small" }, "light"],
    ["look-forest-solid-light", { palette: "forest", bubbles: "solid", text: "small" }, "light"],
    ["look-rose-open-light", { palette: "rose", bubbles: "open", text: "medium" }, "light"],
  ];
  for (const [name, look, theme] of looks) {
    await set(look, theme);
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, `${name}.png`) });
  }
  await set({ palette: "omh", bubbles: "soft", text: "small" }, "dark");
  await appearance(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "appearance-dark.png") });
});
