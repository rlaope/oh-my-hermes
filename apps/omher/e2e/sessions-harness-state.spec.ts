// What a person sees when a session's agent cannot hold a chat (QA H4, H5), on the mock host, which emits what the
// shell emits: an old agent that never answers in chat mode ends with a plain reason and an install line instead of
// Working forever; a Codex chat reopened onto a thread that is gone starts a new conversation, says so, and answers.
// Shots: OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
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

async function setup(page: Page, theme: string, globals: Record<string, unknown>) {
  await page.addInitScript(
    ([t, g]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.setItem("omher.theme", t as string);
      Object.assign(w, g);
      w.__omherMockAgents = ["claude", "codex", "omo", "pi"];
      w.__omherPickFolder = "/Users/you/code/web-app";
      if (!sessionStorage.getItem("__kept")) {
        sessionStorage.setItem("__kept", "1");
        localStorage.removeItem("omher.sessions.recent");
        localStorage.removeItem("omher.resume");
      }
    },
    [theme, globals] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function start(page: Page, agent: string, first: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

async function shot(page: Page, what: string, theme: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.mouse.move(5, 5);
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `harness-state-${what}-${TAG}-${theme}.png`), animations: "disabled" });
}

for (const theme of ["dark", "light"] as const) {
  test(`an old agent that never answers in chat mode ends with the reason, not Working (${theme})`, async ({ page }) => {
    await setup(page, theme, { __omherMockNoChat: ["omo"] });
    await start(page, "omo", "Summarize the README");
    await expect(page.getByTestId("bubble-user").last()).toHaveText("Summarize the README");
    const ended = page.getByTestId("session-ended");
    await expect(ended).toContainText("OmO did not answer in chat mode; it may be an old version: npm i -g omo-ai");
    await expect(page.getByTestId("session-status")).toHaveText("Ended");
    // no Stop left behind, and Restart is there
    await expect(page.getByTestId("stop")).toHaveCount(0);
    await expect(page.getByTestId("session-restart")).toBeVisible();
    await shot(page, "stuck", theme);
  });

  test(`a Codex chat reopened onto a gone thread starts a new conversation and answers (${theme})`, async ({ page }) => {
    await setup(page, theme, {});
    await start(page, "codex", "/status");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    // the thread is deleted while omher is closed; omher reopens the chat by itself on the saved thread
    await page.evaluate(() => ((window as unknown as Record<string, unknown>).__omherMockGoneThreads = true));
    await page.addInitScript(() => ((window as unknown as Record<string, unknown>).__omherMockGoneThreads = true));
    await page.reload();
    await expect(page.getByTestId("system-line").last()).toHaveText("The earlier conversation was not found, so a new one started here.");
    await page.getByTestId("composer").fill("Reply with exactly: ok");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("bubble-bot").last()).toContainText("You said: Reply with exactly: ok");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    // nothing about it in the model popover
    await page.getByTestId("model-pill").click();
    await expect(page.getByTestId("model-note")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await shot(page, "resume", theme);
  });
}

test("a Claude Code model picked mid-turn shows as next turn's until that turn starts", async ({ page }) => {
  await setup(page, "dark", {});
  await start(page, "claude", "/status");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("/slow");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  await page.getByTestId("model-pill").click();
  await page.getByTestId("model-opt").filter({ hasText: "Sonnet 5.5" }).click();
  await expect(page.getByTestId("model-label")).toHaveText("Opus 5.5");
  await expect(page.getByTestId("model-next")).toHaveText("Next turn: Sonnet 5.5");
  await page.keyboard.press("Escape");
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("again");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("model-label")).toHaveText("Sonnet 5.5");
  await expect(page.getByTestId("model-next")).toHaveCount(0);
});
