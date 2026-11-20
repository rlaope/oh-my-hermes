// A terminal's right-click menu: Copy (dim with nothing selected), Paste (through the paste guard), Select all, Find,
// Clear, Reset, Split right / down (a TERMINALS terminal splits with a new Shell as ⌘D does; a bottom-panel pane too).
// With Right-click pastes on, a right click pastes and Ctrl+right-click opens the menu.
import { expect, test, type Page } from "@playwright/test";
import { clipWrites, feed, mock, newTerminal, openApp, pointAt, settle, typed } from "./term-find-helpers";

const menu = (page: Page) => page.getByTestId("term-menu");
async function rightClick(page: Page, text: string, mods: ("Control")[] = []) {
  const p = await pointAt(page, text);
  for (const m of mods) await page.keyboard.down(m);
  await page.mouse.click(p.x, p.y, { button: "right" });
  for (const m of mods) await page.keyboard.up(m);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("right click opens the menu; Select all then Copy copies; Paste types the clipboard; Clear empties the screen; Esc closes it", async ({ page }) => {
  await openApp(page, { clipboard: "pasted-by-menu" });
  await newTerminal(page);
  await feed(page, "\r\nmenu-text-4410\r\n");
  await rightClick(page, "menu-text-4410");
  await expect(menu(page)).toBeVisible();
  await expect(page.getByTestId("term-menu-copy")).toBeDisabled();
  await expect(page.getByTestId("term-menu-splitRight")).toBeVisible();
  await page.getByTestId("term-menu-selectAll").click();
  await expect(menu(page)).toHaveCount(0);
  await rightClick(page, "menu-text-4410");
  await expect(page.getByTestId("term-menu-copy")).toBeEnabled();
  await page.getByTestId("term-menu-copy").click();
  await expect.poll(() => clipWrites(page)).toEqual([expect.stringContaining("menu-text-4410")]);
  const before = await typed(page);
  await rightClick(page, "menu-text-4410");
  await page.getByTestId("term-menu-paste").click();
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("pasted-by-menu");
  await rightClick(page, "menu-text-4410");
  await page.getByTestId("term-menu-clear").click();
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).not.toContainText("menu-text-4410");
  await page.locator('[data-testid="terminal"] .xterm-screen').click({ button: "right" });
  await expect(menu(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu(page)).toHaveCount(0);
  await expect(page.locator('[data-testid="terminal"] .xterm-helper-textarea')).toBeFocused();
});

test("Split right from the menu splits a TERMINALS terminal with a new Shell, as ⌘D", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\r\nsplit-from-menu\r\n");
  await rightClick(page, "split-from-menu");
  await page.getByTestId("term-menu-splitRight").click();
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
});

test("with Right-click pastes on, a right click pastes and Ctrl+right-click opens the menu", async ({ page }) => {
  await openApp(page, { term: { rightClickPaste: true }, clipboard: "rc-paste" });
  await newTerminal(page);
  await feed(page, "\r\nrc-target\r\n");
  const before = await typed(page);
  await rightClick(page, "rc-target");
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("rc-paste");
  await expect(menu(page)).toHaveCount(0);
  await rightClick(page, "rc-target", ["Control"]);
  await expect(menu(page)).toBeVisible();
  await settle(page);
});

test("in the bottom panel, Split down from a pane's menu adds a pane under it", async ({ page }) => {
  await openApp(page);
  await page.evaluate(async () => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd("/home/you/code/web-app");
  });
  await page.keyboard.press("Control+Backquote");
  const panes = page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]');
  await expect(panes.first().locator(".xterm-rows")).toContainText("login shell in");
  await panes.first().locator(".xterm-screen").click({ button: "right" });
  await expect(menu(page)).toBeVisible();
  await page.getByTestId("term-menu-splitDown").click();
  await expect(panes).toHaveCount(2);
});

test("a program reading the mouse (tmux mouse on) gets the right click and no menu opens; Shift+right-click opens it", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  // mouse reporting on (DECSET 1000), as tmux with `mouse on` or htop asks
  await feed(page, "\x1b[?1000h\x1b[?1006h\r\nmouse-app\r\n");
  const p = await pointAt(page, "mouse-app");
  const before = await typed(page);
  await page.mouse.click(p.x, p.y, { button: "right" });
  await settle(page);
  await expect(menu(page)).toHaveCount(0);
  // the press reached the program as a mouse report
  await expect.poll(async () => (await typed(page)).slice(before.length)).toMatch(/\x1b\[<2;/);
  await page.keyboard.down("Shift");
  await page.mouse.click(p.x, p.y, { button: "right" });
  await page.keyboard.up("Shift");
  await expect(menu(page)).toBeVisible();
});

test("the menu goes when another session comes to the front, so it never acts on a terminal out of sight", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\r\nfirst-term\r\n");
  await rightClick(page, "first-term");
  await expect(menu(page)).toBeVisible();
  await page.evaluate(async () => {
    const m = (await import("/src/state/store.ts" as string)) as { getStore(): { actions: { openSettings(): void } } };
    m.getStore().actions.openSettings();
  });
  await expect(menu(page)).toHaveCount(0);
});
