// Shell: sidebar, timeline bubbles, composer send/stop, theme, header right side, screenshots.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

// Headless Chromium reports a light OS scheme; the sketch default is dark.
test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls). */
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
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function setTheme(page: Page, theme: "system" | "dark" | "light") {
  await page.evaluate(async (t) => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme(t);
  }, theme);
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  // init selects the first bot and opens its chat
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("sidebar lists the mock bots and search filters them", async ({ page }) => {
  await open(page);
  const side = page.getByTestId("sidebar");
  for (const name of ["Kami", "Friren", "Hermes"]) await expect(side.getByText(name, { exact: true })).toBeVisible();
  await expect(side.getByText("omher", { exact: true })).toBeVisible();
  for (const nav of ["Settings", "You"]) await expect(side.getByText(nav, { exact: true })).toBeVisible();
  // not in this version yet: shown, disabled, tagged Soon
  for (const id of ["nav-automations", "nav-plugins"]) await expect(side.getByTestId(id)).toHaveText(/(Automations|Plugins)Soon/);
  // Kami starts running in the mock -> live ring around its face
  await expect(page.getByTestId("bot-kami").getByTestId("live-ring")).toBeVisible();
  await page.getByLabel("Search bots").fill("fri");
  await expect(page.getByTestId("bot-friren")).toBeVisible();
  await expect(page.getByTestId("bot-kami")).toHaveCount(0);
  await expect(page.getByTestId("bot-default")).toHaveCount(0);
  await page.getByLabel("Search bots").fill("");
  await expect(page.getByTestId("bot-default")).toBeVisible();
});

test("select Kami shows history as filled bubbles; switching bots swaps the chat", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("timeline").getByText("Summarise the Tauri 2 updater docs.")).toBeVisible();
  await page.getByTestId("bot-kami").click();
  const tl = page.getByTestId("timeline");
  await expect(tl.getByText("gateway 502 로그 좀 봐줄래?")).toBeVisible();
  await expect(tl.getByText("Thanks. Ping me when the retry fix is up.")).toBeVisible();
  // markdown: inline code inside the bot bubble
  await expect(tl.getByTestId("bubble-bot").locator("code").first()).toHaveText("/v1/responses");
  // filled bubbles, no border, radius <= 10px
  const style = await tl.getByTestId("bubble-bot").first().locator(".b").evaluate((el) => {
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, border: cs.borderTopWidth, radius: parseFloat(cs.borderTopLeftRadius) };
  });
  expect(style.bg).toBe("rgb(29, 26, 32)"); // #1d1a20
  expect(style.border).toBe("0px");
  expect(style.radius).toBeLessThanOrEqual(10);
  const me = await tl.getByTestId("bubble-user").first().locator(".b").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(me).toBe("rgb(60, 42, 59)"); // #3c2a3b (OMH soft tint)
  await expect(page.getByTestId("header").getByText("Kami", { exact: true })).toBeVisible();
});

test("Enter sends: user bubble, Stop during the turn, reply bubble arrives", async ({ page }) => {
  await open(page);
  const box = page.getByTestId("composer");
  await box.fill("line one");
  await box.press("Shift+Enter");
  await box.pressSequentially("line two");
  await expect(box).toHaveValue("line one\nline two");
  await box.fill("Check the 502s please");
  await box.press("Enter");
  await expect(box).toHaveValue("");
  const tl = page.getByTestId("timeline");
  await expect(tl.getByTestId("bubble-user").filter({ hasText: "Check the 502s please" })).toBeVisible();
  await expect(page.getByTestId("stop")).toBeVisible();
  await expect(tl.getByTestId("bubble-bot").filter({ hasText: "expired keep-alive connections" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("stop")).toHaveCount(0);
  await expect(page.getByTestId("send")).toBeVisible();
  const calls = (await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.send");
  expect(calls).toEqual([expect.objectContaining({ params: expect.objectContaining({ bot: "kami", text: "Check the 502s please" }) })]);
});

test("Stop interrupts the running turn", async ({ page }) => {
  await open(page);
  await page.getByTestId("composer").fill("long job");
  await page.getByTestId("composer").press("Enter");
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("stop")).toHaveCount(0);
  const ops = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(ops).toContain("chat.interrupt");
});

test("slash shows the skill hint", async ({ page }) => {
  await open(page);
  await page.getByTestId("composer").fill("/pl");
  await expect(page.getByTestId("skill-hint")).toBeVisible();
  await page.getByTestId("composer").fill("hello /plan");
  await expect(page.getByTestId("skill-hint")).toHaveCount(0);
});

test("header right holds only the model pill; name toggles the details column", async ({ page }) => {
  await open(page);
  const right = page.getByTestId("head-right");
  await expect(right.locator(":scope > *")).toHaveCount(1);
  await expect(right).toContainText("Opus 5.5");
  await expect(right).toContainText("High");
  // at most one interactive control (the model picker slot renders one button; the fallback none)
  expect(await right.locator("button, a, [role=button], input, select").count()).toBeLessThanOrEqual(1);
  const details = page.getByTestId("details");
  expect((await details.boundingBox())?.width ?? 0).toBeLessThan(2);
  await page.getByTestId("who").click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(300);
  await page.getByTestId("who").click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBeLessThan(2);
});

test("theme follows the store; dark and light screenshots", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  // a finished turn in the timeline makes the shot closer to the sketch
  await page.getByTestId("composer").fill("Check the 502s please");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "expired keep-alive" })).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("composer").blur();
  await page.screenshot({ path: join(SHOTS, "shell-dark.png") });

  // The store's setTheme (same module instance the app uses; Vite serves it by URL).
  await setTheme(page, "light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  const bg = await page.getByTestId("bubble-bot").first().locator(".b").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(242, 240, 244)"); // #f2f0f4
  await page.getByTestId("composer").blur();
  await page.waitForTimeout(400); // let the 0.2s colour transitions settle
  await page.screenshot({ path: join(SHOTS, "shell-light.png") });

  // persisted, and "system" follows the OS live
  expect(await page.evaluate(() => localStorage.getItem("omher.theme"))).toBe("light");
  await setTheme(page, "system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
