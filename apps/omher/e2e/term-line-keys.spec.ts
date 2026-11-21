// Line editing keys in a terminal on macOS, as Terminal.app, iTerm2, Ghostty and Orca send them: Cmd+Left / Cmd+Right
// go to the line's start / end (Ctrl+A / Ctrl+E), Cmd+Backspace deletes to its start (Ctrl+U), Option+Left /
// Option+Right move a word (ESC b / ESC f), and Cmd+K clears the screen and scrollback without moving the keyboard to
// the bot search. Off macOS none of these is taken: Ctrl+arrows reach the program as xterm encodes them.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

const PROJECT = "/home/you/code/web-app";
const pane = (page: Page) => page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]').first();
type Call = { op: string; data?: string };
const written = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "write").map((c) => c.data ?? "").join(""));

async function openPanel(page: Page) {
  await openApp(page);
  await page.evaluate(async (p) => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd(p);
  }, PROJECT);
  await page.keyboard.press("Control+Backquote");
  await expect(pane(page).locator(".xterm-rows")).toContainText(`login shell in ${PROJECT}`);
  await pane(page).locator(".xterm-helper-textarea").focus();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("line and word keys send what readline knows (macOS); off macOS Ctrl+arrows stay xterm's", async ({ page }) => {
  await openPanel(page);
  const mac = await platformIsMac(page);
  const before = await written(page);
  if (mac) {
    for (const k of ["Meta+ArrowLeft", "Meta+ArrowRight", "Meta+Backspace", "Alt+ArrowLeft", "Alt+ArrowRight"]) await page.keyboard.press(k);
    await expect.poll(async () => (await written(page)).slice(before.length)).toBe("\x01\x05\x15\x1bb\x1bf");
  } else {
    await page.keyboard.press("Control+ArrowLeft");
    await expect.poll(async () => (await written(page)).slice(before.length)).toBe("\x1b[1;5D");
  }
});

test("Cmd+K clears the terminal's screen and scrollback (macOS); the bot search does not take the keyboard and the shell gets nothing", async ({ page }) => {
  await openPanel(page);
  const mac = await platformIsMac(page);
  const ta = pane(page).locator(".xterm-helper-textarea");
  await page.keyboard.type("echo marker-before-clear");
  await page.keyboard.press("Enter");
  await expect(pane(page).locator(".xterm-rows")).toContainText("marker-before-clear");
  const before = await written(page);
  await page.keyboard.press(mac ? "Meta+k" : "Control+k");
  if (mac) {
    await expect(pane(page).locator(".xterm-rows")).not.toContainText("marker-before-clear");
    await expect(ta).toBeFocused();
    expect(await written(page)).toBe(before);
  } else {
    // Ctrl+K is the program's (kill to the end of the line)
    await expect.poll(async () => (await written(page)).slice(before.length)).toBe("\x0b");
  }
});

test("a program with the Kitty keyboard protocol on gets Option+arrows as xterm encodes them, not ESC b / ESC f (macOS)", async ({ page }) => {
  await openPanel(page);
  if (!(await platformIsMac(page))) return expect(await platformIsMac(page)).toBe(false);
  // the program asks for Kitty keys (CSI > 1 u), as a shell's line editor that reads them itself would
  await page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; write(d: string, cb?: () => void): void }> };
    const host = document.querySelector('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"] .xterm');
    return new Promise<void>((r) => [...w.__omherTerms].find((t) => t.element === host)!.write("\x1b[>1u", r));
  });
  const before = await written(page);
  await page.keyboard.press("Alt+ArrowLeft");
  await expect.poll(async () => (await written(page)).length).toBeGreaterThan(before.length);
  const sent = (await written(page)).slice(before.length);
  expect(sent).not.toBe("\x1bb");
  // Cmd keys stay line editing: no program reads Cmd
  const mid = await written(page);
  await page.keyboard.press("Meta+ArrowLeft");
  await expect.poll(async () => (await written(page)).slice(mid.length)).toBe("\x01");
});
