// TERMINALS restore (mock host): a Claude Code terminal starts under an id omher made (`--session-id`), and after
// omher restarts (a reload with the same storage; the mock host starts empty, as the shell does) it continues that
// conversation (`--resume <same id>`) in the same folder, once; an agent without its own conversation comes back
// paused as before.
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

type Call = { op: string; agent?: string; cwd?: string; resume?: string; sessionId?: string; account?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const starts = async (page: Page) => (await calls(page)).filter((c) => c.op === "start");
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));

async function open(page: Page) {
  await page.addInitScript((folder) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.termpanel.tabs"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = folder;
    w.__omherMockAgents = ["claude", "codex", "grok", "omh", "pi"];
  }, FOLDER);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** Start `agent` from the TERMINALS + menu in FOLDER; its session id. */
async function newTerm(page: Page, agent: string): Promise<string> {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows").last()).toContainText("(mock)");
  return (await page.getByTestId("terminal").getAttribute("data-session"))!;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a Claude Code terminal starts under an id omher made and continues it after a restart, once", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  const first = await starts(page);
  expect(first).toHaveLength(1);
  expect(first[0]).toMatchObject({ agent: "claude", cwd: FOLDER });
  expect(first[0].resume).toBeUndefined();
  const conv = first[0].sessionId!;
  expect(conv).toMatch(UUID4);
  // the id is kept with the session, and it was running
  await expect.poll(async () => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === id)).toMatchObject({ agent: "claude", agentSession: conv, running: true });

  await page.reload();
  await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  // it starts by itself, continuing the same conversation in the same folder: no new id, no Resume button
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", cwd: FOLDER, resume: conv })]);
  expect((await starts(page))[0].sessionId).toBeUndefined();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.getByTestId("session-paused")).toHaveCount(0);
  await expect(page.locator(".xterm-rows").last()).toContainText("(mock)");
  await page.waitForTimeout(300);
  expect(await starts(page)).toHaveLength(1);
  // the id stays the same across a second restart
  await expect.poll(async () => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === id)?.agentSession).toBe(conv);
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "claude", resume: conv })]);
});

test("an agent with no conversation of its own (Grok) still comes back paused and starts only on Resume", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "grok");
  expect((await starts(page))[0].sessionId).toBeUndefined();
  await expect.poll(async () => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === id)?.running).toBe(true);
  await page.reload();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await page.waitForTimeout(300);
  expect(await starts(page)).toEqual([]);
});

