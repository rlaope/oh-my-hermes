// The bottom terminal panel gives the keyboard back when it hides: Ctrl+` from inside it, or its last tab closing,
// returns the focus to where the person was typing before (a TERMINALS session or the chat composer), never to the
// page body where keys go nowhere. A place clicked while the panel was open is left alone.
import { expect, test, type Page } from "@playwright/test";
import { mock, newTerminal, openApp, platformIsMac } from "./term-find-helpers";

const panel = (page: Page) => page.getByTestId("termpanel");
const inPanel = (page: Page) => page.evaluate(() => !!document.activeElement?.closest('[data-testid="termpanel-terminal"]'));
const where = (page: Page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return "body";
    if (a.closest('[data-testid="termpanel"]')) return "panel";
    const t = a.closest<HTMLElement>('[data-testid="terminal"]');
    if (t) return `session:${t.dataset.session}`;
    return a.getAttribute("data-testid") ?? a.tagName;
  });

async function toggle(page: Page, open: boolean) {
  await page.keyboard.press("Control+Backquote");
  if (open) {
    await expect(panel(page)).toBeVisible();
    await expect.poll(() => inPanel(page)).toBe(true);
  } else await expect(panel(page)).toBeHidden();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Ctrl+` twice from a TERMINALS session: the keyboard is back in that session, and typing reaches it", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await toggle(page, true);
  await toggle(page, false);
  await expect.poll(() => where(page)).toBe(`session:${id}`);
});

test("Ctrl+` twice from the chat composer: the keyboard is back in the composer", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("composer").focus();
  await toggle(page, true);
  await toggle(page, false);
  await expect.poll(() => where(page)).toBe("composer");
  await page.keyboard.type("still here");
  await expect(page.getByTestId("composer")).toHaveValue(/still here/);
});

test("the panel's last tab closing gives the keyboard back too", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await toggle(page, true);
  await page.getByTestId("termpanel-tab-close").click();
  await expect(panel(page)).toBeHidden();
  await expect.poll(() => where(page)).toBe(`session:${id}`);
});

test("a place clicked while the panel was open keeps the keyboard when it hides", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await toggle(page, true);
  // the person moves to the bot chat and types there, then hides the panel from the menu key
  await page.getByTestId("bot-kami").click();
  await page.getByTestId("composer").focus();
  await page.evaluate(async () => {
    const m = (await import("/src/terminal/state.ts" as string)) as { toggleTerminal(): void };
    m.toggleTerminal();
  });
  await expect(panel(page)).toBeHidden();
  await expect.poll(() => where(page)).toBe("composer");
});

test("in a split, the first open of the panel remembers the pane that had the keyboard (the right one, not the first)", async ({ page }) => {
  await openApp(page);
  const left = await newTerminal(page);
  await page.locator(`[data-testid="terminal"][data-session="${left}"] .xterm-helper-textarea`).focus();
  await page.keyboard.press((await platformIsMac(page)) ? "Meta+d" : "Control+Shift+D");
  await expect(page.getByTestId("split-pane")).toHaveCount(2);
  const right = (await page.locator('[data-testid="split-pane"][data-focused="true"]').getAttribute("data-session"))!;
  expect(right).not.toBe(left);
  await expect.poll(() => where(page)).toBe(`session:${right}`);
  await toggle(page, true);
  await toggle(page, false);
  await expect.poll(() => where(page)).toBe(`session:${right}`);
});
