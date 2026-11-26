// Shift+Enter in a terminal running a coding agent makes a new line instead of sending the prompt, on the mock host.
// xterm sends Shift+Enter as \\r (Enter's byte) unless the program turned the Kitty keyboard protocol on, and on Windows
// ConPTY never lets Claude Code turn it on, so there Shift+Enter always sent. The page now sends ESC CR (what Claude
// Code's /terminal-setup binds, a new line in Claude Code, Codex, omh, Hermes) to an agent without the protocol,
// CSI 13;2 u to pi / oh-my-pi / Droid, leaves the protocol's own CSI 13;2 u alone, and keeps \\r for a shell.
// The same on every platform: run with OMHER_E2E_PLATFORM=Win32 too.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp, settle, typed } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

const focus = (page: Page) => page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();

type Call = { op: string; id?: number; data?: string };
/** What the shell host (a Shell row, the bottom panel) was given to type into pty `pty`. */
const shellTyped = (page: Page, pty: number) =>
  page.evaluate(
    (id) =>
      ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? [])
        .filter((c) => c.op === "write" && c.id === id)
        .map((c) => c.data ?? "")
        .join(""),
    pty,
  );

/** What one key press sends the program; `pty`: a Shell row's (its writes go through the shell host). */
async function sends(page: Page, key: string, pty?: number): Promise<string> {
  await focus(page);
  const read = () => (pty === undefined ? typed(page) : shellTyped(page, pty));
  const before = (await read()).length;
  await page.keyboard.press(key);
  await expect.poll(async () => (await read()).length).toBeGreaterThan(before);
  await settle(page, 150);
  return (await read()).slice(before);
}

type Sessions = { startTerminal(a: string, c: string): string; ptyOf(id: string): number | null };
const fg = (page: Page, pty: number, agent: string | null) =>
  page.evaluate(([id, a]) => (window as unknown as { __omherEmitSessionFg(p: { id: number; agent: string | null }): void }).__omherEmitSessionFg({ id: id as number, agent: a as string | null }), [pty, agent] as const);

/** A TERMINALS Shell row, shown, and its pty id. */
async function shellRow(page: Page): Promise<number> {
  const id = await page.evaluate(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", "/home/you/code/web-app"));
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).toContainText("(mock)");
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
}

test("a Claude Code row without the Kitty protocol gets ESC CR for Shift+Enter, and Enter stays \\r", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  expect(await sends(page, "Shift+Enter")).toBe("\x1b\r");
  expect(await sends(page, "Enter")).toBe("\r");
});

test("with the Kitty protocol on, Shift+Enter stays xterm's CSI 13;2 u; after the program pops it, ESC CR again", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\x1b[>1u");
  expect(await sends(page, "Shift+Enter")).toBe("\x1b[13;2u");
  await feed(page, "\x1b[<u");
  expect(await sends(page, "Shift+Enter")).toBe("\x1b\r");
});

test("a Shell row keeps \\r; once Claude Code runs in its foreground ESC CR, pi gets CSI 13;2 u, back at the shell \\r", async ({ page }) => {
  await openApp(page);
  const pty = await shellRow(page);
  expect(await sends(page, "Shift+Enter", pty)).toBe("\r");
  await fg(page, pty, "claude");
  expect(await sends(page, "Shift+Enter", pty)).toBe("\x1b\r");
  await fg(page, pty, "pi");
  expect(await sends(page, "Shift+Enter", pty)).toBe("\x1b[13;2u");
  await fg(page, pty, null);
  expect(await sends(page, "Shift+Enter", pty)).toBe("\r");
});

test("the bottom panel: a shell keeps \\r, the agent in its foreground gets ESC CR", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  const term = page.locator('[data-testid="termpanel-terminal"]:not([hidden])');
  await expect(term.locator(".xterm-rows")).toContainText("login shell in");
  const calls = () => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []) as Call[]);
  await expect.poll(async () => (await calls()).filter((c) => c.op === "start").length).toBe(1);
  const pty = (await calls()).find((c) => c.op === "start")!.id!;
  const press = async () => {
    await term.locator(".xterm-helper-textarea").focus();
    const before = (await shellTyped(page, pty)).length;
    await page.keyboard.press("Shift+Enter");
    await expect.poll(async () => (await shellTyped(page, pty)).length).toBeGreaterThan(before);
    await settle(page, 150);
    return (await shellTyped(page, pty)).slice(before);
  };
  expect(await press()).toBe("\r");
  await fg(page, pty, "codex");
  expect(await press()).toBe("\x1b\r");
});
