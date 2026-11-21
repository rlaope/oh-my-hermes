// When the TERMINALS session in view goes away from a split (its program ends, or its row is closed), the pane that
// takes its place in the split gets the view, the sidebar highlight and the keyboard, never the row next to it in
// the sidebar list. The world has decoy sessions outside the split, older and newer, so a list neighbour would be
// a different session than the split's heir.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

type Call = { op: string; id?: number; data?: string };
type W = { __omherSessions: { startTerminal(a: string, c: string): string; ptyOf(id: string): number | null; getState(): { list: { id: string }[] } }; __omherCloseGraceMs?: number; __omherSessionCalls?: Call[]; __omherShellCalls?: Call[] };

test.beforeEach(async () => {
  await mock("mock.reset");
});

const start = (page: Page, agent: string, cwd: string) => page.evaluate(([a, c]) => (window as unknown as W).__omherSessions.startTerminal(a, c), [agent, cwd] as const);
const list = (page: Page) => page.evaluate(() => (window as unknown as W).__omherSessions.getState().list.map((r) => r.id));
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const row = (page: Page, id: string) => page.getByTestId(`session-${id}`);
const split = (page: Page) => page.getByTestId("session-split");
const focusedTerm = (page: Page) => page.evaluate(() => document.activeElement?.closest('[data-testid="terminal"]')?.getAttribute("data-session") ?? null);
const uiSession = (page: Page) =>
  page.evaluate(async () => {
    const m = (await import("/src/state/store.ts" as string)) as { getStore(): { getState(): { ui: { session: string | null } } } };
    return m.getStore().getState().ui.session;
  });
async function ptyOf(page: Page, id: string): Promise<number> {
  await expect.poll(() => page.evaluate((i) => (window as unknown as W).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as W).__omherSessions.ptyOf(i), id)) as number;
}
const writesTo = async (page: Page, pty: number) =>
  (await page.evaluate(() => [...((window as unknown as W).__omherSessionCalls ?? []), ...((window as unknown as W).__omherShellCalls ?? [])]))
    .filter((c) => c.op === "write" && c.id === pty)
    .map((c) => c.data ?? "")
    .join("");
/** the shell in pty `p` is told `exit`, as typing it would */
const shellExit = (page: Page, p: number) =>
  page.evaluate(async (pp) => {
    const m = (await import("/src/terminal/host.ts" as string)) as { getShellHost(): { write(p: number, d: string): Promise<void> } };
    await m.getShellHost().write(pp, "exit\r");
  }, p);

async function keys(page: Page) {
  const mac = await platformIsMac(page);
  return {
    right: mac ? "Meta+d" : "Control+Shift+D",
    down: mac ? "Meta+Shift+D" : "Alt+Shift+D",
    focus: (d: "Left" | "Up") => (mac ? `Meta+Alt+Arrow${d}` : `Control+Alt+Arrow${d}`),
    zoom: mac ? "Meta+Shift+Enter" : "Control+Shift+Enter",
  };
}

async function make(page: Page, agent: "shell" | "claude", cwd: string): Promise<string> {
  const id = await start(page, agent, cwd);
  await expect(term(page, id).locator(".xterm-rows")).toContainText(agent === "shell" ? "login shell in" : "(mock)");
  return id;
}

/** decoys d0 (oldest) and d1 (newest) around `p`, the session in view with the keyboard */
async function world(page: Page, o: { grace?: number; agent?: "shell" | "claude" } = {}) {
  await openApp(page);
  await page.evaluate((ms) => void ((window as unknown as W).__omherCloseGraceMs = ms), o.grace ?? 0);
  const d0 = await make(page, "shell", "/w/d0");
  const p = await make(page, o.agent ?? "shell", "/w/p");
  const d1 = await make(page, "shell", "/w/d1");
  await row(page, p).locator(".ss-open").click();
  await expect.poll(() => uiSession(page)).toBe(p);
  await term(page, p).locator(".xterm-helper-textarea").focus();
  return { d0, p, d1 };
}

/** split the pane `from` with `key`; returns the new pane's session, which has the keyboard */
async function splitBy(page: Page, from: string, key: string): Promise<string> {
  await term(page, from).locator(".xterm-helper-textarea").focus();
  const before = await list(page);
  await page.keyboard.press(key);
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  const n = (await list(page)).find((i) => !before.includes(i))!;
  await expect.poll(() => focusedTerm(page)).toBe(n);
  return n;
}

async function ends(page: Page, id: string) {
  await shellExit(page, await ptyOf(page, id));
  await expect.poll(async () => (await list(page)).includes(id)).toBe(false);
}

/** `id` has the view, the sidebar highlight and the keyboard, and typed keys reach its program */
async function expectHas(page: Page, id: string) {
  await expect.poll(() => uiSession(page)).toBe(id);
  await expect.poll(() => focusedTerm(page)).toBe(id);
  await expect(row(page, id)).toHaveClass(/\bactive\b/);
  const p = await ptyOf(page, id);
  const mark = `Z${Date.now() % 1_000_000}`;
  await page.keyboard.type(mark);
  await expect.poll(() => writesTo(page, p)).toContain(mark);
}

test("Claude Code on the left, ⌘D, `exit` in the right Shell: Claude Code fills the view and has the keyboard", async ({ page }) => {
  const { p } = await world(page, { agent: "claude" });
  const n = await splitBy(page, p, (await keys(page)).right);
  await ends(page, n);
  await expectHas(page, p);
});

test("the left pane in view ends: the right pane takes over, not the oldest row", async ({ page }) => {
  const k = await keys(page);
  const { p } = await world(page);
  const n = await splitBy(page, p, k.right);
  await page.keyboard.press(k.focus("Left"));
  await expect.poll(() => focusedTerm(page)).toBe(p);
  await ends(page, p);
  await expectHas(page, n);
});

test("top and bottom: the bottom pane in view ends and the top one takes over", async ({ page }) => {
  const { p } = await world(page);
  const n = await splitBy(page, p, (await keys(page)).down);
  await ends(page, n);
  await expectHas(page, p);
});

test("a zoomed pane that ends hands the view to the other pane", async ({ page }) => {
  const k = await keys(page);
  const { p } = await world(page);
  const n = await splitBy(page, p, k.right);
  await page.keyboard.press(k.zoom);
  await expect(split(page)).toHaveAttribute("data-zoom", "true");
  await ends(page, n);
  await expectHas(page, p);
});

test("closing the pane in view from its row (no undo window) hands the view to the other pane", async ({ page }) => {
  const { p } = await world(page);
  const n = await splitBy(page, p, (await keys(page)).right);
  await row(page, n).hover();
  await row(page, n).getByTestId("session-close").click();
  await page.getByTestId("session-stop").click();
  await expect.poll(async () => (await list(page)).includes(n)).toBe(false);
  await expectHas(page, p);
});

test("with the undo window on, closing the pane in view hands the view to the other pane, and Undo puts it back", async ({ page }) => {
  const { p } = await world(page, { grace: 10_000 });
  const n = await splitBy(page, p, (await keys(page)).right);
  await row(page, n).hover();
  await row(page, n).getByTestId("session-close").click();
  await expect.poll(async () => (await list(page)).includes(n)).toBe(false);
  await expectHas(page, p);
  await page.getByTestId(`close-toast-${n}`).getByTestId("close-toast-undo").click();
  await expect(split(page)).toHaveAttribute("data-panes", "2");
  await expect.poll(() => uiSession(page)).toBe(n);
});

test("not split: the session in view ends and the row below it in the sidebar opens, in its own folder", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => void ((window as unknown as W).__omherCloseGraceMs = 0));
  // the list is newest first (c, b, a); the sidebar groups folders: /w/web holds c then a, /w/api holds b
  const a = await make(page, "shell", "/w/web");
  const b = await make(page, "shell", "/w/api");
  const c = await make(page, "shell", "/w/web");
  await row(page, c).locator(".ss-open").click();
  await expect.poll(() => uiSession(page)).toBe(c);
  await term(page, c).locator(".xterm-helper-textarea").focus();
  await ends(page, c);
  await expectHas(page, a);
  expect(await list(page)).toContain(b);
});
