// SESSIONS open as a chat: a mock Claude Code / Codex agent (the browser build's MockHost speaks the same
// events as the Rust adapters) and oh-my-hermes as a Hermes chat in the folder (mock bridge folder.open).
// Bubbles, the one progress line, an approval card answered, Esc = the agent's interrupt, the model button,
// the Terminal toggle, and close stopping the agent.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

async function mock(op: string): Promise<{ calls?: { op: string; params: Record<string, unknown> }[] }> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const out = await new Promise<{ result?: { calls?: { op: string; params: Record<string, unknown> }[] } }>((res) => {
    ws.onmessage = (m) => res(JSON.parse(String(m.data)));
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
  return out.result ?? {};
}
const bridgeCalls = async () => (await mock("mock.calls")).calls ?? [];

type Call = { op: string; agent?: string; cwd?: string; id?: number; resume?: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function open(page: Page, folder = "/Users/you/code/omher") {
  await page.addInitScript((f) => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = f;
  }, folder);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A New session chat on `agent` in the dialog's folder; nothing runs until its first message. */
async function draft(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
}

/** `agent` started by its first message (`first`), its answer done. */
async function start(page: Page, agent: string, first = "/status") {
  await draft(page, agent);
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

async function settle(page: Page) {
  await page.mouse.move(900, 790);
  await page.waitForTimeout(350);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Claude Code opens as a chat: bubbles, one progress line, no terminal", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  await expect(page.getByTestId("session-title")).toHaveText("New session");
  expect((await calls(page)).filter((c) => c.op === "chat.start")).toEqual([]);
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.getByTestId("live-ring")).toHaveCount(0); // a draft: no ring
  await page.getByTestId("composer").fill("explain the sessions feature");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  // the first message names the session; the agent and the full path sit next to it
  await expect(page.getByTestId("session-title")).toHaveText("explain the sessions feature");
  await expect(page.getByTestId("session-agent")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/omher");
  await expect(page.getByTestId("model-label")).toHaveText("Opus 5.5");
  // the UI sent only an agent id and a folder
  const st = (await calls(page)).find((c) => c.op === "chat.start")!;
  expect(Object.keys(st).sort()).toEqual(["agent", "cwd", "id", "op"]);
  expect(st).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher" });
  await expect(page.getByTestId("bubble-user")).toHaveText("explain the sessions feature");
  await expect(row.getByTestId("live-ring")).toBeVisible(); // the answer ring while the turn runs, as on a bot row
  await expect(row.getByTestId("live-dot")).toHaveCount(0); // a chat row rings; only a terminal row keeps the dot
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  await expect(page.getByTestId("bubble-bot")).toHaveText("(mock Claude Code) You said: explain the sessions feature");
  // one activity line for the turn, collapsing to a summary; the step detail is the tool's argument
  await expect(page.getByTestId("activity")).toHaveCount(1);
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("activity-text")).toContainText("Worked for");
  await page.getByTestId("activity-toggle").click();
  await expect(page.getByTestId("activity-step")).toHaveText(/Read\s*README\.md/);
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  const send = (await calls(page)).find((c) => c.op === "chat.input")!;
  expect(send.input).toEqual({ kind: "send", text: "explain the sessions feature" });
  // a session chat never goes to the bot's main chat
  expect((await bridgeCalls()).filter((c) => c.op === "chat.send")).toHaveLength(0);
});

test("a file in a session's answer sits under its bubble in the same column, one face per run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await draft(page, "claude");
  // the mock agent echoes the text: a MEDIA line in it comes back as a file under the answer
  await page.getByTestId("composer").fill("here\nMEDIA:/w/media/report.zip");
  await page.getByTestId("composer").press("Enter");
  const chat = page.getByTestId("session-chat");
  const msg = chat.getByTestId("bubble-bot").filter({ has: page.getByTestId("media") });
  await expect(msg).toHaveCount(1);
  await expect(msg).not.toContainText("MEDIA:");
  const [bub, tile] = await Promise.all(
    [msg.locator(".b"), msg.getByTestId("media").locator(":scope > *").first()].map((l) => l.evaluate((e) => e.getBoundingClientRect().toJSON() as DOMRect)),
  );
  expect(Math.abs(tile.left - bub.left)).toBeLessThanOrEqual(1);
  expect(tile.top).toBeGreaterThan(bub.bottom);
  await expect(msg.locator(".msg-face:not(.blank)")).toHaveCount(1);
});

test("the empty section's New session row opens a New session chat, then gives way to the session row", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("session-start")).toHaveAttribute("title", /Claude Code/);
  await page.getByTestId("session-start").click();
  await page.getByTestId("session-agent-claude").click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-none")).toHaveCount(0);
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(1);
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher" });
});

test("an approval card in a session: Deny first, answered with Allow for session, the row waits", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Run this command?");
  await expect(card.locator(".card-cmd")).toHaveText("rm -rf ./build");
  await expect(card.getByTestId("card-risk")).toContainText("Deletes files");
  expect(await card.locator(".card-btn").allInnerTexts()).toEqual(["Deny", "Allow once", "Allow for session"]);
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row).toHaveAttribute("data-needs-you", "true");
  // one amber signal pair in the row ("waiting" and the dot): the line under the name stays the gray agent name
  await expect(row.getByTestId("session-sub")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-status")).toHaveText("Needs you");
  // the bot row's waiting state: amber dot and "waiting", the ring stops
  await expect(row.getByTestId("needs")).toBeVisible();
  await expect(row.getByTestId("bot-time")).toHaveText("waiting");
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  // the activity line waits with the card
  await expect(page.getByTestId("activity-text")).toContainText("Waiting for approval");

  await card.getByRole("button", { name: "Allow for session" }).click();
  await expect(page.getByTestId("card-line")).toContainText("Allowed for session");
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("Cleaned the build folder (allowed for this session).");
  await expect(row).not.toHaveAttribute("data-needs-you", "true");
  const approve = (await calls(page)).find((c) => c.op === "chat.input" && c.input?.kind === "approve")!;
  expect(approve.input).toMatchObject({ kind: "approve", choice: "session" });
  expect((await bridgeCalls()).filter((c) => c.op === "approval.respond")).toHaveLength(0);
});

test("Esc and Stop send the agent's own interrupt; the model button switches the agent's model", async ({ page }) => {
  await open(page);
  await draft(page, "codex");
  await page.getByTestId("composer").fill("/slow");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("model-label")).toHaveText("GPT-6.1 Sol");
  await expect(page.getByTestId("bubble-streaming")).toContainText("line 2");
  await page.getByTestId("timeline").click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "interrupted");
  expect((await calls(page)).filter((c) => c.input?.kind === "interrupt")).toHaveLength(1);

  await page.getByTestId("model-pill").click();
  await expect(page.getByTestId("model-opt")).toHaveText(["GPT-6.1 Sol", "GPT-6.1 Terra"]);
  await page.getByTestId("model-opt").nth(1).click();
  await expect(page.getByTestId("model-label")).toHaveText("GPT-6.1 Terra");
  expect((await calls(page)).find((c) => c.input?.kind === "model")!.input).toEqual({ kind: "model", model: "gpt-6.1-terra" });
  // the header keeps the toggle, the model button and the panel button (the session's Plans) only
  await page.keyboard.press("Escape");
  expect(await page.locator("[data-testid=head-right] > *").count()).toBe(3);
  await expect(page.locator("[data-testid=head-right] > *").last()).toHaveAttribute("data-testid", "panel-button");
});

test("a chat session resets first and loads xterm only when its Terminal view opens", async ({ page }) => {
  const scripts: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "script") scripts.push(r.url());
  });
  await open(page);
  await start(page, "claude");
  const ops = (await calls(page)).map((c) => c.op);
  expect(ops.filter((o) => o === "reset")).toHaveLength(1);
  expect(ops.indexOf("reset")).toBeLessThan(ops.indexOf("chat.start"));
  await page.waitForLoadState("networkidle");
  expect(scripts.filter((u) => u.includes("xterm"))).toEqual([]);
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect(scripts.some((u) => u.includes("xterm"))).toBe(true);
});

test("Terminal toggle: Claude Code's terminal resumes the same conversation, and back to the chat continues it", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot")).toBeVisible();
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "done");
  const toggle = page.getByTestId("session-terminal-toggle");
  await expect(toggle).toHaveAttribute("aria-label", "Open in Terminal");
  await expect(toggle).toHaveAttribute("aria-description", /continuing this conversation/);
  await toggle.click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await expect(page.getByTestId("session-status")).toHaveText("Terminal view");
  let c = await calls(page);
  expect(c.filter((x) => x.op === "chat.close")).toHaveLength(1); // the chat process stopped first
  expect(c.find((x) => x.op === "start")).toMatchObject({ agent: "claude", resume: "11111111-2222-4333-8444-555555555555" });

  await page.getByTestId("session-terminal-toggle").click(); // "Chat"
  await expect(page.getByTestId("session-chat")).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("bubble-user")).toHaveText("hello"); // the chat kept its bubbles
  c = await calls(page);
  expect(c.filter((x) => x.op === "close")).toHaveLength(1); // the terminal stopped
  expect(c.filter((x) => x.op === "chat.start").pop()).toMatchObject({ agent: "claude", resume: "11111111-2222-4333-8444-555555555555" });
});

test("Codex's terminal view starts its TUI fresh and the chat keeps running", async ({ page }) => {
  await open(page);
  await start(page, "codex");
  const toggle = page.getByTestId("session-terminal-toggle");
  await expect(toggle).toHaveAttribute("aria-description", /starts Codex fresh/);
  await toggle.click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  // xterm loads on this first terminal view, and the terminal starts after it
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  const c = await calls(page);
  expect(c.find((x) => x.op === "start")).toMatchObject({ agent: "codex" });
  expect(c.find((x) => x.op === "start")?.resume).toBeUndefined();
  expect(c.filter((x) => x.op === "chat.close")).toHaveLength(0);
  await page.getByTestId("session-terminal-toggle").click();
  await page.getByTestId("composer").fill("still here?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("still here?");
});

test("oh-my-hermes opens as a Hermes chat in the folder through the bridge", async ({ page }) => {
  await open(page, "/Users/you/work/api");
  await draft(page, "omh");
  await page.getByTestId("composer").fill("what is here?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("oh-my-hermes");
  await expect(page.getByTestId("model-label")).toHaveText("Opus 5.5");
  const opened = (await bridgeCalls()).find((c) => c.op === "folder.open")!;
  expect(opened.params).toEqual({ bot: "kami", cwd: "/Users/you/work/api" });
  await expect(page.getByTestId("bubble-bot")).toHaveText("(mock oh-my-hermes) Working in /Users/you/work/api: what is here?");
  await page.getByTestId("activity-toggle").click();
  await expect(page.getByTestId("activity-step")).toHaveText(/Ran\s*ls \/Users\/you\/work\/api/);
  const sent = (await bridgeCalls()).filter((c) => c.op === "chat.send");
  expect(sent).toHaveLength(1);
  expect(sent[0].params).toEqual({ bot: "kami", session: expect.stringMatching(/^f-/), text: "what is here?" });
  // the bot's own chat is untouched
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("timeline")).not.toContainText("Working in /Users/you/work/api");

  // closing asks, then closes the folder chat in Hermes
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await row.hover();
  await row.getByTestId("session-close").click();
  await page.getByTestId("session-stop").click();
  await expect.poll(async () => (await bridgeCalls()).filter((c) => c.op === "folder.close").length).toBe(1);
});

test("close stops the agent; an agent that exits ends the session with its reason", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  await page.getByTestId("composer").fill("/exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  await expect(page.getByTestId("session-ended")).toContainText("Ended");
  await expect(page.getByTestId("composer")).toBeDisabled();
  await expect(page.getByTestId("composer")).toHaveAttribute("placeholder", "Claude Code has ended");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.getByTestId("session-sub")).toHaveText("Claude Code · Ended");

  await start(page, "codex");
  const row2 = page.locator("[data-testid=session-list] .ss-row").first();
  await row2.hover();
  await row2.getByTestId("session-close").click();
  // the question names the session it stops, agent and folder
  await expect(page.locator("[data-testid^=session-confirm-]")).toHaveAttribute("aria-label", "Stop Codex in omher?");
  await page.getByTestId("session-stop").click();
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(1);
  expect((await calls(page)).filter((c) => c.op === "chat.close")).toHaveLength(1);
});

test("an ended session restarts in the same chat; Claude Code and Codex continue their conversation", async ({ page }) => {
  await open(page);
  await draft(page, "codex");
  await page.getByTestId("composer").fill("/exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  await page.getByTestId("session-restart").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toBeEnabled();
  const starts = (await calls(page)).filter((c) => c.op === "chat.start");
  expect(starts).toHaveLength(2);
  // the second start continues the Codex thread the first one reported
  expect(starts[0].resume).toBeUndefined();
  expect(starts[1].resume).toMatch(/^codex-mock-/);
  await page.getByTestId("composer").fill("hello again");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("You said: hello again");
  // the earlier exchange is still on screen
  await expect(page.getByTestId("bubble-user").first()).toHaveText("/exit");
});

test("a session's question becomes a question card; a failed command and a missing login stay calm", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  await page.getByTestId("composer").fill("/ask");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("card-clarify");
  await expect(card).toContainText("Which greeting should go in greet.txt?");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.getByTestId("bot-time")).toHaveText("waiting");
  await card.getByRole("button", { name: "hi", exact: true }).click();
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("Wrote hi to greet.txt.");
  const answer = (await calls(page)).find((c) => c.op === "chat.input" && c.input?.kind === "clarify")!;
  expect(answer.input).toMatchObject({ kind: "clarify", answer: "hi" });
  await expect(row).not.toHaveAttribute("data-needs-you", "true");

  await page.getByTestId("composer").fill("/bad");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("Exit code: 127.");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");

  await page.getByTestId("composer").fill("/signedout");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("activity").last()).toContainText("not signed in");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("composer")).toBeEnabled();
});

test("the approval card says which folder the command runs in", async ({ page }) => {
  await open(page, "/Users/you/code/web-app");
  await draft(page, "claude");
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("card-approval");
  await expect(card.locator(".card-cmd")).toHaveText("rm -rf ./build");
  await expect(card.getByTestId("card-cwd")).toHaveText("in /Users/you/code/web-app");
  await expect(card.getByRole("button")).toHaveText(["Deny", "Allow once", "Allow for session"]);
});

test("screenshots: a chat session with an approval, dark and light", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  await open(page, "/Users/you/code/omher");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api"));
  await start(page, "omh");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher"));
  await start(page, "codex", "run the tests");
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "done");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/oh-my-hermes"));
  await start(page, "claude", "explain the sessions feature");
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "done");
  await page.getByTestId("composer").fill("/approve clean the build folder");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-approval")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "T14-chat-dark.png") });
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "T14-chat-light.png") });
  await page.getByTestId("card-approval").getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("card-line")).toBeVisible();
  await page.getByTestId("model-pill").click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, "T14-model-light.png") });
  await page.keyboard.press("Escape");
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "T14-terminal-light.png") });
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("dark");
  });
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.getByTestId("session-chat")).toBeVisible();
  await page.locator("[data-testid=session-list] .ss-row").nth(2).locator(".ss-open").click();
  await expect(page.getByTestId("session-agent")).toHaveText("oh-my-hermes");
  await page.getByTestId("composer").fill("what is in this folder?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toBeVisible();
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "T14-omh-dark.png") });
});
