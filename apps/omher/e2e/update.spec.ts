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
    w.__omherUpdateHost = {
      check: async () => {
        calls.push("check");
        if (plan.checkFails) throw new Error("network down");
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
