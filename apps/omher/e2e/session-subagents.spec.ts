// A SESSIONS chat shows the subagents its agent starts: one card per fan-out with one row each (name, task, state,
// time; opens to its steps and answer), a subagent's approval names it, the header's panel button opens Plans for
// that session alone, and work left in the background after a turn is said in the header. Events are the ones the
// Claude adapter emitted for a real run (src-tauri/tests/fixtures/real/claude-9-*.jsonl). Read-only: nothing in
// these views assigns, steers or stops a subagent.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

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

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function session(page: Page, first: string) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("two subagents in parallel: one card, one row each, live then answered", async ({ page }) => {
  await session(page, "/subagents");
  const card = page.getByTestId("fanout-card");
  await expect(card).toHaveCount(1);
  const rows = card.getByTestId("subagent-row");
  await expect(rows).toHaveCount(2);
  // name and task, never the word "helper"
  await expect(rows.nth(0).getByTestId("subagent-goal")).toHaveText("general-purpose · Read a.txt first line");
  await expect(rows.nth(1).getByTestId("subagent-goal")).toHaveText("general-purpose · Count lines of b.txt");
  await expect(rows.nth(0)).toHaveAttribute("data-agent", "claude");
  // the first hands back while the second still works: the card stays running, the turn is not over
  await expect(rows.nth(0)).toHaveAttribute("data-state", "done");
  await expect(rows.nth(1)).toHaveAttribute("data-state", "running");
  await expect(rows.nth(0).getByTestId("subagent-line")).toHaveText("alpha line");
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(page.getByTestId("panel-button")).toHaveAttribute("data-working", "1");
  await expect(page.getByTestId("panel-button-live")).toBeVisible();
  // both done: the card reads "Ran 2 subagents", the session is idle
  await expect(rows.nth(1)).toHaveAttribute("data-state", "done");
  await expect(card).toHaveAttribute("data-state", "done");
  await expect(card.getByTestId("fanout-summary")).toContainText("2 subagents");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("panel-button")).toHaveAttribute("data-working", "0");
  // a row opens to its own steps and its answer
  await rows.nth(1).getByTestId("subagent-open").click();
  await expect(rows.nth(1).getByTestId("subagent-step")).toHaveText(["b.txt"]);
  await expect(rows.nth(1).getByTestId("subagent-answer")).toHaveText("3");
  await expect(page.locator("body")).not.toContainText(/helper/i);
  // nothing was sent to the agent for the subagents: one send, no steering
  expect((await calls(page)).filter((c) => c.op === "chat.input").map((c) => c.input?.kind)).toEqual(["send"]);
});

test("a subagent's approval names the subagent; answering it lets the subagent finish", async ({ page }) => {
  await session(page, "/subask");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("card-subagent")).toHaveText("Subagent Write c.txt via echo asks");
  await expect(card.locator(".card-cmd")).toHaveText("echo three > c.txt");
  await expect(page.getByTestId("session-status")).toHaveText("Needs you");
  await card.locator(".card-btn", { hasText: "Allow once" }).click();
  const row = page.getByTestId("fanout-card").getByTestId("subagent-row");
  await expect(row).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  const approve = (await calls(page)).find((c) => c.input?.kind === "approve");
  expect(approve?.input?.choice).toBe("once");
});

test("the session header's panel button opens Plans for that session alone", async ({ page }) => {
  await session(page, "/subagents");
  await expect(page.getByTestId("fanout-card")).toHaveAttribute("data-state", "done");
  // before the agent's own record exists: the chat's rows
  await page.getByTestId("panel-button").click();
  const panel = page.getByTestId("panel-runs");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("session-plans-rows").getByTestId("subagent-row")).toHaveCount(2);
  // the agent wrote its record: the session's own run, as a graph with each subagent's node
  await mock("mock.sessionRun");
  await page.getByTestId("panel-button").click();
  await page.getByTestId("panel-button").click();
  const box = panel.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", "claude:11111111-2222-4333-8444-555555555555");
  await expect(box.locator("[data-testid=run-node]")).toHaveCount(2);
  await expect(box.getByTestId("node-title")).toHaveText(["Read a.txt first line", "Count lines of b.txt"]);
  // the bot's own runs are not listed in a session's panel
  await expect(panel.getByTestId("cli-run-row")).toHaveCount(0);
  await expect(panel.getByTestId("run-row")).toHaveCount(0);
  // the fan-out card's Plans button opens the same panel
  await page.getByTestId("panel-button").click();
  await expect(panel).toHaveCount(0);
  await page.getByTestId("fanout-open").click();
  await expect(page.getByTestId("panel-runs")).toHaveAttribute("data-session", /.+/);
});

test("work left in the background after a turn is said in the header until it ends", async ({ page }) => {
  await session(page, "/background");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-background")).toHaveText("1 still running in the background");
  await expect(page.getByTestId("session-background")).toHaveCount(0);
});

test("shots: a session's subagents, the subagent's ask, and its Plans", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await session(page, "/subagents hold");
  await expect(page.getByTestId("subagent-row").nth(0)).toHaveAttribute("data-state", "done");
  await page.mouse.move(900, 790);
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "B1-session-subagents-live.png") });
  await page.getByTestId("subagent-row").nth(0).getByTestId("subagent-open").click();
  await page.screenshot({ path: join(SHOTS, "B2-subagent-opened.png") });
  await mock("mock.sessionRun");
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("run-graph-box")).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "B3-session-plans.png") });
  await page.getByTestId("panel-button").click();
  // Esc is the agent's interrupt
  await page.getByTestId("composer").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("/subask");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-subagent")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "B4-subagent-ask.png") });
});
