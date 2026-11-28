// TERMINALS + menu › Continue a conversation (BOUNDARY rule 30): the conversations Claude Code and Codex keep, listed
// read-only from their own files (the mock host stands in for the shell's read, host.ts MOCK_PAST).
// 1. the + menu ends with one row per installed agent that keeps conversations; picking one lists that agent's
//    conversations in the menu's folder, each with the last thing said under its title and its folder and age;
// 2. a Codex fork reads "fork of <title>" beside its title;
// 3. This folder / All folders: All folders lists every folder's conversations (each row shows its own), the choice is
//    kept for the next time, and the filter narrows by title, last line or folder;
// 4. picking one opens a TERMINALS row in that folder whose CLI continues that conversation (`--resume <id>`); the
//    same conversation picked again opens that row, also one closed moments ago (its close is undone); a conversation
//    whose folder is gone starts nothing, says so and leaves the recent folders.
// This replaces the chat-mode coverage of sessions-manage.spec.ts (skipped since TERMINALS replaced chat sessions).
// Shots: OMHER_SHOTS=<dir> -> past-all-folders.png, past-codex-fork.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { closeFromSidebar } from "./split-drag-helpers";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}
const MARIGOLD = "bbbbbbbb-1111-4222-8333-444444444444"; // Claude Code in /home/you/code/omher
const LOGIN = "aaaaaaaa-1111-4222-8333-444444444444"; // Claude Code in /home/you/code/web-app
const THEME = "01a1d060-4ab7-72b2-b02b-1dbee1d5f52c"; // Codex in /home/you/code/web-app
const FORK = "01a1d060-4ab7-72b2-b02b-1dbee1d5f52d"; // a fork of it

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

async function open(page: Page, folder: string) {
  await page.addInitScript((f) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.past.scope"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = f;
    w.__omherMockAgents = ["claude", "codex", "omh"];
  }, folder);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** The + menu with its folder chip on `folder`. */
async function plusMenu(page: Page, folder: string) {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  const menu = page.getByTestId("session-menu");
  await expect(menu).toBeVisible();
  await menu.getByTestId("session-folder").click();
  const recent = menu.locator(`[data-testid=session-folder-pick][title="${folder}"]`);
  if (await recent.count()) await recent.click();
  else await menu.getByTestId("session-choose").click();
  await expect(menu.getByTestId("session-folder")).toHaveAttribute("title", folder);
  return menu;
}

const reads = (page: Page) => page.evaluate(() => (window as unknown as { __omherPastReads?: { op: string }[] }).__omherPastReads?.filter((r) => r.op === "list") ?? []);
const calls = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionCalls?: { op: string; agent?: string; cwd?: string; resume?: string }[] }).__omherSessionCalls ?? []);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Claude Code: this folder's conversations with the last thing said; All folders, kept; the filter; picking one continues it in a terminal", async ({ page }) => {
  await open(page, "/home/you/code/omher");
  const menu = await plusMenu(page, "/home/you/code/omher");
  // one row per agent that keeps conversations, at the end of the menu
  await expect(menu.getByTestId("session-past-claude")).toBeVisible();
  await expect(menu.getByTestId("session-past-codex")).toBeVisible();
  await menu.getByTestId("session-past-claude").click();
  const past = page.getByTestId("session-past-menu");
  await expect(past.getByTestId("session-past-scope-here")).toHaveAttribute("aria-checked", "true");
  // the filter takes the focus once the list is there: typing narrows it at once
  await expect(past.getByTestId("session-past-filter")).toBeFocused();
  const row = past.getByTestId(`session-past-row-${MARIGOLD}`);
  await expect(row).toContainText("Remember the word MARIGOLD for later");
  await expect(row.getByTestId("session-past-said")).toHaveText("You: Remember the word MARIGOLD for later");
  await expect(row).toContainText("~/code/omher · 3d");
  // only the chip's folder: the web-app conversation is not here
  await expect(past.getByTestId(`session-past-row-${LOGIN}`)).toHaveCount(0);
  expect(await reads(page)).toEqual([{ op: "list", agent: "claude", cwds: ["/home/you/code/omher"] }]);
  // the said line is one line inside the row, under the title
  const geo = await row.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const said = el.querySelector(".ss-past-said")!.getBoundingClientRect();
    const title = el.querySelector(".ss-l")!.getBoundingClientRect();
    return { inside: said.left >= r.left && said.right <= r.right + 0.5 && said.bottom <= r.bottom + 0.5, below: said.top >= title.bottom - 0.5, oneLine: said.height <= 16 };
  });
  expect(geo).toEqual({ inside: true, below: true, oneLine: true });

  // All folders: every folder's conversations, each row its own folder
  await past.getByTestId("session-past-scope-all").click();
  await expect(past.getByTestId(`session-past-row-${LOGIN}`)).toContainText("~/code/web-app");
  await expect(past.getByTestId(`session-past-row-${LOGIN}`).getByTestId("session-past-said")).toHaveText("Agent: The redirect now keeps the page you were on.");
  await expect(past.getByTestId(`session-past-row-${MARIGOLD}`)).toContainText("~/code/omher");
  expect((await reads(page)).at(-1)).toEqual({ op: "list", agent: "claude", cwds: ["/home/you/code/omher"], all: true });
  await shot(page, "past-all-folders");
  // the filter: by the last line, by the folder, and nothing
  const filter = past.getByTestId("session-past-filter");
  await filter.fill("redirect now");
  await expect(past.locator("[data-testid^=session-past-row-]")).toHaveCount(1);
  await expect(past.getByTestId(`session-past-row-${LOGIN}`)).toBeVisible();
  await filter.fill("code/omher");
  await expect(past.locator("[data-testid^=session-past-row-]")).toHaveCount(1);
  await expect(past.getByTestId(`session-past-row-${MARIGOLD}`)).toBeVisible();
  await filter.fill("nothing like this");
  await expect(past.getByTestId("session-past-nomatch")).toHaveText("No conversation matches");
  // ← in the filter edits it; ↓ moves out of it
  await filter.fill("marigold");
  await page.keyboard.press("ArrowLeft");
  await expect(past).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(past.getByTestId(`session-past-row-${MARIGOLD}`)).toBeFocused();
  // ← from a row goes back to the agents; the switch is kept
  await page.keyboard.press("ArrowLeft");
  await expect(menu).toBeVisible();
  await menu.getByTestId("session-past-claude").click();
  await expect(past.getByTestId("session-past-scope-all")).toHaveAttribute("aria-checked", "true");
  await expect(past.getByTestId(`session-past-row-${LOGIN}`)).toBeVisible();

  // picking one: a TERMINALS row in that folder whose Claude Code continues it
  await past.getByTestId(`session-past-row-${MARIGOLD}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "start")).toEqual([expect.objectContaining({ agent: "claude", cwd: "/home/you/code/omher", resume: MARIGOLD })]);
  expect((await calls(page)).some((c) => c.op === "chat.start")).toBe(false);
  // picking it again opens the same row
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-past-claude").click();
  await page.getByTestId(`session-past-row-${MARIGOLD}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  expect((await calls(page)).filter((c) => c.op === "start")).toHaveLength(1);
});

test("Codex: a fork reads as a fork of the conversation it came from; an empty folder says so", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await plusMenu(page, "/home/you/code/web-app");
  await page.getByTestId("session-past-codex").click();
  const past = page.getByTestId("session-past-menu");
  await expect(past.getByTestId(`session-past-row-${FORK}`).getByTestId("session-past-fork")).toHaveText("fork of Add a dark theme");
  await expect(past.getByTestId(`session-past-row-${THEME}`).getByTestId("session-past-fork")).toHaveCount(0);
  // no last line in the file's end: no said line (nothing guessed)
  await expect(past.getByTestId(`session-past-row-${THEME}`).getByTestId("session-past-said")).toHaveCount(0);
  // the fork mark and the title share one line inside the row
  const fits = await past.getByTestId(`session-past-row-${FORK}`).evaluate((el) => {
    const r = el.getBoundingClientRect();
    const f = el.querySelector(".ss-past-fork")!.getBoundingClientRect();
    const t = el.querySelector(".ss-l")!.getBoundingClientRect();
    return f.right <= r.right + 0.5 && Math.abs(f.bottom - t.bottom) < 4;
  });
  expect(fits).toBe(true);
  await shot(page, "past-codex-fork");
  await past.getByTestId("session-past-back").click();
  // a folder with none
  await page.evaluate(() => ((window as unknown as { __omherPastChats: unknown[] }).__omherPastChats = []));
  await page.getByTestId("session-past-codex").click();
  await expect(page.getByTestId("session-past-none")).toHaveText("No Codex conversations in this folder");
  await page.getByTestId("session-past-scope-all").click();
  await expect(page.getByTestId("session-past-none")).toHaveText("No Codex conversations");
});

test("a conversation whose folder is gone starts nothing: its row and the folder's header say so", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await page.evaluate(() => ((window as unknown as { __omherMockGoneFolders: string[] }).__omherMockGoneFolders = ["/home/you/code/web-app"]));
  await plusMenu(page, "/home/you/code/web-app");
  await page.getByTestId("session-past-codex").click();
  await page.getByTestId(`session-past-row-${THEME}`).click();
  await expect(page.getByTestId("terminal").locator(".xterm-rows")).toContainText("/home/you/code/web-app no longer exists: nothing was started");
  await expect(page.getByTestId("term-group-gone")).toHaveText("This folder no longer exists");
  // the refused start is the only one: no program runs, nothing is typed
  const starts = (await calls(page)).filter((c) => c.op === "start");
  expect(starts).toEqual([expect.objectContaining({ agent: "codex", cwd: "/home/you/code/web-app", resume: THEME })]);
  expect((await calls(page)).some((c) => c.op === "write")).toBe(false);
});

test("a conversation already running in a Shell row's Claude Code opens that row; no second Claude Code starts on it", async ({ page }) => {
  await open(page, "/home/you/code/omher");
  const menu = await plusMenu(page, "/home/you/code/omher");
  await menu.getByTestId("session-agent-shell").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  const rows = page.locator(".ss-open");
  const shellRow = await page.locator('[data-testid^="session-s"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")).find((x) => x && /^session-s\d+$/.test(x))!);
  const id = shellRow.slice("session-".length);
  const pty = await page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
  expect(pty).not.toBeNull();
  // the person runs `claude --resume` there themselves; the shell names the conversation its Claude Code runs
  await page.evaluate(([p, c]) => void (((window as unknown as { __omherMockFgOwn?: Record<number, string> }).__omherMockFgOwn ??= {})[p as number] = c as string), [pty, MARIGOLD] as const);
  await page.evaluate((p) => (window as unknown as { __omherEmitSessionFg(x: { id: number; agent: string }): void }).__omherEmitSessionFg({ id: p as number, agent: "claude" }), pty);
  const saved = () => page.evaluate((i) => JSON.parse(localStorage.getItem("omher.resume") || "null")?.sessions?.find((s: { id: string }) => s.id === i), id);
  await expect.poll(saved, { timeout: 15_000 }).toMatchObject({ fgCli: "claude", fgSession: MARIGOLD });
  // open another terminal so the Shell row is not the one shown
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-agent-codex").click();
  const count = await rows.count();
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-past-claude").click();
  await page.getByTestId(`session-past-row-${MARIGOLD}`).click();
  await expect(page.getByTestId(`session-${id}`).locator(".ss-open")).toHaveAttribute("aria-current", "true");
  expect(await rows.count()).toBe(count);
  expect((await calls(page)).filter((c) => c.op === "start" && c.agent === "claude")).toEqual([]);
});

test("a conversation whose row was closed moments ago (still in the undo window) undoes that close; no second Claude Code starts on it", async ({ page }) => {
  await open(page, "/home/you/code/omher");
  await page.evaluate(() => void ((window as unknown as { __omherCloseGraceMs: number }).__omherCloseGraceMs = 10_000));
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-past-claude").click();
  await page.getByTestId(`session-past-row-${MARIGOLD}`).click();
  type S = { getState(): { list: { id: string; agentSession?: string }[] }; ptyOf(id: string): number | null };
  const onIt = () => page.evaluate((c) => (window as unknown as { __omherSessions: S }).__omherSessions.getState().list.filter((r) => r.agentSession === c).map((r) => r.id), MARIGOLD);
  await expect.poll(async () => (await onIt()).length).toBe(1);
  const [id] = await onIt();
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: S }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  // closed: the row leaves, its Claude Code runs on hidden for the undo window
  await closeFromSidebar(page, id);
  await expect(page.getByTestId(`close-toast-${id}`)).toBeVisible();
  await expect(page.getByTestId(`session-${id}`)).toHaveCount(0);
  // picked again inside the window: the close is undone and that row opens
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-past-claude").click();
  await page.getByTestId(`session-past-row-${MARIGOLD}`).click();
  await expect(page.getByTestId(`close-toast-${id}`)).toHaveCount(0);
  await expect(page.getByTestId(`session-${id}`).locator(".ss-open")).toHaveAttribute("aria-current", "true");
  expect(await onIt()).toEqual([id]);
  expect((await calls(page)).filter((c) => c.op === "start" && c.agent === "claude")).toHaveLength(1);
});

test("a folder found gone leaves the recent folders: the next + does not start there", async ({ page }) => {
  await open(page, "/home/you/code/omher");
  // the omher folder is used first, then a conversation in web-app, which is gone
  await plusMenu(page, "/home/you/code/omher");
  await page.getByTestId("session-agent-shell").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await page.evaluate(() => {
    const w = window as unknown as { __omherMockGoneFolders: string[]; __omherPickFolder: string };
    w.__omherMockGoneFolders = ["/home/you/code/web-app"];
    w.__omherPickFolder = "/home/you/code/web-app";
  });
  await plusMenu(page, "/home/you/code/web-app");
  await page.getByTestId("session-past-codex").click();
  await page.getByTestId(`session-past-row-${THEME}`).click();
  await expect(page.getByTestId("term-group-gone")).toHaveText("This folder no longer exists");
  const recent = () => page.evaluate(() => (JSON.parse(localStorage.getItem("omher.sessions.recent") || "[]") as { cwd: string }[]).map((r) => r.cwd));
  await expect.poll(recent).toEqual(["/home/you/code/omher"]);
  // the + menu's folder chip is on the folder that is still there, and its list no longer offers the gone one
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  const menu = page.getByTestId("session-menu");
  await expect(menu.getByTestId("session-folder")).toHaveAttribute("title", "/home/you/code/omher");
  await menu.getByTestId("session-folder").click();
  await expect(menu.locator('[data-testid=session-folder-pick][title="/home/you/code/web-app"]')).toHaveCount(0);
});
