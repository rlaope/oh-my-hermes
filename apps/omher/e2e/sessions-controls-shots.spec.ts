// Shots for the SESSIONS controls work: the permission mode, reasoning effort, the agent's `/` commands, the line
// under the box (branch, context) and a message sent while a turn runs, in a Claude Code chat.
// Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function running(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher";
  }, theme);
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("Look at the README and tell me what this repo does");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

const shot = (page: Page, what: string, theme: string) =>
  page.screenshot({ path: join(SHOTS, `sessions-controls-${what}-${TAG}-${theme}.png`), animations: "disabled" });

for (const theme of ["dark", "light"] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await running(page, theme);
    await page.mouse.move(900, 790);

    // the line under the box (before: folder only)
    await shot(page, "usage", theme);

    // permission mode: its menu (before: the composer row has none)
    const mode = page.getByTestId("session-mode");
    if (await mode.count()) {
      await mode.click();
      await expect(page.getByTestId("session-mode-menu")).toBeVisible();
    }
    await shot(page, "mode", theme);
    await page.keyboard.press("Escape");

    // reasoning effort: the model menu (before: models only)
    await page.getByTestId("model-pill").click();
    await expect(page.getByTestId("model-pop")).toBeVisible();
    await shot(page, "effort", theme);
    await page.keyboard.press("Escape");

    // the agent's own commands on `/` (before: a skill hint)
    await page.getByTestId("composer").fill("/");
    await page.waitForTimeout(200);
    await shot(page, "slash", theme);
    await page.getByTestId("composer").fill("");

    // a message sent while a turn runs
    await page.getByTestId("composer").fill("/slow");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("session-status")).toHaveText("Working");
    await page.getByTestId("composer").fill("Also check the CHANGELOG when you are done");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    await shot(page, "queued", theme);
    await page.getByTestId("stop").click();
  });
}
