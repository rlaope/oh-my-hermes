// Shots of the three session defects (exit reason, plan card, a subagent's edit), dark and light, on the mock host.
// Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after; without OMHER_SHOTS every test is skipped.
import { test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
  // no bot named after the product in a shot
  await mock("bots.rename", { bot: "default", name: "Mira" });
});

async function session(page: Page, theme: string, agent: "claude" | "codex", first: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/calc";
  }, theme);
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

const shot = (page: Page, what: string, theme: string) =>
  page.screenshot({ path: join(SHOTS, `sessions-027-${what}-${TAG}-${theme}.png`), animations: "disabled" });

for (const theme of ["dark", "light"] as const) {
  test(`exit ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await session(page, theme, "codex", "/quit");
    await page.getByTestId("session-ended").waitFor();
    await page.mouse.move(0, 0);
    await shot(page, "exit", theme);
  });

  test(`plancard ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await session(page, theme, "claude", "/plan");
    await page.getByTestId("card-approval").waitFor();
    await page.mouse.move(0, 0);
    await shot(page, "plancard", theme);
  });

  test(`subdiff ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await session(page, theme, "codex", "/subedit");
    const row = page.getByTestId("subagent-row");
    await row.and(page.locator("[data-state=done]")).waitFor();
    await page.waitForTimeout(500);
    await row.getByTestId("subagent-open").click();
    const steps = row.getByTestId("subagent-step");
    await steps.last().waitFor();
    await steps.last().click();
    await page.waitForTimeout(300);
    await page.mouse.move(0, 0);
    await shot(page, "subdiff", theme);
  });
}
