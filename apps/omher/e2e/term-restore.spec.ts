// TERMINALS restore (mock host): a Claude Code terminal starts under an id omher made (`--session-id`), and after
// omher restarts (a reload with the same storage; the mock host starts empty, as the shell does) it continues that
// conversation (`--resume <same id>`) in the same folder, once; a Codex terminal asks the shell for its conversation id
// after 5 s and continues it (`codex resume <id>`) the same way; an agent without its own conversation comes back
// paused as before. Each terminal's scrollback is kept by the shell (`history.*` calls; the mock keeps it in this
// page's storage) and written back, dimmed, under a "--- restored <time> ---" line before the new output; closing
// removes it; Settings > Terminal turns it off. The bottom panel's tabs come back with their folders and scrollback.
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

type Call = { op: string; agent?: string; cwd?: string; resume?: string; sessionId?: string; account?: string; key?: string; data?: string; keep?: string[] };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const starts = async (page: Page) => (await calls(page)).filter((c) => c.op === "start");
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));

async function open(page: Page) {
  await page.addInitScript((folder) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.termpanel.tabs", "__omherMockHistory", "omher.term"]) localStorage.removeItem(k);
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

test("a Codex terminal learns its conversation id from the shell and continues it after a restart", async ({ page }) => {
  const THREAD = "01a1f29c-c5b1-7301-a199-2dd07ff4b024";
  await page.addInitScript((thread) => {
    (window as unknown as { __omherMockCodexLatest?: string }).__omherMockCodexLatest = thread;
  }, THREAD);
  await open(page);
  const t0 = Date.now() / 1000;
  const id = await newTerm(page, "codex");
  const first = await starts(page);
  expect(first).toEqual([expect.objectContaining({ agent: "codex", cwd: FOLDER })]);
  expect(first[0].resume).toBeUndefined();
  expect(first[0].sessionId).toBeUndefined();
  // after the program has run 5 s the page asks for the newest Codex conversation in its folder started since then
  await expect.poll(async () => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === id)?.agentSession, { timeout: 15_000 }).toBe(THREAD);
  const reads = await page.evaluate(() => (window as unknown as { __omherPastReads?: { op: string; cwd?: string; since?: number }[] }).__omherPastReads ?? []);
  const latest = reads.filter((r) => r.op === "latest");
  expect(latest).toHaveLength(1);
  expect(latest[0].cwd).toBe(FOLDER);
  expect(latest[0].since!).toBeGreaterThanOrEqual(Math.floor(t0) - 2);
  expect(latest[0].since!).toBeLessThanOrEqual(Date.now() / 1000);

  await page.reload();
  await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  // it starts by itself as `codex resume <id>` in the same folder, and asks for no id again
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex", cwd: FOLDER, resume: THREAD })]);
  await page.waitForTimeout(6_000);
  const again = await page.evaluate(() => ((window as unknown as { __omherPastReads?: { op: string }[] }).__omherPastReads ?? []).filter((r) => r.op === "latest"));
  expect(again).toEqual([]);
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

const history = async (page: Page) => (await calls(page)).filter((c) => c.op.startsWith("history."));
/** The page saves history every 30 s and when it goes away; the test asks for it now, as the page going away does. */
const flush = (page: Page) => page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
const screen = (page: Page) => page.locator("[data-testid=terminal] .xterm-rows");
/** Rows of the open terminal, top to bottom, with text. */
const rows = (page: Page, sel = "[data-testid=terminal] .xterm-rows") =>
  page.evaluate((s) => [...document.querySelector(s)!.children].map((r) => (r.textContent ?? "").replace(/\u00a0/g, " ").trimEnd()).filter(Boolean), sel);

test("the scrollback comes back dimmed, under a divider, before the program's new output; closing removes it", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  const pty = await page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
  await page.evaluate((p) => (window as unknown as { __omherMockOut(id: number, d: string): boolean }).__omherMockOut(p!, "\x1b[32mbefore-restart-line\x1b[0m\r\n"), pty);
  await expect(screen(page)).toContainText("before-restart-line");
  await flush(page);
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.save" && c.key === id).pop()?.data ?? "").toContain("before-restart-line");

  await page.reload();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(screen(page)).toContainText("(mock)");
  const r = await rows(page);
  const old = r.findIndex((l) => l.includes("before-restart-line"));
  const line = r.findIndex((l) => /^--- restored .+ ---$/.test(l));
  const fresh = r.findLastIndex((l) => l.includes("(mock)"));
  expect(old).toBeGreaterThanOrEqual(0);
  expect(line).toBeGreaterThan(old);
  expect(fresh).toBeGreaterThan(line);
  // the old text is drawn faint
  const dim = await page.evaluate(() => {
    const span = [...document.querySelectorAll("[data-testid=terminal] .xterm-rows span")].find((s) => s.textContent?.includes("before-restart-line"));
    return span ? span.className : "";
  });
  expect(dim).toContain("xterm-dim");
  // read once, as the startup prune kept it
  expect((await history(page)).filter((c) => c.op === "history.read").map((c) => c.key)).toEqual([id]);
  expect((await history(page)).find((c) => c.op === "history.prune")?.keep).toContain(id);

  // closing the row removes its kept text
  await page.getByTestId(`session-${id}`).hover();
  await page.evaluate((i) => (window as unknown as { __omherSessions: { close(id: string): void } }).__omherSessions.close(i), id);
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.remove").map((c) => c.key)).toEqual([id]);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("__omherMockHistory") || "{}"))).not.toHaveProperty(id);
});

test("Keep terminal history off: one clear, and no history call after it", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const sw = page.getByTestId("term-keep-history");
  await expect(page.getByTestId("term-keep-history-row")).toContainText("Keep history across restarts");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Off" }).click();
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.clear")).toHaveLength(1);
  const before = (await history(page)).length;
  await flush(page);
  await page.reload();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(screen(page)).toContainText("(mock)");
  await page.waitForTimeout(300);
  expect(await history(page)).toEqual([]);
  expect(await rows(page)).not.toContainEqual(expect.stringMatching(/restored/));
  expect(before).toBeGreaterThan(0);
});

test("the bottom panel's tabs come back after a restart in their folders, with their scrollback", async ({ page }) => {
  await open(page);
  await page.evaluate(async () => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd("/home/you/code/api");
  });
  await page.keyboard.press("Control+Backquote");
  const shown = page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');
  await expect(shown).toContainText("login shell in /home/you/code/api");
  await page.keyboard.type("echo panel-before\r");
  await expect(shown).toContainText("echo panel-before");
  await page.getByTestId("termpanel-new").click();
  await expect(page.getByTestId("termpanel-tab")).toHaveCount(2);
  await flush(page);
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.save" && c.key === "panel-1").pop()?.data ?? "").toContain("panel-before");

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  // nothing starts until the panel shows
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (window as unknown as { __omherShellCalls?: unknown[] }).__omherShellCalls ?? [])).toEqual([]);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["api", "api"]);
  await page.getByTestId("termpanel-tab").first().getByRole("tab").click();
  await expect(shown).toContainText("login shell in /home/you/code/api");
  const r = await rows(page, '[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');
  const old = r.findIndex((l) => l.includes("echo panel-before"));
  const line = r.findIndex((l) => /^--- restored .+ ---$/.test(l));
  const fresh = r.findLastIndex((l) => l.includes("login shell in"));
  expect(old).toBeGreaterThanOrEqual(0);
  expect(line).toBeGreaterThan(old);
  expect(fresh).toBeGreaterThan(line);
  const starts = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string; cwd: string | null }[] }).__omherShellCalls ?? []).filter((c) => c.op === "start"));
  // a fresh login shell per tab, in its own folder
  expect(starts.map((c) => c.cwd)).toEqual(["/home/you/code/api", "/home/you/code/api"]);
  // closing a tab removes its kept text
  await page.getByTestId("termpanel-tab-close").first().click();
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.remove").map((c) => c.key)).toEqual(["panel-1"]);
});
