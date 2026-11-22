// A TERMINALS Claude Code or Codex session that cannot continue its conversation keeps it (mock host): after omher
// restarts (a reload with the same storage) the row continues its conversation; when that CLI ends at once (the
// conversation, its account folder or the login is gone) or is not on this computer, the row stays Claude Code /
// Codex, ended or failed, with the same conversation id (it does not go on as a Shell and lose it). Restart continues
// that conversation (`--resume <id>` / `resume <id>`), and "Start a new conversation" is the way out when it is gone
// for good. A Claude Code terminal nobody typed in has no conversation on disk (Claude Code writes it on the first
// message), so after a restart it starts again under the same id instead of failing to continue it. A new Claude Code
// terminal's id is kept only once its CLI started. A continued CLI the person used and then left still goes on as
// the login shell, as before. The mock's Claude Code keeps what it wrote in this page's storage
// (`__omherMockClaudeConvs`) and refuses `--resume` of a conversation it never wrote, as the real one does.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const FOLDER = "/home/you/code/web-app";
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

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

type Call = { op: string; agent?: string; cwd?: string; resume?: string; sessionId?: string };
type Saved = { id: string; agent: string; agentSession?: string; running?: boolean; failed?: boolean };
const starts = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []).filter((c) => c.op === "start"));
const shellStarts = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "start"));
const savedOf = (page: Page, id: string): Promise<Saved | undefined> =>
  page.evaluate((i) => (JSON.parse(localStorage.getItem("omher.resume") || "null")?.sessions ?? []).find((s: Saved) => s.id === i), id);
const screen = (page: Page) => page.locator("[data-testid=terminal] .xterm-rows").last();

/** What the next loads of the page find: CLIs that are not installed, conversations that cannot be continued. */
const nextLoads = (page: Page, o: { missing?: string[]; gone?: string[] }) =>
  page.evaluate((v) => sessionStorage.setItem("__mockWorld", JSON.stringify(v)), o);
/** The same, for this load from now on (Restart). */
const fromNow = (page: Page, o: { missing?: string[]; gone?: string[] }) =>
  page.evaluate((v) => {
    const w = window as unknown as Record<string, unknown>;
    w.__omherMockMissing = v.missing ?? [];
    w.__omherMockGoneConversations = v.gone ?? [];
    sessionStorage.setItem("__mockWorld", JSON.stringify(v));
  }, o);

async function open(page: Page) {
  await page.addInitScript((folder) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.termpanel.tabs", "__omherMockHistory", "__omherMockClaudeConvs", "omher.term"])
        localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = folder;
    w.__omherMockAgents = ["claude", "codex", "grok", "omh", "pi"];
    const world = JSON.parse(sessionStorage.getItem("__mockWorld") || "{}") as { missing?: string[]; gone?: string[] };
    w.__omherMockMissing = world.missing ?? [];
    w.__omherMockGoneConversations = world.gone ?? [];
  }, FOLDER);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** Pick `agent` from the TERMINALS + menu in FOLDER; its session id. */
async function pick(page: Page, agent: string): Promise<string> {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  return (await page.getByTestId("terminal").getAttribute("data-session"))!;
}

/** Type `text` and Enter in the open terminal, as the person does. */
async function say(page: Page, text: string) {
  await page.locator("[data-testid=terminal] .xterm-helper-textarea").last().focus();
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
}

/** A new Claude Code terminal in FOLDER, running; with `talk`, the person said something in it (so Claude Code wrote
 *  the conversation). Its session id and conversation id. */
async function claude(page: Page, talk = true): Promise<{ id: string; conv: string }> {
  const id = await pick(page, "claude");
  await expect(screen(page)).toContainText("(mock)");
  const conv = (await starts(page))[0].sessionId!;
  expect(conv).toMatch(UUID4);
  if (talk) {
    await say(page, "remember MARIGOLD");
    await expect(screen(page)).toContainText("you said");
  }
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: true });
  return { id, conv };
}

async function openRow(page: Page, id: string) {
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-ended")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a Claude Code terminal whose conversation cannot be continued after a restart stays Claude Code, ended, and Restart continues it", async ({ page }) => {
  await open(page);
  const { id, conv } = await claude(page);

  await nextLoads(page, { gone: [conv] });
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", cwd: FOLDER, resume: conv })]);
  // its CLI ended at once: the row is still Claude Code with the same conversation, ended (no Shell started there)
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: false });
  await openRow(page, id);
  await expect(screen(page)).toContainText(`No conversation found with session ID: ${conv}`);
  await expect(page.getByTestId(`session-${id}`).getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
  await expect(page.getByTestId("session-fresh")).toBeVisible();
  expect(await shellStarts(page)).toEqual([]);

  // the conversation is back (the account folder returned): Restart continues it, with no new id
  await fromNow(page, {});
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  const again = (await starts(page))[1];
  expect(again).toMatchObject({ agent: "claude", cwd: FOLDER, resume: conv });
  expect(again.sessionId).toBeUndefined();
  await expect(screen(page)).toContainText("(mock)");
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: true });

  // and the next restart continues it by itself, as before
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", resume: conv })]);
});

test("a conversation gone for good: Restart fails again, and Start a new conversation starts one under a new id", async ({ page }) => {
  await open(page);
  const { id, conv } = await claude(page);

  await nextLoads(page, { gone: [conv] });
  await page.reload();
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: false });
  await openRow(page, id);

  // still gone: Restart tries the same conversation and ends the same way, keeping it
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  expect((await starts(page))[1]).toMatchObject({ agent: "claude", resume: conv });
  await expect(page.getByTestId("session-fresh")).toBeVisible();
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: false });

  // the way out: a new conversation in the same row, folder and agent
  await page.getByTestId("session-fresh").click();
  await expect.poll(async () => (await starts(page)).length).toBe(3);
  const fresh = (await starts(page))[2];
  expect(fresh).toMatchObject({ agent: "claude", cwd: FOLDER });
  expect(fresh.resume).toBeUndefined();
  expect(fresh.sessionId).toMatch(UUID4);
  expect(fresh.sessionId).not.toBe(conv);
  await expect(screen(page)).toContainText("(mock)");
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: fresh.sessionId, running: true });
});

test("a Claude Code terminal nobody typed in starts again under the same id after a restart, and runs", async ({ page }) => {
  await open(page);
  const { id, conv } = await claude(page, false);

  await page.reload();
  // Claude Code never wrote that conversation: no `--resume` (it would refuse it), the same id as a new one
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", cwd: FOLDER, sessionId: conv })]);
  expect((await starts(page))[0].resume).toBeUndefined();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  // the mock's CLI prints its banner or its refusal, never both: the banner means it took the id
  await expect(screen(page)).toContainText("(mock)");
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: true });

  // once something is said in it, the next restart continues it
  await say(page, "hello");
  await expect(screen(page)).toContainText("you said");
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", resume: conv })]);
  expect((await starts(page))[0].sessionId).toBeUndefined();
});

test("a Claude Code terminal whose CLI is gone after a restart fails, keeps its conversation, and Restart continues it once the CLI is back", async ({ page }) => {
  await open(page);
  const { id, conv } = await claude(page);

  await nextLoads(page, { missing: ["claude"] });
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", resume: conv })]);
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: false, failed: true });
  await openRow(page, id);
  await expect(page.getByTestId("session-ended")).toContainText("Claude Code is not installed");
  // a CLI that is not there is not a conversation that is gone: Restart is the way, once it is installed
  await expect(page.getByTestId("session-fresh")).toHaveCount(0);

  // Restart while it is still missing: refused again, and the conversation id is not replaced
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  expect((await starts(page))[1]).toMatchObject({ agent: "claude", resume: conv });
  expect((await starts(page))[1].sessionId).toBeUndefined();
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agentSession: conv, failed: true });

  // installed again: Restart continues the same conversation
  await fromNow(page, {});
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(3);
  expect((await starts(page))[2]).toMatchObject({ agent: "claude", resume: conv });
  expect((await starts(page))[2].sessionId).toBeUndefined();
  await expect(screen(page)).toContainText("(mock)");
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: conv, running: true });
});

test("a new Claude Code terminal that could not start keeps no conversation id, and Restart starts a new conversation", async ({ page }) => {
  await open(page);
  await fromNow(page, { missing: ["claude"] });
  const id = await pick(page, "claude");
  await expect(page.getByTestId("session-ended")).toContainText("Claude Code is not installed");
  const first = (await starts(page))[0];
  expect(first.sessionId).toMatch(UUID4);
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", failed: true });
  expect((await savedOf(page, id))?.agentSession).toBeUndefined();

  await fromNow(page, {});
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  const again = (await starts(page))[1];
  expect(again.resume).toBeUndefined();
  expect(again.sessionId).toMatch(UUID4);
  expect(again.sessionId).not.toBe(first.sessionId);
  await expect(screen(page)).toContainText("(mock)");
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "claude", agentSession: again.sessionId, running: true });
});

test("a Codex terminal whose conversation cannot be continued after a restart stays Codex, ended; Restart and a new conversation", async ({ page }) => {
  await open(page);
  const id = await pick(page, "codex");
  await expect(screen(page)).toContainText("(mock)");
  // its Codex holds conversation A open; the page learns it 5 s after the start
  const A = "01a1f29c-c5b1-7301-a199-2dd07ff4b0aa";
  const pty = await page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
  await page.evaluate(([p, c]) => void (((window as unknown as { __omherMockCodexOwn?: Record<number, string> }).__omherMockCodexOwn ??= {})[p as number] = c as string), [pty, A] as const);
  await expect.poll(async () => (await savedOf(page, id))?.agentSession, { timeout: 15_000 }).toBe(A);

  await nextLoads(page, { gone: [A] });
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex", resume: A })]);
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "codex", agentSession: A, running: false });
  await openRow(page, id);
  expect(await shellStarts(page)).toEqual([]);

  // still gone: Restart fails the same way and keeps it
  await page.getByTestId("session-restart").click();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  expect((await starts(page))[1]).toMatchObject({ agent: "codex", resume: A });
  await expect(page.getByTestId("session-fresh")).toBeVisible();
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "codex", agentSession: A, running: false });

  // a new conversation: Codex starts with no id, and the row forgets the old one
  await page.getByTestId("session-fresh").click();
  await expect.poll(async () => (await starts(page)).length).toBe(3);
  expect((await starts(page))[2].resume).toBeUndefined();
  await expect(screen(page)).toContainText("(mock)");
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "codex", running: true });
  expect((await savedOf(page, id))?.agentSession).toBeUndefined();
});

test("a continued Claude Code the person used and then left goes on as the login shell, as before", async ({ page }) => {
  await open(page);
  const { id, conv } = await claude(page);
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", resume: conv })]);
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(screen(page)).toContainText("(mock)");
  // the person types /exit at once: their keys say it was used, however soon it ended
  await say(page, "/exit");
  await expect.poll(() => savedOf(page, id)).toMatchObject({ agent: "shell" });
  expect((await savedOf(page, id))?.agentSession).toBeUndefined();
  await expect.poll(async () => (await shellStarts(page)).length).toBe(1);
});
