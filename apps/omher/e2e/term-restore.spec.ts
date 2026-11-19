// TERMINALS restore (mock host): a Claude Code terminal starts under an id omher made (`--session-id`), and after
// omher restarts (a reload with the same storage; the mock host starts empty, as the shell does) it continues that
// conversation (`--resume <same id>`) in the same folder, once; a Codex terminal asks the shell which conversation its
// own Codex holds open (5 s after it starts, then every 15 s) and continues it (`codex resume <id>`) the same way; no
// other terminal's conversation ever comes to it, whatever order Codex writes in or rows close or exit; an agent without its own conversation comes back
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

const A = "01a1f29c-c5b1-7301-a199-2dd07ff4b024";
const B = "01a1f29c-c5b1-7301-a199-2dd07ff4b025";
const C = "01a1f29c-c5b1-7301-a199-2dd07ff4b026";
const ptyOf = (page: Page, id: string) => page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
/** The Codex now running in session `id`'s terminal holds conversation `conv`'s rollout open, as a real one does once
 *  it answered its first prompt. */
async function holds(page: Page, id: string, conv: string) {
  const pty = await ptyOf(page, id);
  expect(pty).not.toBeNull();
  await page.evaluate(([p, c]) => void (((window as unknown as { __omherMockCodexOwn?: Record<number, string> }).__omherMockCodexOwn ??= {})[p as number] = c as string), [pty, conv] as const);
}
/** What the page asked the shell about its Codex terminals' conversations. */
const asks = (page: Page) => page.evaluate(() => ((window as unknown as { __omherPastReads?: { op: string; pty?: number }[] }).__omherPastReads ?? []).filter((r) => r.op === "own"));
const conv = async (page: Page, id: string) => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === id)?.agentSession;
async function closeRow(page: Page, id: string) {
  const card = page.getByTestId(`session-${id}`);
  await card.hover();
  await card.getByTestId("session-close").click();
  await page.getByTestId(`session-confirm-${id}`).getByTestId("session-stop").click();
  await expect(card).toHaveCount(0);
}

test("a Codex terminal learns its conversation from its own Codex and continues it after a restart", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "codex");
  const first = await starts(page);
  expect(first).toEqual([expect.objectContaining({ agent: "codex", cwd: FOLDER })]);
  expect(first[0].resume).toBeUndefined();
  expect(first[0].sessionId).toBeUndefined();
  // its Codex answers the first prompt and holds its rollout open; 5 s after the start the page asks the shell
  await holds(page, id, A);
  await expect.poll(() => conv(page, id), { timeout: 15_000 }).toBe(A);
  // the ask named only this terminal's pty, and asking stopped once it was answered
  const pty = await ptyOf(page, id);
  await page.waitForTimeout(300);
  expect(await asks(page)).toEqual([{ op: "own", agent: "codex", pty }]);

  await page.reload();
  await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  // it starts by itself as `codex resume <id>` in the same folder, and asks for nothing again
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex", cwd: FOLDER, resume: A })]);
  await page.waitForTimeout(6_000);
  expect(await asks(page)).toEqual([]);
});

test("two Codex terminals in one folder each learn only their own conversation, whichever Codex writes first", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const a = await newTerm(page, "codex");
  const b = await newTerm(page, "codex");
  // the second terminal's Codex answers first; the first one's has no rollout yet when both ask
  await holds(page, b, B);
  await expect.poll(() => conv(page, b), { timeout: 15_000 }).toBe(B);
  await expect.poll(async () => (await asks(page)).length, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await flush(page);
  expect(await conv(page, a)).toBeUndefined();
  // then the first one's writes its own: it learns that one at its next ask, never the other's
  await holds(page, a, A);
  await expect.poll(() => conv(page, a), { timeout: 20_000 }).toBe(A);
  expect(await conv(page, b)).toBe(B);
  // each ask named one of the two terminals' own ptys, nothing else
  const ptys = [await ptyOf(page, a), await ptyOf(page, b)];
  expect([...new Set((await asks(page)).map((r) => r.pty))].sort()).toEqual([...ptys].sort());
  await page.reload();
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  expect((await starts(page)).map((c) => c.resume).sort()).toEqual([A, B]);
  expect([await conv(page, a), await conv(page, b)]).toEqual([A, B]);
});

test("closing one of two Codex terminals in a folder never hands its conversation to the other", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const a = await newTerm(page, "codex");
  const b = await newTerm(page, "codex");
  // the second one's Codex wrote its conversation, and that terminal is closed before it asked
  await holds(page, b, B);
  const closedPty = await ptyOf(page, b);
  await closeRow(page, b);
  await expect.poll(async () => (await asks(page)).length, { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  await flush(page);
  expect(await conv(page, a)).toBeUndefined();
  // the one left learns its own once its Codex writes it
  await holds(page, a, A);
  await expect.poll(() => conv(page, a), { timeout: 20_000 }).toBe(A);
  expect((await asks(page)).map((r) => r.pty)).not.toContain(closedPty);
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex", resume: A })]);
});

test("a Codex that exits to the shell gives its conversation to no other terminal, and its shell row is not resumed", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "codex");
  const b = await newTerm(page, "codex");
  // the second one's Codex wrote its conversation, then ends (/exit) before it asked: its row goes on as its shell
  await holds(page, b, B);
  const codexPty = await ptyOf(page, b);
  await page.evaluate(async (p) => {
    const m = await import("/src/sessions/host.ts" as string);
    await m.getHost().write(p, "/exit\r");
  }, codexPty);
  await expect.poll(async () => (await saved(page))?.sessions?.find((s: { id: string }) => s.id === b)?.agent).toBe("shell");
  await expect.poll(() => ptyOf(page, b)).not.toBe(codexPty);
  // the person types codex in that shell: the row shows Codex, but it is a shell row and asks nothing
  const shellPty = await ptyOf(page, b);
  await page.evaluate((p) => (window as unknown as { __omherEmitSessionFg(x: { id: number; agent: string }): void }).__omherEmitSessionFg({ id: p!, agent: "codex" }), shellPty);
  await expect(page.getByTestId(`session-${b}`).getByTestId("term-row-mark")).toHaveAttribute("data-agent", "codex");
  // the first one asks after 5 s: its Codex holds nothing yet, so it learns nothing, and never the other's
  await expect.poll(async () => (await asks(page)).length, { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  await flush(page);
  expect([await conv(page, a), await conv(page, b)]).toEqual([undefined, undefined]);
  expect((await asks(page)).map((r) => r.pty)).toEqual([await ptyOf(page, a)]);
  // after a restart neither continues anything: both come back paused
  await page.reload();
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  await page.waitForTimeout(300);
  expect(await starts(page)).toEqual([]);
});

test("a Codex terminal started after another closed in its folder learns its own conversation", async ({ page }) => {
  await open(page);
  // the first one never wrote a conversation and is closed
  const first = await newTerm(page, "codex");
  await closeRow(page, first);
  const second = await newTerm(page, "codex");
  expect(second).not.toBe(first);
  await holds(page, second, B);
  await expect.poll(() => conv(page, second), { timeout: 15_000 }).toBe(B);
  await page.reload();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex", resume: B })]);
});

test("Resume right after a restart learns only the new Codex's own conversation", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const a = await newTerm(page, "codex");
  const b = await newTerm(page, "codex");
  // the second one's Codex wrote a conversation and was closed; the first never learned one
  await holds(page, b, B);
  await closeRow(page, b);
  await flush(page);
  expect(await conv(page, a)).toBeUndefined();
  await page.reload();
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  expect(await starts(page)).toEqual([]);
  // Resume at once: a new Codex, which holds nothing until it answers, so nothing is learned
  await page.getByTestId("session-resume").click();
  await expect.poll(() => starts(page)).toEqual([expect.objectContaining({ agent: "codex" })]);
  expect((await starts(page))[0].resume).toBeUndefined();
  await expect.poll(async () => (await asks(page)).length, { timeout: 15_000 }).toBe(1);
  await flush(page);
  expect(await conv(page, a)).toBeUndefined();
  // once it answers, its own conversation is the one kept
  await holds(page, a, C);
  await expect.poll(() => conv(page, a), { timeout: 20_000 }).toBe(C);
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

test("a paused terminal shows what it showed before the restart, dimmed under the divider, and starts nothing", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "grok");
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await expect.poll(async () => (await calls(page)).some((c) => c.op === "history.save" && c.key === id && !!c.data?.includes("(mock)"))).toBe(true);
  await page.reload();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  const kept = page.getByTestId("session-paused-history").locator(".xterm-rows");
  await expect(kept).toContainText("(mock)");
  await expect(kept).toContainText(/--- restored .+ ---/);
  const dim = await page.evaluate(() => {
    const span = [...document.querySelectorAll("[data-testid=session-paused-history] .xterm-rows span")].find((s) => s.textContent?.includes("(mock)"));
    return span ? span.className : "";
  });
  expect(dim).toContain("xterm-dim");
  // nothing started and no session terminal was made; typing there goes nowhere
  await page.getByTestId("session-paused-history").click();
  await page.keyboard.type("ls\r");
  await page.waitForTimeout(300);
  expect(await starts(page)).toEqual([]);
  expect((await calls(page)).filter((c) => c.op === "write")).toEqual([]);
  // Resume starts it, with the same history written back first
  await page.getByTestId("session-resume").click();
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  await expect(screen(page)).toContainText(/--- restored .+ ---/);
});

const history = async (page: Page) => (await calls(page)).filter((c) => c.op.startsWith("history."));
/** The page saves history every 30 s and when it goes away; the test asks for it now, as the page going away does. */
const flush = (page: Page) => page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
const screen = (page: Page) => page.locator("[data-testid=terminal] .xterm-rows");
/** Rows of the open terminal, top to bottom, with text; none while its rows are not in the page yet (a slow
 *  computer mounts the terminal after the row opens). */
const rows = (page: Page, sel = "[data-testid=terminal] .xterm-rows") =>
  page.evaluate((s) => [...(document.querySelector(s)?.children ?? [])].map((r) => (r.textContent ?? "").replace(/\u00a0/g, " ").trimEnd()).filter(Boolean), sel);

test("the scrollback comes back dimmed, under a divider, before the program's new output; closing removes it", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  const pty = await page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
  await page.evaluate((p) => (window as unknown as { __omherMockOut(id: number, d: string): boolean }).__omherMockOut(p!, "\x1b[32mbefore-restart-line\x1b[0m\r\n"), pty);
  await expect(screen(page)).toContainText("before-restart-line");
  await flush(page);
  await expect.poll(async () => (await history(page)).filter((c) => c.op === "history.save" && c.key === id).pop()?.data ?? "").toContain("before-restart-line");

  // a slow computer: the shell answers the history read late, and the program still starts only after it is in
  await page.addInitScript(() => ((window as unknown as Record<string, unknown>).__omherMockHistoryDelay = 400));
  await page.reload();
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(screen(page)).toBeAttached();
  // the kept text holds the old banner too: wait for the new program's own banner, below the divider
  const below = (r: string[]) => r.findLastIndex((l) => l.includes("(mock)")) > r.findIndex((l) => /^--- restored .+ ---$/.test(l));
  await expect.poll(async () => below(await rows(page))).toBe(true);
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
  // and before the program started
  const order = (await calls(page)).filter((c) => c.op === "history.read" || c.op === "start").map((c) => c.op);
  expect(order).toEqual(["history.read", "start"]);
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

test("a save already on its way when history is turned off does not make the file again", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  // hold the next save at the host's door, as a slow disk would, with the real history controller and Settings
  await page.evaluate(async () => {
    const w = window as unknown as Record<string, unknown>;
    const h = ((await import("/src/sessions/host.ts" as string)) as { getHost(): { historySave(k: string, t: string, s: number): Promise<void> } }).getHost();
    const real = h.historySave.bind(h);
    h.historySave = async (k, t, s) => {
      h.historySave = real;
      w.__savePending = true;
      await new Promise<void>((r) => (w.__releaseSave = r));
      try {
        await real(k, t, s);
      } finally {
        w.__saveDone = true;
      }
    };
    window.dispatchEvent(new Event("pagehide"));
  });
  await expect.poll(() => page.evaluate(() => !!(window as unknown as { __savePending?: boolean }).__savePending)).toBe(true);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await page.getByTestId("term-keep-history").getByRole("radio", { name: "Off" }).click();
  await expect.poll(async () => (await history(page)).some((c) => c.op === "history.clear")).toBe(true);
  await page.evaluate(() => (window as unknown as { __releaseSave(): void }).__releaseSave());
  await expect.poll(() => page.evaluate(() => !!(window as unknown as { __saveDone?: boolean }).__saveDone)).toBe(true);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("__omherMockHistory") || "{}"))).not.toHaveProperty(id);
  // turned on again, the next save is kept
  await page.getByTestId("term-keep-history").getByRole("radio", { name: "On" }).click();
  await flush(page);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("__omherMockHistory") || "{}"))).toHaveProperty(id);
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

  // a slow computer: the shell answers the history read late
  await page.addInitScript(() => ((window as unknown as Record<string, unknown>).__omherMockHistoryDelay = 400));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  // nothing starts until the panel shows
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (window as unknown as { __omherShellCalls?: unknown[] }).__omherShellCalls ?? [])).toEqual([]);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["api", "api"]);
  await page.getByTestId("termpanel-tab").first().getByRole("tab").click();
  // the kept text holds the old shell's first line too: wait for the new shell's, below the divider
  const sel = '[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows';
  await expect
    .poll(async () => {
      const r = await rows(page, sel);
      return r.findLastIndex((l) => l.includes("login shell in")) > r.findIndex((l) => /^--- restored .+ ---$/.test(l));
    })
    .toBe(true);
  const r = await rows(page, sel);
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
