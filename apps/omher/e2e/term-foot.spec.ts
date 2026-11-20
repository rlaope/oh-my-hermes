// No dark bar at a terminal's foot. The rows rarely fill a terminal's box to the pixel, and xterm.css paints the
// viewport behind them black (`.xterm:not(.allow-transparency) .xterm-viewport`); omher's own rule that clears it must
// win that rule, or the few pixels under the last row show as a black strip (thick in the light theme). Checked in a
// TERMINALS session and in the bottom panel, dark and light: the viewport is see-through, so the strip is the theme's
// background.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp } from "./term-find-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string };

const viewportBg = (page: Page, sel: string) =>
  page.evaluate((s) => {
    const v = document.querySelector(`${s} .xterm-viewport`);
    return v ? getComputedStyle(v).backgroundColor : null;
  }, sel);

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of ["dark", "light"] as const) {
  test(`a terminal's foot has no black bar (${theme}): the viewport under the rows is see-through`, async ({ page }) => {
    await openApp(page, { theme });
    const id = await page.evaluate(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", "/home/you/code/web-app"));
    const sel = `[data-testid="terminal"][data-session="${id}"]`;
    await expect(page.locator(`${sel} .xterm-rows`)).toContainText("(mock)");
    await expect.poll(() => viewportBg(page, sel)).toBe("rgba(0, 0, 0, 0)");
    // the bottom panel's shells too
    await page.keyboard.press("Control+Backquote");
    const panelSel = '[data-testid="termpanel-terminal"]:not([hidden])';
    await expect(page.locator(`${panelSel} .xterm-rows`)).toContainText("login shell");
    await expect.poll(() => viewportBg(page, panelSel)).toBe("rgba(0, 0, 0, 0)");
  });
}
