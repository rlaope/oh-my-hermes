// Shots for the six ACP agents (Kilo Code, Gemini CLI, Qwen Code, Kimi Code, Copilot CLI, Cline) at a 900x600
// window, dark and light: the SESSIONS + menu folded, the same menu with the agents that are not installed opened,
// and an installed agent that is not signed in. Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after (skipped
// otherwise). On the base commit there is no fold and no Gemini CLI: "more" scrolls the menu to its end and "signin"
// shows OpenCode's signed-out turn for comparison.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, args: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...args }));
  });
  ws.close();
}

test.beforeEach(async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
  await mock("mock.reset");
  await mock("bots.rename", { bot: "default", name: "Milo" });
  await page.setViewportSize({ width: 900, height: 600 });
});

async function open(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "opencode", "kilo", "gemini"];
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function menu(page: Page) {
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
  await page.mouse.move(700, 300);
}

for (const theme of ["dark", "light"]) {
  test(`shots: the + menu folded (${theme})`, async ({ page }) => {
    await open(page, theme);
    await menu(page);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `acp-agents-menu-${TAG}-${theme}.png`), animations: "disabled" });
  });

  test(`shots: the + menu with more agents open (${theme})`, async ({ page }) => {
    await open(page, theme);
    await menu(page);
    const more = page.getByTestId("session-more");
    if (await more.count()) {
      await more.click();
      await page.getByTestId("session-agent-cline").evaluate((e) => e.scrollIntoView({ block: "nearest" }));
    } else {
      await page.getByTestId("session-menu-list").evaluate((el) => (el.scrollTop = el.scrollHeight));
    }
    await page.mouse.move(700, 300);
    await page.waitForTimeout(150);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `acp-agents-more-${TAG}-${theme}.png`), animations: "disabled" });
  });

  test(`shots: an installed agent that is not signed in (${theme})`, async ({ page }) => {
    await open(page, theme);
    await menu(page);
    const gemini = page.getByTestId("session-agent-gemini");
    const agent = (await gemini.count()) ? "gemini" : "opencode";
    await page.getByTestId(`session-agent-${agent}`).click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await page.getByTestId("composer").fill(agent === "gemini" ? "Add a dark mode toggle to the settings page" : "/signedout");
    await page.keyboard.press("Enter");
    if (agent === "gemini") await expect(page.getByTestId("session-ended")).toBeVisible({ timeout: 10_000 });
    else await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "error", { timeout: 10_000 });
    await page.mouse.move(700, 120);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `acp-agents-signin-${TAG}-${theme}.png`), animations: "disabled" });
  });
}
