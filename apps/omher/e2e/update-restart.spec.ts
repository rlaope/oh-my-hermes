// An update whose restart does not happen. No Tauri here: `window.__omherUpdateHost` stands in for the shell's
// updater, and its relaunch never ends the page (as when the shell refuses or loses the restart). The page waits
// (`window.__omherRestartWaitMs`, short here), then shows "Waiting to restart" with Restart again / Later.
// Restart again relaunches without installing again and saves what is open first, every time.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS || "";

async function stub(page: Page, relaunch: "resolve" | "reject", theme: "dark" | "light" = "dark") {
  await page.addInitScript(
    ({ relaunch, theme }) => {
      localStorage.setItem("omher.theme", theme);
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      w.__updCalls = calls;
      w.__omherRestartWaitMs = 400;
      // a write of the resume snapshot (saveResumeNow) shows in the call list as "save"
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k: string, v: string) {
        if (k === "omher.resume") calls.push("save");
        return set.call(this, k, v);
      };
      w.__omherUpdateHost = {
        check: async () => {
          calls.push("check");
          return {
            version: "0.2.4",
            install: async (onProgress: (p: { done: number; total: number | null }) => void) => {
              calls.push("install");
              onProgress({ done: 1000, total: 1000 });
            },
          };
        },
        relaunch: async () => {
          calls.push("relaunch");
          if (relaunch === "reject") throw new Error("restart refused");
        },
      };
    },
    { relaunch, theme },
  );
}

const calls = (page: Page) => page.evaluate(() => (window as unknown as { __updCalls: string[] }).__updCalls);
/** The calls without the snapshot writes the app makes on its own, and whether a save came right before each relaunch. */
const sequence = async (page: Page) => {
  const all = await calls(page);
  const savedFirst = all.every((c, i) => c !== "relaunch" || all[i - 1] === "save");
  return { ops: all.filter((c) => c !== "save"), savedFirst };
};

async function installAndWait(page: Page) {
  await page.goto("/");
  await page.getByTestId("update-btn").click();
  await page.getByTestId("update-go").click();
  await expect(page.getByTestId("update-waiting")).toBeVisible();
}

test("a restart that does not happen: Waiting to restart, then Restart again relaunches without installing again", async ({ page }) => {
  await stub(page, "resolve");
  await installAndWait(page);
  await expect(page.getByTestId("update-waiting-title")).toHaveText("Waiting to restart");
  // inside the sidebar, under "You", and it leaves the icon row above it uncovered
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  const card = (await page.getByTestId("update-waiting").boundingBox())!;
  const settings = (await page.getByTestId("nav-settings").boundingBox())!;
  expect(card.x + card.width).toBeLessThanOrEqual(side.x + side.width);
  expect(card.y).toBeGreaterThanOrEqual(settings.y + settings.height);
  await expect(page.getByTestId("update-waiting")).toContainText("omher 0.2.4 is installed, but omher has not restarted yet.");
  await expect(page.getByTestId("update-restart-again")).toHaveText("Restart again");
  await expect(page.getByTestId("update-later")).toHaveText("Later");
  expect(await sequence(page)).toEqual({ ops: ["check", "install", "relaunch"], savedFirst: true });

  await page.getByTestId("update-restart-again").click();
  await expect(page.getByTestId("update-progress")).toHaveText("Restarting…");
  await expect(page.getByTestId("update-waiting")).toBeVisible();
  expect(await sequence(page)).toEqual({ ops: ["check", "install", "relaunch", "relaunch"], savedFirst: true });
});

test("a refused restart waits too; Later closes the card and the button restarts later, never installing again", async ({ page }) => {
  await stub(page, "reject");
  await installAndWait(page);
  await page.getByTestId("update-later").click();
  await expect(page.getByTestId("update-waiting")).toHaveCount(0);
  const btn = page.getByTestId("update-btn");
  await expect(btn).toHaveText("Restart for 0.2.4");
  // the person comes back to it: the confirm still asks first, then only relaunches
  await btn.click();
  await expect(page.getByTestId("update-confirm")).toBeVisible();
  await page.getByTestId("update-go").click();
  await expect(page.getByTestId("update-waiting")).toBeVisible();
  expect(await sequence(page)).toEqual({ ops: ["check", "install", "relaunch", "relaunch"], savedFirst: true });
});

test("screenshots: Waiting to restart in dark and light", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await stub(page, "resolve", theme);
    await installAndWait(page);
    await page.mouse.move(700, 400);
    await page.screenshot({ path: join(SHOTS, `update-waiting-${theme}.png`), animations: "disabled" });
  }
});
