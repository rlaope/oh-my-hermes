// Split zoom follows focus (kasaterm "칸 머리 조작": the zoom moves with the keyboard; typing never goes to a hidden
// pane). Zoomed (⌘⇧↩), every way the keyboard moves to another pane of the split shows that pane, still zoomed: ⌘] /
// ⌘[ (Ctrl+Tab / Ctrl+Shift+Tab off macOS), ⌘⌥arrows, a click on that session's sidebar row, a click on its system
// notification. Splitting, closing or moving a pane while zoomed shows every pane again (tmux).
// Off macOS: OMHER_E2E_PLATFORM=Win32.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
type Call = { op: string; id?: number; data?: string };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const ptyOf = async (page: Page, id: string) => {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
};
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const textarea = (page: Page, id: string) => term(page, id).locator(".xterm-helper-textarea");
const split = (page: Page) => page.getByTestId("session-split");
const focusedTerm = (page: Page) => page.evaluate(() => document.activeElement?.closest('[data-testid="terminal"]')?.getAttribute("data-session") ?? null);
/** the session ids of the panes drawn now */
const shown = (page: Page) => page.locator('[data-testid="split-pane"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-session")));
const writesTo = (page: Page, pty: number) =>
  page.evaluate(
    (p) => [...((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []), ...((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? [])].filter((c) => c.op === "write" && c.id === p).map((c) => c.data ?? "").join(""),
    pty,
  );

async function keys(page: Page) {
  const mac = await platformIsMac(page);
  return {
    right: mac ? "Meta+d" : "Control+Shift+D",
    down: mac ? "Meta+Shift+D" : "Alt+Shift+D",
    close: mac ? "Meta+w" : "Control+Shift+W",
    focus: (d: "Left" | "Right" | "Up" | "Down") => (mac ? `Meta+Alt+Arrow${d}` : `Control+Alt+Arrow${d}`),
    move: (d: "Left" | "Right" | "Up" | "Down") => (mac ? `Meta+Alt+Shift+Arrow${d}` : `Control+Alt+Shift+Arrow${d}`),
    next: mac ? "Meta+BracketRight" : "Control+Tab",
    prev: mac ? "Meta+BracketLeft" : "Control+Shift+Tab",
    zoom: mac ? "Meta+Shift+Enter" : "Control+Shift+Enter",
  };
}

async function sessions(page: Page, folders: string[]): Promise<string[]> {
  const ids: string[] = [];
  for (const f of folders) {
    const id = await start(page, f);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  return ids;
}

async function splitWith(page: Page, from: string, key: string, pick: string) {
  await textarea(page, from).focus();
  await page.keyboard.press(key);
  await expect(page.getByTestId("split-picker")).toBeVisible();
  await page.locator(`[data-testid="split-pick"][data-session="${pick}"]`).click();
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
}

/** a | (b over c), c focused; returns the ids and the keys */
async function threePanes(page: Page, extra: string[] = []) {
  const k = await keys(page);
  const ids = await sessions(page, ["/w/a", "/w/b", "/w/c", ...extra]);
  const [a, b, c] = ids;
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  await splitWith(page, b, k.down, c);
  await expect(split(page)).toHaveAttribute("data-panes", "3");
  await expect.poll(() => focusedTerm(page)).toBe(c);
  return { k, ids };
}

/** zoomed on `id`, the keyboard in its terminal */
async function expectZoomedOn(page: Page, id: string) {
  await expect(split(page)).toHaveAttribute("data-zoom", "true");
  await expect.poll(() => shown(page)).toEqual([id]);
  await expect(page.getByTestId("terminal")).toHaveCount(1);
  await expect.poll(() => focusedTerm(page)).toBe(id);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("zoomed: ⌘] / ⌘[ and ⌘⌥arrows move the zoom to the new pane, and typing goes to that pane's program", async ({ page }) => {
  await openApp(page);
  const { k, ids } = await threePanes(page);
  const [a, b, c] = ids;
  await page.keyboard.press(k.zoom);
  await expectZoomedOn(page, c);
  // ⌘] (next, wrapping): a, zoomed
  await page.keyboard.press(k.next);
  await expectZoomedOn(page, a);
  await expect(page.getByTestId(`session-${a}`)).toHaveClass(/active/);
  // typing goes to a's program, nothing to the hidden panes
  const [pa, pb, pc] = [await ptyOf(page, a), await ptyOf(page, b), await ptyOf(page, c)];
  await page.keyboard.type("echo za");
  await expect.poll(() => writesTo(page, pa)).toContain("echo za");
  expect(await writesTo(page, pb)).toBe("");
  expect(await writesTo(page, pc)).toBe("");
  // ⌘[ back to c
  await page.keyboard.press(k.prev);
  await expectZoomedOn(page, c);
  await page.keyboard.type("zc");
  await expect.poll(() => writesTo(page, pc)).toContain("zc");
  // ⌘⌥↑ from c: b, zoomed (the arrows go by the layout, not by what is drawn)
  await page.keyboard.press(k.focus("Up"));
  await expectZoomedOn(page, b);
  await page.keyboard.type("zb");
  await expect.poll(() => writesTo(page, pb)).toContain("zb");
  // ⌘⌥← from b: a
  await page.keyboard.press(k.focus("Left"));
  await expectZoomedOn(page, a);
  // the zoom key again: every pane
  await page.keyboard.press(k.zoom);
  await expect(split(page)).toHaveAttribute("data-zoom", "false");
  await expect(page.getByTestId("terminal")).toHaveCount(3);
  await expect.poll(() => focusedTerm(page)).toBe(a);
  // none of the pane keys reached a program
  for (const p of [pa, pb, pc]) expect(await writesTo(page, p)).not.toMatch(/\x1b\[|\t/);
});

test("zoomed: a click on another pane's sidebar row, or on its notification, shows that pane zoomed with the keyboard", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __notes: { title: string; n: { onclick: null | (() => void) } }[]; Notification: unknown };
    w.__notes = [];
    w.Notification = class {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string) {
        w.__notes.push({ title, n: this });
      }
      close() {}
    };
  });
  await openApp(page);
  const { k, ids } = await threePanes(page);
  const [a, b, c] = ids;
  await page.keyboard.press(k.zoom);
  await expectZoomedOn(page, c);
  // the sidebar row of a (a pane of this split)
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expectZoomedOn(page, a);
  await page.keyboard.type("row-a");
  await expect.poll(async () => writesTo(page, await ptyOf(page, a))).toContain("row-a");
  // c, a plain shell hidden behind the zoom, rings (tab completion, a stray \a): the row is marked, no notification
  await out(page, await ptyOf(page, c), "\x07");
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (window as unknown as { __notes: unknown[] }).__notes.length)).toBe(0);
  // b, hidden behind the zoom, runs Claude Code and rings: its notification's click shows b, zoomed, with the keyboard
  await page.evaluate((i) => (window as unknown as { __omherSessions: { setSessionFg(id: string, a: string | null): void } }).__omherSessions.setSessionFg(i, "claude"), b);
  await out(page, await ptyOf(page, b), "\x07");
  await expect.poll(() => page.evaluate(() => (window as unknown as { __notes: unknown[] }).__notes.length)).toBeGreaterThan(0);
  await page.evaluate(() => (window as unknown as { __notes: { n: { onclick: null | (() => void) } }[] }).__notes.at(-1)!.n.onclick?.());
  await expectZoomedOn(page, b);
  await page.keyboard.type("note-b");
  await expect.poll(async () => writesTo(page, await ptyOf(page, b))).toContain("note-b");
  expect(await writesTo(page, await ptyOf(page, c))).toBe("");
});

test("zoomed: splitting, closing the zoomed pane or moving it shows every pane again (tmux)", async ({ page }) => {
  await openApp(page);
  const { k, ids } = await threePanes(page, ["/w/d"]);
  const [a, b, c, d] = ids;
  // split while zoomed: unzoomed, four panes, the new one has the keyboard
  await page.keyboard.press(k.zoom);
  await expectZoomedOn(page, c);
  await splitWith(page, c, k.right, d);
  await expect(split(page)).toHaveAttribute("data-zoom", "false");
  await expect(split(page)).toHaveAttribute("data-panes", "4");
  await expect(page.getByTestId("terminal")).toHaveCount(4);
  await expect.poll(() => focusedTerm(page)).toBe(d);
  // close the zoomed pane: unzoomed, the nearest pane has the keyboard and takes what is typed
  await page.keyboard.press(k.zoom);
  await expectZoomedOn(page, d);
  await page.keyboard.press(k.close);
  await expect(split(page)).toHaveAttribute("data-panes", "3");
  await expect(split(page)).toHaveAttribute("data-zoom", "false");
  await expect(page.getByTestId("terminal")).toHaveCount(3);
  const heir = await focusedTerm(page);
  expect([a, b, c]).toContain(heir);
  await page.keyboard.type("heir");
  await expect.poll(async () => writesTo(page, await ptyOf(page, heir!))).toContain("heir");
  // move the zoomed pane: unzoomed, it keeps the keyboard
  await term(page, a).click();
  await expect(page.getByTestId(`session-${a}`)).toHaveClass(/active/);
  await expect.poll(() => focusedTerm(page)).toBe(a);
  await page.keyboard.press(k.zoom);
  await expectZoomedOn(page, a);
  await page.keyboard.press(k.move("Right"));
  await expect(split(page)).toHaveAttribute("data-zoom", "false");
  await expect(page.getByTestId("terminal")).toHaveCount(3);
  await expect.poll(() => focusedTerm(page)).toBe(a);
  // the closed pane's session is still listed
  await expect(page.getByTestId(`session-${d}`)).toHaveCount(1);
  void b;
});
