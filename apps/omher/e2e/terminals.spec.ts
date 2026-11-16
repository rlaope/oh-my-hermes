// TERMINALS (termui, owner 2026-11-16): SESSIONS is back as terminal sessions only, grouped by folder, with an
// independent scroll for BOTS (with nested threads) and TERMINALS, and the pinned dock at the bottom of the sidebar.
// 1. the + menu: Shell first, then the CLIs with their official marks; no Chat/Terminal choice anywhere; picking one
//    starts it in a terminal in the folder chip's folder;
// 2. rows: one line [status][mark][title][cli age], grouped under a folder header with the git branch; the mark is
//    TermRowMark and follows session.fgAgent (setSessionFg), status spinner while output flows, check / x on exit;
// 3. scroll: 12 bots x 6 threads and 15 terminals at 900px: both headers visible, each list scrolls on its own, the
//    selected row scrolls into view, the region divider stays put, "Show N more" kept, the dock stays visible;
// 4. dock: pin/unpin/reorder persist across reload; tile click opens and scrolls its row into view; needs/failed dots;
// 5. ⌘N/⌘T open the + menu, ⌘⇧] / ⌘⇧[ step through terminals.
// Shots (taken first): OMHER_SHOTS=<dir> -> termsessions-{sidebar-dark,sidebar-light,many-scroll,plus-menu}.png,
// sidebar-dock-{dark,light}.png, terminals-groups-{dark,light}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

const FOLDERS = ["/home/you/code/web-app", "/home/you/code/omher"];

async function open(page: Page, o: { theme?: "dark" | "light"; roster?: string[]; keep?: boolean } = {}) {
  await page.addInitScript(
    ([theme, folders, roster, keep]) => {
      if (!keep || !sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.dock"]) localStorage.removeItem(k);
        sessionStorage.setItem("__kept", "1");
      }
      if (theme) localStorage.setItem("omher.theme", theme as string);
      if (roster) localStorage.setItem("omher.roster", JSON.stringify(roster));
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = (folders as string[])[0];
      w.__omherMockAgents = ["claude", "codex", "grok", "opencode", "omh", "pi", "omp", "omo"];
      w.__omherBranches = { "/home/you/code/web-app": "feature/checkout-flow", "/home/you/code/omher": "feat/terminal-sessions" };
    },
    [o.theme ?? null, FOLDERS, o.roster ?? null, !!o.keep] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** Start `agent` (or `shell`) from the TERMINALS + menu in `folder` (one of the recent folders, else the picker's). */
async function newTerm(page: Page, agent: string, folder?: string): Promise<string> {
  const before = await page.locator('[data-testid^="session-s"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  if (folder) {
    await page.getByTestId("session-folder").click();
    const recent = page.locator(`[data-testid=session-folder-pick][title="${folder}"]`);
    if (await recent.count()) await recent.click();
    else {
      await page.evaluate((f) => ((window as unknown as Record<string, unknown>).__omherPickFolder = f), folder);
      await page.getByTestId("session-choose").click();
    }
    await expect(page.getByTestId("session-folder")).toHaveAttribute("title", folder);
  }
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows").last()).toContainText("(mock)");
  const after = await page.locator('[data-testid^="session-s"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  const id = after.find((x) => x && !before.includes(x) && /^session-s\d+$/.test(x))!;
  return id.slice("session-".length);
}

const typeIn = async (page: Page, text: string) => {
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
};

const setFg = (page: Page, id: string, agent: string | null) =>
  page.evaluate(([i, a]) => (window as unknown as { __omherSessions: { setSessionFg(id: string, a: string | null): void } }).__omherSessions.setSessionFg(i as string, a as string | null), [id, agent] as const);

/** Claude Code, Codex and Grok running (Grok via a Shell whose foreground CLI is grok), a plain shell, an exited one;
 *  two folders. */
async function seedTerminals(page: Page) {
  const claude = await newTerm(page, "claude", FOLDERS[0]);
  const codex = await newTerm(page, "codex", FOLDERS[0]);
  const shellGrok = await newTerm(page, "shell", FOLDERS[1]);
  await setFg(page, shellGrok, "grok");
  const shell = await newTerm(page, "shell", FOLDERS[1]);
  const done = await newTerm(page, "pi", FOLDERS[1]);
  await typeIn(page, "exit");
  await expect(page.getByTestId(`session-${done}`)).toHaveAttribute("data-term-status", "ok");
  return { claude, codex, shellGrok, shell, done };
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test.describe("shots", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const theme of ["dark", "light"] as const) {
    test(`shots: TERMINALS groups, sidebar and dock (${theme})`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      await page.setViewportSize({ width: 1280, height: 900 });
      await open(page, { theme });
      const ids = await seedTerminals(page);
      // pins: two bots and two terminals
      await page.getByTestId("bot-kami").click({ button: "right" });
      await page.getByTestId("row-dock").click();
      await page.getByTestId("bot-friren").click({ button: "right" });
      await page.getByTestId("row-dock").click();
      for (const id of [ids.claude, ids.shellGrok]) {
        await page.getByTestId(`session-${id}`).click({ button: "right" });
        await page.getByTestId("session-pin").click();
      }
      await page.getByTestId(`session-${ids.claude}`).locator(".ss-open").click();
      // output flowing on claude: the spinner shows
      await typeIn(page, "after 0 progress");
      await page.mouse.move(900, 600);
      await shot(page, `terminals-groups-${theme}`);
      await shot(page, `termsessions-sidebar-${theme}`);
      await shot(page, `sidebar-dock-${theme}`);
      if (theme === "dark") {
        await page.getByTestId("session-new").click();
        await expect(page.getByTestId("session-agent-shell")).toBeVisible();
        await shot(page, "termsessions-plus-menu");
        await page.keyboard.press("Escape");
      }
    });
  }
});

test("the + menu: Shell first, then CLIs with official marks; no chat choice; picking starts a terminal in the chip's folder", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-start").click();
  const menu = page.getByTestId("session-menu");
  await expect(menu).toBeVisible();
  const rows = menu.locator("[data-testid^=session-agent-]");
  await expect(rows.first()).toHaveAttribute("data-testid", "session-agent-shell");
  await expect(rows.first().getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  for (const a of ["claude", "codex", "grok", "opencode", "omh"]) await expect(menu.getByTestId(`session-agent-${a}`)).toBeVisible();
  // no letter glyphs: every CLI row draws a mark image or svg
  for (const a of ["claude", "codex", "grok"]) await expect(menu.getByTestId(`session-agent-${a}`).locator("svg, img").first()).toBeVisible();
  await expect(page.getByTestId("session-way")).toHaveCount(0);
  await expect(menu.getByTestId("session-folder")).toContainText("web-app");
  await menu.getByTestId("session-agent-claude").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveCount(0);
  const calls = await page.evaluate(() => (window as unknown as { __omherSessionCalls: { op: string; agent?: string; cwd?: string }[] }).__omherSessionCalls);
  expect(calls.filter((c) => c.op === "start")).toEqual([expect.objectContaining({ op: "start", agent: "claude", cwd: "/home/you/code/web-app" })]);
  expect(calls.some((c) => c.op === "chat.start")).toBe(false);
  // the Shell row runs the login shell through shell_start (a folder and a size, never a program)
  await newTerm(page, "shell", FOLDERS[1]);
  const shells = await page.evaluate(() => (window as unknown as { __omherShellCalls: { op: string; cwd?: string | null }[] }).__omherShellCalls);
  expect(shells.filter((c) => c.op === "start")).toEqual([expect.objectContaining({ cwd: FOLDERS[1] })]);
});

test("rows: grouped by folder with the branch; one line with status, mark, title and mono cli/age; mark follows fgAgent", async ({ page }) => {
  await open(page);
  const ids = await seedTerminals(page);
  const groups = page.getByTestId("term-group");
  await expect(groups).toHaveCount(2);
  await expect(groups.nth(0).getByTestId("term-group-head")).toContainText("omher");
  await expect(groups.nth(0).getByTestId("term-group-branch")).toHaveText("feat/terminal-sessions");
  await expect(groups.nth(1).getByTestId("term-group-branch")).toHaveText("feature/checkout-flow");
  const row = page.getByTestId(`session-${ids.claude}`);
  await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
  await expect(row.getByTestId("term-meta")).toHaveText(/^claude (now|\d+[smhd])$/);
  // one line: the row is about one text line tall
  const h = await row.boundingBox();
  expect(h!.height).toBeLessThan(34);
  // a Shell whose foreground CLI is grok shows Grok's mark; back to the shell icon when it leaves
  const sg = page.getByTestId(`session-${ids.shellGrok}`);
  await expect(sg.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "grok");
  await expect(sg.getByTestId("term-meta")).toContainText("grok");
  await setFg(page, ids.shellGrok, null);
  await expect(sg.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  await expect(sg.getByTestId("term-meta")).toContainText("shell");
  // exit 0 = check; exit 3 = x; output flowing = spinner, then idle
  await expect(page.getByTestId(`session-${ids.done}`).getByTestId("term-status")).toHaveAttribute("data-status", "ok");
  await page.getByTestId(`session-${ids.codex}`).locator(".ss-open").click();
  await typeIn(page, "hello");
  await expect(page.getByTestId(`session-${ids.codex}`)).toHaveAttribute("data-term-status", "busy");
  await expect(page.getByTestId(`session-${ids.codex}`)).toHaveAttribute("data-term-status", "idle", { timeout: 6000 });
  await typeIn(page, "after 10 exit 3");
  await expect(page.getByTestId(`session-${ids.codex}`)).toHaveAttribute("data-term-status", "err");
  // the selected row is a rounded block with a border, no accent bar
  const sel = await page.getByTestId(`session-${ids.codex}`).evaluate((el) => {
    const cs = getComputedStyle(el);
    return { r: parseFloat(cs.borderTopLeftRadius), b: cs.borderTopWidth };
  });
  expect(sel.r).toBeGreaterThanOrEqual(6);
  expect(sel.b).toBe("1px");
  // no chat badge or Chat|Terminal mark anywhere in TERMINALS
  await expect(page.getByTestId("side-sessions").getByTestId("session-view")).toHaveCount(0);
});

test("a saved chat-mode session is not listed; a saved terminal one is", async ({ page }) => {
  await page.addInitScript(() => {
    const snap = {
      v: 1,
      at: Date.now(),
      bot: "kami",
      view: "chat",
      session: null,
      panelOpen: false,
      panelTab: "details",
      runsFull: false,
      runId: null,
      drafts: {},
      sessions: [
        { id: "s1", agent: "claude", cwd: "/home/you/code/web-app", startedAt: 1, view: "chat", running: false, messages: [{ id: "m1", role: "user", text: "old chat", ts: 1 }] },
        { id: "s2", agent: "codex", cwd: "/home/you/code/omher", startedAt: 2, view: "terminal", open: "terminal", running: false, exitCode: 0 },
      ],
    };
    if (!sessionStorage.getItem("__seeded")) {
      localStorage.setItem("omher.resume", JSON.stringify(snap));
      sessionStorage.setItem("__seeded", "1");
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(page.getByTestId("session-s2")).toBeVisible();
  await expect(page.getByTestId("session-s1")).toHaveCount(0);
});

test("scroll: 12 bots x 6 threads and 15 terminals at 900px; each region scrolls on its own; the dock stays", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const { bots } = await mock("mock.manyBots", { n: 12 });
  for (const b of bots as string[]) await mock("mock.threads", { bot: b, threads: Array.from({ length: 6 }, (_, i) => ({ title: `${b} thread ${i + 1}`, ago: (i + 1) * 600 })) });
  await open(page, { roster: ["kami", ...(bots as string[])] });
  await expect(page.getByTestId("bot-bot12")).toBeAttached();
  for (let i = 0; i < 15; i++) await newTerm(page, i % 3 === 0 ? "shell" : i % 3 === 1 ? "claude" : "codex", FOLDERS[i % 2]);
  await expect(page.locator('[data-testid^="session-s"].tr')).toHaveCount(15);
  await page.mouse.move(900, 600);
  await shot(page, "termsessions-many-scroll");
  const botsSec = page.getByTestId("side-bots");
  const termSec = page.getByTestId("side-sessions");
  const botList = botsSec.locator(".bot-list");
  const termList = termSec.locator(".ss-list");
  // both headers visible inside the window, the dock below both regions
  const vh = 900;
  for (const h of [botsSec.locator(".side-sh"), termSec.locator(".side-sh")]) {
    const b = (await h.boundingBox())!;
    expect(b.y).toBeGreaterThanOrEqual(0);
    expect(b.y + b.height).toBeLessThanOrEqual(vh);
  }
  const dock = page.getByTestId("dock");
  await expect(dock).toBeVisible();
  const dockBox = (await dock.boundingBox())!;
  const termBox = (await termList.boundingBox())!;
  expect(termBox.y + termBox.height).toBeLessThanOrEqual(dockBox.y + 0.5);
  expect(dockBox.y + dockBox.height).toBeLessThanOrEqual(vh);
  // both lists overflow and scroll
  for (const l of [botList, termList]) expect(await l.evaluate((el) => el.scrollHeight > el.clientHeight + 4)).toBe(true);
  // "Show N more" is kept for threads
  await expect(page.getByTestId("thread-more").first()).toBeAttached();
  const divider = async () => (await termSec.boundingBox())!.y;
  const d0 = await divider();
  // wheel inside BOTS moves BOTS only
  const tTop0 = await termList.evaluate((el) => el.scrollTop);
  const bb = (await botList.boundingBox())!;
  await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2);
  await page.mouse.wheel(0, 600);
  await expect.poll(() => botList.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  expect(await termList.evaluate((el) => el.scrollTop)).toBe(tTop0);
  // wheel inside TERMINALS moves TERMINALS only
  const bTop = await botList.evaluate((el) => el.scrollTop);
  const tb = (await termList.boundingBox())!;
  await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2);
  await page.mouse.wheel(0, 400);
  await expect.poll(() => termList.evaluate((el) => el.scrollTop)).toBeGreaterThan(tTop0);
  expect(await botList.evaluate((el) => el.scrollTop)).toBe(bTop);
  expect(await divider()).toBe(d0);
  // the selected row scrolls into view: ⌘⇧] to the first terminal, then a bot far down the list
  await termList.evaluate((el) => (el.scrollTop = el.scrollHeight));
  const first = page.locator('[data-testid^="session-s"].tr').first();
  const mod = process.platform === "darwin" ? "Meta" : "Control";
  await page.locator("body").click({ position: { x: 900, y: 450 } });
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(first).toBeInViewport();
  await botList.evaluate((el) => (el.scrollTop = 0));
  await page.keyboard.press(`${mod}+Shift+BracketLeft`);
  const last = page.locator('[data-testid^="session-s"].tr').last();
  await expect(last).toBeInViewport();
  expect(await divider()).toBe(d0);
});

test("dock: pin, unpin and reorder persist across a reload; a tile opens and scrolls its row into view; dots", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, { keep: true });
  // with nothing pinned the dock shows the bots with the newest activity
  await expect(page.getByTestId("dock").locator(".dk-t").first()).toBeVisible();
  const id = await newTerm(page, "claude", FOLDERS[0]);
  await page.getByTestId("bot-friren").click({ button: "right" });
  await page.getByTestId("row-dock").click();
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await page.getByTestId("session-pin").click();
  await page.getByTestId("bot-kami").click({ button: "right" });
  await page.getByTestId("row-dock").click();
  const order = () => page.getByTestId("dock").locator(".dk-t").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(await order()).toEqual(["dock-tile-bot:friren", `dock-tile-term:${id}`, "dock-tile-bot:kami"]);
  // drag kami to the first place
  const from = (await page.getByTestId("dock-tile-bot:kami").boundingBox())!;
  const to = (await page.getByTestId("dock-tile-bot:friren").boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + 10, from.y + 10, { steps: 4 });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 6 });
  await page.mouse.up();
  expect(await order()).toEqual(["dock-tile-bot:kami", "dock-tile-bot:friren", `dock-tile-term:${id}`]);
  // unpin friren from its tile
  await page.getByTestId("dock-tile-bot:friren").click({ button: "right" });
  await page.getByTestId("dock-unpin").click();
  expect(await order()).toEqual(["dock-tile-bot:kami", `dock-tile-term:${id}`]);
  // reload: the same pins in the same order (the terminal comes back from the resume snapshot)
  await page.waitForTimeout(600);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(order).toEqual(["dock-tile-bot:kami", `dock-tile-term:${id}`]);
  const stored = await page.evaluate(() => localStorage.getItem("omher.dock"));
  expect(JSON.parse(stored!).pins).toEqual(["bot:kami", `term:${id}`]);
  // the terminal tile opens it and marks it active
  await page.getByTestId(`dock-tile-term:${id}`).click();
  await expect(page.getByTestId(`dock-tile-term:${id}`)).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId(`session-${id}`)).toBeInViewport();
  // a needs-you ask on kami: orange dot on its tile; a failed turn: red dot
  await mock("mock.manual", { bot: "kami" });
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }, { event: "approval.request", bot: "kami", request_id: "ap-1", title: "Run", command: "ls", choices: ["once", "deny"] }] });
  await expect(page.getByTestId("dock-tile-bot:kami")).toHaveAttribute("data-state", "needs");
  await expect(page.getByTestId("dock-tile-bot:kami").getByTestId("dock-dot")).toHaveAttribute("data-dot", "needs");
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", outcome: "error", error: "boom" }] });
  await expect(page.getByTestId("dock-tile-bot:kami")).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("dock-tile-bot:kami").getByTestId("dock-dot")).toHaveAttribute("data-dot", "failed");
  await mock("mock.manual", { bot: "kami", on: false });
  // keyboard: one tab stop, arrows move
  await page.getByTestId("dock-tile-bot:kami").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId(`dock-tile-term:${id}`)).toBeFocused();
  await expect(page.getByTestId("dock-tile-bot:kami")).toHaveAttribute("tabindex", "-1");
});

test("a short window keeps one row of tiles", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await mock("mock.manyBots", { n: 6 });
  await open(page, { roster: ["kami", "friren", "bot01", "bot02", "bot03", "bot04", "bot05", "bot06"] });
  const dock = page.getByTestId("dock");
  await expect(dock).toBeVisible();
  const h = (await dock.boundingBox())!.height;
  expect(h).toBeLessThan(44 * 2);
});

test("⌘N / ⌘T open the TERMINALS + menu", async ({ page }) => {
  await open(page);
  const mod = process.platform === "darwin" ? "Meta" : "Control";
  await page.locator("body").click({ position: { x: 900, y: 450 } });
  await page.keyboard.press(`${mod}+n`);
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(page.getByTestId("session-agent-shell")).toBeVisible();
});
