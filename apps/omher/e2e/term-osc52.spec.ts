// OSC 52: a program's copy (a tmux or Neovim yank, a copy over SSH) lands on the clipboard when it answers the
// person: the terminal has the keyboard and a key was pressed a moment before. A query is never answered; a copy from
// a terminal without the keyboard, or long after the last key, is refused with a note; Settings › Terminal › Programs
// may copy turns it off for terminals already open. The bottom panel's terminals do the same.
import { expect, test, type Page } from "@playwright/test";
import { clipWrites, feed, mock, newTerminal, openApp, settle, typed } from "./term-find-helpers";

/** The person presses a key in the open terminal (Shift alone: nothing reaches the program). */
const keyIn = async (page: Page, sel = '[data-testid="terminal"] .xterm-helper-textarea') => {
  await page.locator(sel).first().focus();
  await page.keyboard.press("Shift");
};

const osc52 = (text: string) => `\x1b]52;c;${Buffer.from(text, "utf8").toString("base64")}\x07`;
const setOsc52 = (page: Page, on: boolean) =>
  page.evaluate(async (v) => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ osc52: v });
  }, on);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a program's OSC 52 copy reaches the clipboard, a query gets no answer, and the setting turns it off", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await keyIn(page);
  await feed(page, osc52("yanked in tmux 한글"));
  await expect.poll(() => clipWrites(page)).toEqual(["yanked in tmux 한글"]);
  // a read of the clipboard is never answered: nothing goes to the program
  const before = await typed(page);
  await feed(page, "\x1b]52;c;?\x07");
  await settle(page);
  expect((await typed(page)).slice(before.length)).toBe("");
  expect(await clipWrites(page)).toHaveLength(1);
  // the setting, on an open terminal
  await setOsc52(page, false);
  await keyIn(page);
  await feed(page, osc52("not copied"));
  await settle(page);
  expect(await clipWrites(page)).toEqual(["yanked in tmux 한글"]);
  // nothing of the sequence is drawn
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).not.toContainText("not copied");
});

test("a copy with no key pressed, or from a terminal without the keyboard, is refused with a note on it", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  // nobody at the keys yet: a program's copy is refused
  await feed(page, osc52("from a background job"));
  const note = page.getByTestId("term-osc52-refused");
  await expect(note).toBeVisible();
  await expect(note).toContainText("A program tried to copy");
  expect(await clipWrites(page)).toEqual([]);
  await expect(note).toHaveCount(0, { timeout: 6000 });
  // a key pressed, then the keyboard moved out of the terminal: refused too
  await keyIn(page);
  await page.getByTestId("bot-search").focus();
  await feed(page, osc52("while elsewhere"));
  await expect(note).toBeVisible();
  expect(await clipWrites(page)).toEqual([]);
});

test("a copy the webview itself refuses says so too", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await page.evaluate(() => {
    navigator.clipboard.writeText = () => Promise.reject(new DOMException("not allowed", "NotAllowedError"));
  });
  await keyIn(page);
  await feed(page, osc52("webview says no"));
  await expect(page.getByTestId("term-osc52-refused")).toBeVisible();
});

test("a program in the bottom panel copies the same way", async ({ page }) => {
  await openApp(page);
  await page.evaluate(async () => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd("/home/you/code/web-app");
  });
  await page.keyboard.press("Control+Backquote");
  const pane = page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]').first();
  await expect(pane.locator(".xterm-rows")).toContainText("login shell in");
  const ta = '[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"] .xterm-helper-textarea';
  await keyIn(page, ta);
  // the panel shell's output: what it prints is fed to its terminal as a program's output
  await page.evaluate((d) => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; write(d: string): void }> };
    const host = document.querySelector('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"] .xterm');
    [...w.__omherTerms].find((t) => t.element === host)!.write(d);
  }, osc52("panel yank"));
  await expect.poll(() => clipWrites(page)).toEqual(["panel yank"]);
});

test("the Terminal page has Programs may copy under Clipboard, on by default; Off is kept", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-osc52-row")).toContainText("Programs may copy");
  const sw = page.getByTestId("term-osc52");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Off" }).click();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ osc52: false });
});
