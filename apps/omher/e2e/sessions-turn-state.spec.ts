// A finished turn stays finished. OmO (and pi / oh-my-pi) send a status of their own after the turn's end
// (`setStatus` after `agent_end`, tests/fixtures/real/omo-1-plain.jsonl): the chat stays idle (Send, no spinner,
// header Ready, no ring on the row). Stop ends a turn for good. A terminal session that exits (Ctrl+C, `exit`)
// gets the Ended line with Restart, which starts the program again (Grok: a new conversation); an ended DSH chat's
// Restart continues DeepSeek Harness's own session.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const SHOT_TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string) {
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

type Call = { op: string; agent?: string; cwd?: string; id?: number; resume?: string; input?: { kind: string } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function open(page: Page, installed = ["claude", "codex", "omh", "omo", "grok", "dsh"]) {
  await page.addInitScript((a) => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.resume");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/omher";
    w.__omherMockAgents = a;
  }, installed);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function draft(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
}

async function send(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.keyboard.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a status after the turn's end leaves the chat idle: Send, no spinner, Ready, no ring", async ({ page }) => {
  await open(page);
  await draft(page, "omo");
  await send(page, "/late");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: /^ok$/ })).toBeVisible();
  // the late status and thinking have arrived (the mock sends them 50 and 100 ms after the end)
  await page.waitForTimeout(600);
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.locator('[data-testid=activity][data-state="live"]')).toHaveCount(0);
  await expect(page.getByTestId("typing")).toHaveCount(0);
  await expect(page.getByText("mem:khope-sionic-ai-d09472c9")).toHaveCount(0);
  await expect(page.getByTestId("send")).toBeVisible();
  await expect(page.getByTestId("stop")).toHaveCount(0);
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  // a turn with no steps says only how long it took
  await expect(page.getByTestId("activity-toggle").last()).toHaveText(/^✓Worked for \d+s$/);
});

test("before/after shots of the OmO case (OMHER_SHOTS)", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  for (const scheme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await mock("mock.reset");
    await open(page);
    await draft(page, "omo");
    await send(page, "안녕 /late");
    await expect(page.getByTestId("bubble-bot").filter({ hasText: /^ok$/ })).toBeVisible();
    await page.waitForTimeout(1500);
    await page.mouse.move(900, 790);
    await page.screenshot({ path: join(SHOTS, `orch-turn-${SHOT_TAG}-${scheme}.png`), animations: "disabled" });
  }
});

test("Stop ends the turn for good: a status after it does not bring the spinner back", async ({ page }) => {
  await open(page);
  await draft(page, "omo");
  await send(page, "/slow");
  await expect(page.getByTestId("stop")).toBeVisible();
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("send")).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.locator('[data-testid=activity][data-state="interrupted"]')).toHaveCount(1);
});

test("a terminal session that exits shows Ended with Restart, which starts the program again", async ({ page }) => {
  await open(page);
  await draft(page, "grok");
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "start").length).toBe(1);
  const first = (await calls(page)).find((c) => c.op === "start")!;
  // the program quits (Ctrl+D in the mock; Ctrl+C belongs to the program and is passed through as typed)
  await page.locator(".term-host").click();
  await page.keyboard.press("Control+C");
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await page.keyboard.press("Control+D");
  const ended = page.getByTestId("session-ended");
  await expect(ended).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  const restart = page.getByTestId("session-restart");
  // Grok's terminal does not continue a conversation: Restart starts a new one in the same folder
  await expect(restart).toHaveAttribute("title", "Start Grok again in this folder, as a new conversation");
  await restart.click();
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "start").length).toBe(2);
  const again = (await calls(page)).filter((c) => c.op === "start")[1];
  expect(again).toMatchObject({ agent: "grok", cwd: first.cwd });
  expect(first.resume).toBeUndefined();
  expect(again.resume).toBeUndefined();
  await expect(page.getByTestId("session-status")).toHaveText("Running");
  await expect(page.getByTestId("terminal")).toBeVisible();
  // it ends again by `exit` and still offers a new conversation
  await page.locator(".term-host").click();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-restart")).toHaveAttribute("title", "Start Grok again in this folder, as a new conversation");
});

test("an ended DSH chat restarts as a chat that continues DeepSeek Harness's own session", async ({ page }) => {
  await open(page);
  await draft(page, "dsh");
  await send(page, "Remember PLUM-42.");
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("(mock DSH) You said: Remember PLUM-42.");
  await send(page, "/exit");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  const restart = page.getByTestId("session-restart");
  await expect(restart).toHaveAttribute("title", "Start DSH again, continuing this conversation");
  await restart.click();
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "chat.start").length).toBe(2);
  const starts = (await calls(page)).filter((c) => c.op === "chat.start");
  expect(starts[0]).toMatchObject({ agent: "dsh" });
  expect(starts[0].resume).toBeUndefined();
  // the harness's own `session-<uuid>`, not a terminal `--resume` id
  expect(starts[1]).toMatchObject({ agent: "dsh", cwd: starts[0].cwd, resume: "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8" });
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  // a chat, never a terminal
  const all = await calls(page);
  expect(all.filter((c) => c.op === "start")).toHaveLength(0);
  await expect(page.getByTestId("terminal")).toHaveCount(0);
});

test("an agent that dies mid-turn leaves the chat ended, not working", async ({ page }) => {
  await open(page);
  await draft(page, "omo");
  await send(page, "/die");
  // the program exits during the turn and no turn.end of its own arrives
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  await expect(page.locator('[data-testid=activity][data-state="live"]')).toHaveCount(0);
  await expect(page.locator('[data-testid=activity][data-state="ended"]')).toHaveCount(1);
  await expect(page.getByTestId("stop")).toHaveCount(0);
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  await expect(page.getByTestId("session-restart")).toHaveAttribute("title", "Start OmO again, continuing this conversation");
});
