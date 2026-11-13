// In-app update button in the sidebar's user row. No Tauri here: `window.__omherUpdateHost` stands in
// for the shell's updater (check / install with progress / relaunch) and records what the page asked for.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

type Plan = {
  /** Version a check announces; null = no update. */
  version: string | null;
  /** The check itself throws (offline). */
  checkFails?: boolean;
  /** What the first checks answer, in order, before `version` applies: "fail" throws, "none" finds no update,
   *  "hold" stays unanswered until `window.__updCheckGo()` and then answers with `version`. */
  first?: ("fail" | "none" | "hold")[];
  /** Install throws this message after the progress steps. */
  installFails?: string;
  /** Install waits for `window.__updGo()` before finishing, so the test can see the progress. */
  hold?: boolean;
};

async function stub(page: Page, plan: Plan) {
  await page.addInitScript((plan: Plan) => {
    const w = window as unknown as Record<string, unknown>;
    const calls: string[] = [];
    w.__updCalls = calls;
    let go: () => void = () => {};
    const gate = new Promise<void>((r) => (go = r));
    w.__updGo = () => go();
    const first = [...(plan.first ?? [])];
    let checkGo: () => void = () => {};
    w.__updCheckGo = () => checkGo();
    w.__omherUpdateHost = {
      check: async () => {
        calls.push("check");
        const how = first.shift();
        if (plan.checkFails || how === "fail") throw new Error("network down");
        if (how === "none") return null;
        if (how === "hold") await new Promise<void>((r) => (checkGo = r));
        if (!plan.version) return null;
        return {
          version: plan.version,
          install: async (onProgress: (p: { done: number; total: number | null }) => void) => {
            calls.push("install");
            onProgress({ done: 0, total: 1000 });
            onProgress({ done: 420, total: 1000 });
            if (plan.hold) await gate;
            if (plan.installFails) throw new Error(plan.installFails);
            onProgress({ done: 1000, total: 1000 });
          },
        };
      },
      relaunch: async () => {
        calls.push("relaunch");
      },
    };
  }, plan);
}

const calls = (page: Page) => page.evaluate(() => (window as unknown as { __updCalls: string[] }).__updCalls);

test("no update: the user row shows no button", async ({ page }) => {
  await stub(page, { version: null });
  await page.goto("/");
  await expect(page.getByTestId("me")).toBeVisible();
  await expect.poll(() => calls(page)).toEqual(["check"]);
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  await expect(page.getByTestId("update-progress")).toHaveCount(0);
});

test("a failed check stays quiet", async ({ page }) => {
  await stub(page, { version: "0.1.2", checkFails: true });
  await page.goto("/");
  await expect.poll(() => calls(page)).toEqual(["check"]);
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  await expect(page.getByTestId("update-error")).toHaveCount(0);
});

test("update available: button with the version, bottom-left in the user row", async ({ page }) => {
  await stub(page, { version: "0.1.2", hold: true });
  await page.goto("/");
  const btn = page.getByTestId("me").getByTestId("update-btn");
  await expect(btn).toHaveText("Update to 0.1.2");
  // inside the sidebar, below Settings, and nothing in the row overflows the sidebar
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  const b = (await btn.boundingBox())!;
  const settings = (await page.getByTestId("nav-settings").boundingBox())!;
  expect(b.x + b.width).toBeLessThanOrEqual(side.x + side.width);
  expect(b.y).toBeGreaterThan(settings.y);
  expect(b.y + b.height).toBeGreaterThan(side.y + side.height - 60);

  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.mouse.move(700, 400);
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, "omher-update-button.png") });
    await page.getByTestId("sidebar").screenshot({ path: join(SHOTS, "omher-update-sidebar.png") });
  }

  await btn.click();
  await page.getByTestId("update-go").click();
  const prog = page.getByTestId("update-progress");
  await expect(prog).toHaveText("Updating 42%");
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  if (SHOTS) await page.getByTestId("sidebar").screenshot({ path: join(SHOTS, "omher-update-progress.png") });
  await page.evaluate(() => (window as unknown as { __updGo: () => void }).__updGo());
  await expect.poll(() => calls(page)).toEqual(["check", "install", "relaunch"]);
  await expect(prog).toHaveText("Restarting…");
});

test("a failed install says why and offers a retry", async ({ page }) => {
  await stub(page, { version: "0.1.2", installFails: "signature mismatch\nstack…" });
  await page.goto("/");
  await page.getByTestId("update-btn").click();
  await page.getByTestId("update-go").click();
  await expect(page.getByTestId("update-error")).toHaveText("signature mismatch");
  await expect(page.getByTestId("update-btn")).toHaveText("Retry update");
  expect(await calls(page)).toEqual(["check", "install"]);
  // the app stays usable: the composer and the bot list still respond
  await expect(page.getByTestId("side-bots")).toBeVisible();
  // a retry asks again
  await page.getByTestId("update-btn").click();
  await expect(page.getByTestId("update-confirm")).toBeVisible();
  await page.getByTestId("update-go").click();
  await expect.poll(() => calls(page)).toEqual(["check", "install", "install"]);
});

// An app that is left open. The page's clock is held by the test, so a jump stands in for the hours an open app
// (or a Mac that slept) lets pass, and a focus or visibility event for the person coming back to the window.
const MIN = 60_000;

async function leftOpen(page: Page) {
  await page.clock.install();
  await page.goto("/");
  await expect(page.getByTestId("me")).toBeVisible();
  await expect.poll(() => calls(page)).toEqual(["check"]);
}

const comesBack = (page: Page, how: "focus" | "visible") =>
  page.evaluate((how) => {
    if (how === "focus") window.dispatchEvent(new Event("focus"));
    else document.dispatchEvent(new Event("visibilitychange"));
  }, how);

test("a check that failed is tried again within minutes, and the button appears", async ({ page }) => {
  await stub(page, { version: "0.2.8", first: ["fail"] });
  await leftOpen(page);
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  await page.clock.fastForward(5 * MIN);
  await expect(page.getByTestId("update-btn")).toHaveText("Update to 0.2.8");
  expect(await calls(page)).toEqual(["check", "check"]);
  await expect(page.getByTestId("update-error")).toHaveCount(0);
});

test("a version published after launch shows when the window gets focus 31 minutes later", async ({ page }) => {
  await stub(page, { version: "0.2.8", first: ["none"] });
  await leftOpen(page);
  await page.clock.fastForward(31 * MIN);
  // no timer was due in that half hour: it is the return to the window that asks
  expect(await calls(page)).toEqual(["check"]);
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  await comesBack(page, "focus");
  await expect(page.getByTestId("update-btn")).toHaveText("Update to 0.2.8");
  expect(await calls(page)).toEqual(["check", "check"]);
});

test("coming back 5 minutes after a good check asks nothing; after 31 minutes it asks once", async ({ page }) => {
  await stub(page, { version: null });
  await leftOpen(page);
  await page.clock.fastForward(5 * MIN);
  await comesBack(page, "focus");
  await comesBack(page, "visible");
  expect(await calls(page)).toEqual(["check"]);
  await page.clock.fastForward(26 * MIN);
  await comesBack(page, "visible");
  await expect.poll(() => calls(page)).toEqual(["check", "check"]);
  // that one was a good check as well, so the half hour starts again
  await page.clock.fastForward(5 * MIN);
  await comesBack(page, "focus");
  expect(await calls(page)).toEqual(["check", "check"]);
});

test("coming back twice while a check is in flight sends one request", async ({ page }) => {
  await stub(page, { version: "0.2.8", first: ["none", "hold"] });
  await leftOpen(page);
  await page.clock.fastForward(31 * MIN);
  await comesBack(page, "focus");
  await comesBack(page, "visible");
  await comesBack(page, "focus");
  expect(await calls(page)).toEqual(["check", "check"]);
  await expect(page.getByTestId("update-btn")).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { __updCheckGo: () => void }).__updCheckGo());
  await expect(page.getByTestId("update-btn")).toHaveText("Update to 0.2.8");
  expect(await calls(page)).toEqual(["check", "check"]);
});
