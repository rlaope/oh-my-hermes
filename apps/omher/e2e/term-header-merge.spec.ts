// The main column's header of a TERMINALS session drags (Otty's): a session on its own, dragged by its header down onto
// its own terminal, merges with the next row of its folder (the row above when it is the last), the dragged one on the
// side the preview shows and the other, named in the preview, in the other half. Taken back onto the header, or
// Escape, nothing changes. A folder with no other row offers nothing. In a split the header is the focused pane's
// grip. The header's x closes the focused pane (the session stays listed), or the lone session as ⌘W does.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";
import { dragRowOnto, type Side } from "./split-drag-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string };
type Call = { op: string };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const textarea = (page: Page, id: string) => term(page, id).locator(".xterm-helper-textarea");
const pane = (page: Page, id: string) => page.locator(`[data-testid="split-pane"][data-session="${id}"]`);
const header = (page: Page) => page.getByTestId("header");
const headX = (page: Page) => page.getByTestId("session-head-close");
const shade = (page: Page) => page.getByTestId("split-drop");
const fill = (page: Page) => page.getByTestId("split-drop-fill");
const split = (page: Page) => page.getByTestId("session-split");
const focusedTerm = (page: Page) => page.evaluate(() => document.activeElement?.closest('[data-testid="terminal"]')?.getAttribute("data-session") ?? null);
const order = (page: Page) => page.locator('[data-testid="split-pane"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-session")));
/** the TERMINALS rows of folder `cwd`, as the sidebar lists them */
const rows = (page: Page, cwd: string) => page.locator(`[data-testid="term-group"][data-cwd="${cwd}"] .ss-row.tr`).evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.slice("session-".length)));
const openRow = (page: Page, id: string) => page.getByTestId(`session-${id}`).locator(".ss-open").click();
const calls = (page: Page) =>
  page.evaluate(() => [...((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []), ...((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? [])].filter((c) => c.op === "write" || c.op === "close"));
const windowCloses = (page: Page) => page.evaluate(() => (window as unknown as { __omherWindowCloses?: number }).__omherWindowCloses ?? 0);
const graceMs = (page: Page, ms: number) => page.evaluate((m) => void ((window as unknown as { __omherCloseGraceMs: number }).__omherCloseGraceMs = m), ms);

async function sessions(page: Page, folders: string[]): Promise<string[]> {
  const ids: string[] = [];
  for (const f of folders) {
    const id = await start(page, f);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  return ids;
}

/** A point of the header that is the header itself (not its title, path or buttons). */
async function headerPoint(page: Page) {
  const h = (await header(page).boundingBox())!;
  return { x: h.x + h.width * 0.62, y: h.y + h.height / 2 };
}

/** The point on `side` of the box of `host` (a terminal or a split pane). */
async function sidePoint(page: Page, host: Locator, side: Side) {
  const b = (await host.boundingBox())!;
  const [cx, cy] = [b.x + b.width / 2, b.y + b.height / 2];
  const p = { left: [b.x + b.width * 0.08, cy], right: [b.x + b.width * 0.92, cy], up: [cx, b.y + b.height * 0.08], down: [cx, b.y + b.height * 0.92] }[side];
  return { x: p[0], y: p[1] };
}

/** Press on the header and move onto `side` of `host` (the button not let go). */
async function pressHeaderOnto(page: Page, host: Locator, side: Side) {
  const from = await headerPoint(page);
  const to = await sidePoint(page, host, side);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 12 });
}

const OTHER: Record<Side, Side> = { left: "right", right: "left", up: "down", down: "up" };

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a lone session's header dragged onto its terminal merges it with the next row of its folder, on every side", async ({ page }) => {
  await openApp(page);
  // two sessions of /w/a and one of another folder (never a partner)
  const [x, , y] = await sessions(page, ["/w/a", "/w/b", "/w/a"]);
  const folder = await rows(page, "/w/a");
  expect(folder.sort()).toEqual([x, y].sort());
  // the open one is the newest; its partner is the row under it in /w/a (or above it, as the last)
  const d = y;
  const p = folder[folder.indexOf(d) + 1] ?? folder[folder.indexOf(d) - 1];
  for (const side of ["right", "left", "down", "up"] as Side[]) {
    await openRow(page, d);
    await expect(term(page, d)).toBeVisible();
    await expect(split(page)).toHaveCount(0);
    await expect(header(page)).toHaveAttribute("data-drag", "merge");
    await pressHeaderOnto(page, term(page, d), side);
    // the drop half is where the dragged session goes; the other half names the session that fills it
    await expect(shade(page)).toHaveAttribute("data-side", side);
    await expect(shade(page)).toHaveAttribute("data-session", p);
    await expect(fill(page)).toHaveAttribute("data-session", p);
    await expect(fill(page)).toHaveAttribute("data-side", OTHER[side]);
    const named = (await fill(page).textContent())!;
    expect(named.length).toBeGreaterThan(0);
    await page.mouse.up();
    await expect(shade(page)).toHaveCount(0);
    await expect(fill(page)).toHaveCount(0);
    await expect(split(page)).toHaveAttribute("data-panes", "2");
    // the dragged session keeps the keyboard, on the side the preview showed
    await expect(pane(page, d)).toHaveAttribute("data-focused", "true");
    const [bd, bp] = [(await pane(page, d).boundingBox())!, (await pane(page, p).boundingBox())!];
    if (side === "right") expect(bd.x).toBeGreaterThan(bp.x + bp.width - 2);
    if (side === "left") expect(bp.x).toBeGreaterThan(bd.x + bd.width - 2);
    if (side === "down") expect(bd.y).toBeGreaterThan(bp.y + bp.height - 2);
    if (side === "up") expect(bp.y).toBeGreaterThan(bd.y + bd.height - 2);
    // the preview named the session that is now beside it
    expect((await pane(page, p).getByTestId("split-tools").getAttribute("title"))!.startsWith(`${named} · `)).toBe(true);
    // the header's x closes the focused pane: the split ends, both sessions stay listed and running
    await expect(headX(page)).toHaveAttribute("aria-label", /Terminals/);
    await headX(page).click();
    await expect(split(page)).toHaveCount(0);
    await expect(page.getByTestId(`session-${d}`)).toHaveAttribute("data-status", "running");
    await expect(page.getByTestId(`session-${p}`)).toHaveAttribute("data-status", "running");
  }
  // nothing was typed into or stopped by any of it
  expect(await calls(page)).toEqual([]);
});

test("taken back onto the header, let go elsewhere, or Escape: nothing changes", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/a"]);
  const before = await rows(page, "/w/a");
  await textarea(page, b).focus();
  const check = async () => {
    await expect(shade(page)).toHaveCount(0);
    await expect(fill(page)).toHaveCount(0);
    await expect(split(page)).toHaveCount(0);
    expect(await rows(page, "/w/a")).toEqual(before);
    await expect(page.getByTestId(`session-${b}`)).toHaveClass(/active/);
    await expect(term(page, b)).toBeVisible();
    // the keyboard stays where it was
    await expect.poll(() => focusedTerm(page)).toBe(b);
  };
  // onto the terminal, then back up onto the header band: the preview goes, letting go there does nothing
  await pressHeaderOnto(page, term(page, b), "down");
  await expect(shade(page)).toHaveAttribute("data-session", a);
  const back = await headerPoint(page);
  await page.mouse.move(back.x - 40, back.y, { steps: 8 });
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await check();
  // Escape mid-drag: the preview goes and the drop does nothing
  await pressHeaderOnto(page, term(page, b), "right");
  await expect(shade(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await check();
  await page.mouse.up();
  await check();
  // let go over the sidebar: nothing
  await pressHeaderOnto(page, term(page, b), "left");
  const side = (await page.getByTestId("side-sessions").boundingBox())!;
  await page.mouse.move(side.x + side.width / 2, side.y + 20, { steps: 8 });
  await expect(shade(page)).toHaveCount(0);
  await page.mouse.up();
  await check();
  expect(await calls(page)).toEqual([]);
});

test("a folder with no other row: no grab cursor, no preview, nothing happens; with a partner the header shows grab", async ({ page }) => {
  await openApp(page);
  const [a, , c] = await sessions(page, ["/w/a", "/w/a", "/w/c"]);
  // c is alone in /w/c
  await expect(term(page, c)).toBeVisible();
  await expect(header(page)).not.toHaveAttribute("data-drag", /./);
  expect(await header(page).evaluate((el) => getComputedStyle(el).cursor)).not.toBe("grab");
  await pressHeaderOnto(page, term(page, c), "right");
  await page.waitForTimeout(100);
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(split(page)).toHaveCount(0);
  await expect(term(page, c)).toBeVisible();
  // a has a partner: grab, and the header keeps its height (no shift)
  const h0 = (await header(page).boundingBox())!.height;
  await openRow(page, a);
  await expect(header(page)).toHaveAttribute("data-drag", "merge");
  expect(await header(page).evaluate((el) => getComputedStyle(el).cursor)).toBe("grab");
  expect((await header(page).boundingBox())!.height).toBe(h0);
});

test("in a split the header drags the focused pane as its grip does; a click on the header changes nothing", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/a"]);
  // merge b (open) with a: b right of a
  await pressHeaderOnto(page, term(page, b), "right");
  await page.mouse.up();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  expect(await order(page)).toEqual([a, b]);
  await expect(header(page)).toHaveAttribute("data-drag", "move");
  // the header drags the focused pane (b) onto a's left half: b moves left of a, no partner named
  await pressHeaderOnto(page, pane(page, a), "left");
  await expect(shade(page)).toHaveAttribute("data-session", a);
  await expect(shade(page)).toHaveAttribute("data-side", "left");
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  expect(await order(page)).toEqual([b, a]);
  await expect(pane(page, b)).toHaveAttribute("data-focused", "true");
  // onto its own pane: no preview
  await pressHeaderOnto(page, pane(page, b), "down");
  await page.waitForTimeout(100);
  await expect(shade(page)).toHaveCount(0);
  await page.mouse.up();
  expect(await order(page)).toEqual([b, a]);
  // a plain click on the header (its title, its empty middle) does nothing to the split or the open session
  await page.getByTestId("session-title").click();
  const pt = await headerPoint(page);
  await page.mouse.click(pt.x, pt.y);
  expect(await order(page)).toEqual([b, a]);
  await expect(pane(page, b)).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("split-pane-menu")).toHaveCount(0);
  expect(await calls(page)).toEqual([]);
});

test("a click on a lone session's header does nothing", async ({ page }) => {
  await openApp(page);
  const [, b] = await sessions(page, ["/w/a", "/w/a"]);
  const before = await rows(page, "/w/a");
  await page.getByTestId("session-title").click();
  const pt = await headerPoint(page);
  await page.mouse.click(pt.x, pt.y);
  await expect(split(page)).toHaveCount(0);
  await expect(shade(page)).toHaveCount(0);
  expect(await rows(page, "/w/a")).toEqual(before);
  await expect(page.getByTestId(`session-${b}`)).toHaveClass(/active/);
});

test("the header's x on a lone terminal closes it as ⌘W does: undoable while it runs; pressing it never drags", async ({ page }) => {
  await openApp(page);
  await graceMs(page, 10_000);
  const [a, b] = await sessions(page, ["/w/a", "/w/a"]);
  // named for the session it closes, as the split's x is
  const title = (await page.getByTestId("session-title").textContent())!;
  await expect(headX(page)).toHaveAttribute("aria-label", `Close ${title}`);
  await expect(headX(page)).toHaveAttribute("title", `Close ${title}`);
  // a press on the x carried onto the terminal is no drag, and letting go there closes nothing
  const xb = (await headX(page).boundingBox())!;
  await page.mouse.move(xb.x + xb.width / 2, xb.y + xb.height / 2);
  await page.mouse.down();
  const to = await sidePoint(page, term(page, b), "down");
  await page.mouse.move(to.x, to.y, { steps: 10 });
  await page.waitForTimeout(100);
  await expect(shade(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(page.getByTestId(`session-${b}`)).toBeVisible();
  // reached by the keyboard like the header's other buttons: Enter closes b, with the undo toast; the window stays
  await headX(page).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(`close-toast-${b}`)).toBeVisible();
  await expect(page.getByTestId(`session-${b}`)).toHaveCount(0);
  expect(await windowCloses(page)).toBe(0);
  // its program was not stopped yet (the undo window); Undo brings it back
  expect((await calls(page)).filter((c) => c.op === "close")).toEqual([]);
  await page.getByTestId(`close-toast-${b}`).getByTestId("close-toast-undo").click();
  await expect(page.getByTestId(`session-${b}`)).toBeVisible();
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
});

test("with the undo window Off the header's x on a running terminal asks the row's Stop? and never closes the window", async ({ page }) => {
  await openApp(page, { term: { undoClose: 0 } });
  const [a, b] = await sessions(page, ["/w/a", "/w/a"]);
  // a sidebar search that hides b's row: the question shows on it all the same
  await page.getByTestId("bot-search").fill("zzz-no-match");
  await headX(page).click();
  const ask = page.getByTestId(`session-confirm-${b}`);
  await expect(ask).toBeVisible();
  // the row's own question: Cancel leaves it running
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  await page.getByTestId("bot-search").fill("");
  await expect(page.getByTestId(`session-${b}`)).toHaveAttribute("data-status", "running");
  expect(await calls(page)).toEqual([]);
  // asked again, Stop closes it at once (the program is stopped: no undo window)
  await headX(page).click();
  await page.getByTestId("session-stop").click();
  await expect(page.getByTestId(`session-${b}`)).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "close").length).toBe(1);
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  expect(await windowCloses(page)).toBe(0);
});

test("the main column switched under a drag (⌘⇧] / Ctrl+Shift+]): no preview, letting go merges nothing", async ({ page }) => {
  await openApp(page);
  const mod = (await platformIsMac(page)) ? "Meta" : "Control";
  const [a, b, c] = await sessions(page, ["/w/a", "/w/a", "/w/c"]);
  await openRow(page, b);
  await expect(header(page)).toHaveAttribute("data-drag", "merge");
  await pressHeaderOnto(page, term(page, b), "right");
  await expect(shade(page)).toHaveAttribute("data-session", a);
  // the next terminal opens while the button is held: the view under the pointer is no longer the dragged session's
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(page.getByTestId(`session-${b}`)).not.toHaveClass(/active/);
  const shownId = await page.locator('[data-testid="terminal"]').first().getAttribute("data-session");
  expect(shownId).not.toBe(b);
  const to = await sidePoint(page, page.locator('[data-testid="terminal"]').first(), "left");
  await page.mouse.move(to.x, to.y, { steps: 6 });
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(split(page)).toHaveCount(0);
  expect([a, c]).toContain(shownId);
  expect(await calls(page)).toEqual([]);
});

test("a paused session's idle view takes the merge; another session's idle view, switched to mid-drag, takes nothing", async ({ page }) => {
  await openApp(page);
  const mod = (await platformIsMac(page)) ? "Meta" : "Control";
  const [a, b] = await sessions(page, ["/w/a", "/w/a", "/w/c"]);
  // after a restart the shells come back paused: their idle views, no terminal
  await expect.poll(async () => (await page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null")))?.sessions?.length).toBe(3);
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await openRow(page, b);
  const idle = page.locator(`[data-testid="session-idle"][data-session="${b}"]`);
  await expect(idle).toBeVisible();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(header(page)).toHaveAttribute("data-drag", "merge");
  // the main column steps to another paused session while the button is held: its idle view is no target
  await pressHeaderOnto(page, idle, "right");
  await expect(shade(page)).toHaveAttribute("data-session", a);
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  const other = page.locator('[data-testid="session-idle"]');
  await expect(other).not.toHaveAttribute("data-session", b);
  const to = await sidePoint(page, other, "left");
  await page.mouse.move(to.x, to.y, { steps: 6 });
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(split(page)).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.splits"))).toBeNull();
  // back on b: a drop on its own idle view merges it with a
  await openRow(page, b);
  await expect(idle).toBeVisible();
  await pressHeaderOnto(page, idle, "down");
  await expect(shade(page)).toHaveAttribute("data-session", a);
  await expect(shade(page)).toHaveAttribute("data-side", "down");
  await page.mouse.up();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  const [bb, ba] = [(await pane(page, b).boundingBox())!, (await pane(page, a).boundingBox())!];
  expect(bb.y).toBeGreaterThan(ba.y + ba.height - 2);
  // both still wait for Resume: the merge started nothing
  await expect(page.getByTestId("session-resume")).toHaveCount(2);
  expect((await calls(page)).length).toBe(0);
  expect(await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []).filter((c) => c.op === "start").length)).toBe(0);
});

test("a zoomed split's header shows no grab and drags nothing", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/a"]);
  await pressHeaderOnto(page, term(page, b), "right");
  await page.mouse.up();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  await pane(page, b).hover();
  await pane(page, b).getByTestId("split-zoom").click();
  await expect(split(page)).toHaveAttribute("data-zoom", "true");
  await expect(header(page)).not.toHaveAttribute("data-drag", /./);
  expect(await header(page).evaluate((el) => getComputedStyle(el).cursor)).not.toBe("grab");
  await pressHeaderOnto(page, pane(page, b), "left");
  await page.waitForTimeout(100);
  await expect(shade(page)).toHaveCount(0);
  await page.mouse.up();
  // still zoomed on b (only its pane drawn), both still in the split, laid out as before
  await expect(split(page)).toHaveAttribute("data-zoom", "true");
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  expect(await order(page)).toEqual([b]);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.splits") || "null")?.groups?.[0]?.layout)).toEqual({ dir: "row", ratio: 0.5, a: { pane: Number(a.slice(1)) }, b: { pane: Number(b.slice(1)) } });
});

test("a release the page never hears (another app, outside the window) ends the drag: the next click merges nothing", async ({ page }) => {
  await openApp(page);
  const [, b] = await sessions(page, ["/w/a", "/w/a"]);
  await pressHeaderOnto(page, term(page, b), "right");
  await expect(shade(page)).toBeVisible();
  // a move with no button held (the button went up where the page could not hear it)
  await page.evaluate(() => window.dispatchEvent(new PointerEvent("pointermove", { clientX: 600, clientY: 400, buttons: 0, bubbles: true })));
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(split(page)).toHaveCount(0);
  // the window losing focus mid-drag ends it the same way
  await pressHeaderOnto(page, term(page, b), "down");
  await expect(shade(page)).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(shade(page)).toHaveCount(0);
  await page.mouse.up();
  const to = await sidePoint(page, term(page, b), "right");
  await page.mouse.click(to.x, to.y);
  await expect(split(page)).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveClass(/split-dragging/);
});

test("a partner that closes or changes under the drag: letting go merges nothing", async ({ page }) => {
  await openApp(page);
  const [a, m, b] = await sessions(page, ["/w/a", "/w/a", "/w/a"]);
  // b is open; its partner is the row under it, m
  expect(await rows(page, "/w/a")).toEqual([b, m, a]);
  await pressHeaderOnto(page, term(page, b), "right");
  await expect(fill(page)).toHaveAttribute("data-session", m);
  // m closes while the button is held (a test browser has no undo window: it goes at once); a is the partner now,
  // but the preview named m
  await page.evaluate((id) => (window as unknown as { __omherSessions: { close(id: string): void } }).__omherSessions.close(id), m);
  await expect(page.getByTestId(`session-${m}`)).toHaveCount(0);
  const to = await sidePoint(page, term(page, b), "left");
  await page.mouse.move(to.x, to.y, { steps: 4 });
  // the preview that named m goes at once
  await expect(shade(page)).toHaveCount(0);
  await expect(fill(page)).toHaveCount(0);
  await page.mouse.up();
  await expect(split(page)).toHaveCount(0);
  // a fresh drag names a and merges with it
  await pressHeaderOnto(page, term(page, b), "right");
  await expect(fill(page)).toHaveAttribute("data-session", a);
  await page.mouse.up();
  expect(await order(page)).toEqual([a, b]);
});

test("the partner passes over a row in another split and a chat of the same folder", async ({ page }) => {
  await openApp(page);
  type Api = { draft(agent: string): string; setDraft(id: string, p: { cwd: string }): void; start(id: string, first: string): Promise<boolean> };
  const [a, p, x] = await sessions(page, ["/w/a", "/w/a", "/w/x"]);
  // p goes into a split with x (another folder's session)
  await page.getByTestId(`session-${x}`).locator(".ss-open").click();
  await dragRowOnto(page, p, x, "right");
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  // a chat session in /w/a (not a TERMINALS row: it has no row there)
  const chat = await page.evaluate(async () => {
    const s = (window as unknown as { __omherSessions: Api }).__omherSessions;
    const id = s.draft("claude");
    s.setDraft(id, { cwd: "/w/a" });
    await s.start(id, "/status");
    return id;
  });
  type Rec = { id: string; status: string; cwd: string };
  const list = () => page.evaluate(() => (window as unknown as { __omherSessions: { getState(): { list: Rec[] } } }).__omherSessions.getState().list.map((r) => ({ id: r.id, status: r.status, cwd: r.cwd })));
  await expect.poll(async () => (await list()).find((r) => r.id === chat)?.status).toBe("running");
  await expect(page.getByTestId(`session-${chat}`)).toHaveCount(0);
  const [b] = await sessions(page, ["/w/a"]);
  // the /w/a group lists b and a (p shows in its split's card on top); in the session list p and the chat of /w/a
  // both sit between b and a, so the rule has to pass over each of them
  expect(await rows(page, "/w/a")).toEqual([b, a]);
  const ids = (await list()).filter((r) => r.cwd === "/w/a").map((r) => r.id);
  for (const skip of [p, chat]) {
    expect(ids.indexOf(skip)).toBeGreaterThan(ids.indexOf(b));
    expect(ids.indexOf(skip)).toBeLessThan(ids.indexOf(a));
  }
  await pressHeaderOnto(page, term(page, b), "down");
  await expect(fill(page)).toHaveAttribute("data-session", a);
  await page.mouse.up();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  await expect(pane(page, a)).toHaveCount(1);
  // p's own split with x is as it was (opened from its card)
  await page.locator(`[data-testid="split-cell"][data-session="${x}"] .sc-open`).click();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  expect(await order(page)).toEqual([x, p]);
});
