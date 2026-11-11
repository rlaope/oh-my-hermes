// Shots for the ACP adapter work: the New session menu, an OpenCode chat and its approval card, dark and light.
// Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after (skipped otherwise). The "before" run is on the base
// commit, where OpenCode is not in the menu: the chat and approval shots then show Claude Code for comparison.
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
  test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
  await mock("mock.reset");
});

async function open(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "opencode"];
  }, theme);
  await page.goto("/");
}

for (const theme of ["dark", "light"]) {
  test(`shots: menu, chat and approval (${theme})`, async ({ page }) => {
    await open(page, theme);
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-agent-claude")).toBeVisible();
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `acp-opencode-menu-${TAG}-${theme}.png`), animations: "disabled" });
    const oc = page.getByTestId("session-agent-opencode");
    const agent = (await oc.count()) ? "opencode" : "claude";
    await page.getByTestId(`session-agent-${agent}`).click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await page.getByTestId("composer").fill("Add a dark mode toggle to the settings page");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "done", { timeout: 10_000 });
    await page.mouse.move(900, 790);
    await page.screenshot({ path: join(SHOTS, `acp-opencode-chat-${TAG}-${theme}.png`), animations: "disabled" });
    await page.getByTestId("composer").fill("/approve clean the build folder");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("card-approval")).toBeVisible();
    await page.screenshot({ path: join(SHOTS, `acp-opencode-approval-${TAG}-${theme}.png`), animations: "disabled" });
  });
}

