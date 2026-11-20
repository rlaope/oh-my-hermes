// Copy / paste keys off macOS (Ctrl+Shift+C or Ctrl+Insert copies the selection and never sends Ctrl+C; Ctrl+Shift+V
// or Shift+Insert is the page's paste, never a ^V or an Insert escape to the program) and the scrollback keys (Cmd+Home
// / Cmd+End on macOS, Ctrl+Home / Ctrl+End elsewhere). Run once with OMHER_E2E_PLATFORM=Win32 for the Ctrl paths.
import { expect, test, type Page } from "@playwright/test";
import { clipWrites, feed, mock, newTerminal, openApp, platformIsMac, settle, typed } from "./term-find-helpers";

const viewport = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; buffer: { active: { viewportY: number; baseY: number } } }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...w.__omherTerms].find((x) => x.element === host)!;
    return { y: t.buffer.active.viewportY, base: t.buffer.active.baseY };
  });
const selectAll = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; selectAll(): void }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    [...w.__omherTerms].find((x) => x.element === host)!.selectAll();
  });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("copy and paste keys: off macOS they are the page's and the program gets none of them; macOS leaves them to xterm (Cmd+C is the menu's)", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\r\ncopy-me-7731\r\n");
  const ta = page.locator('[data-testid="terminal"] .xterm-helper-textarea');
  await ta.focus();
  await selectAll(page);
  const before = await typed(page);
  if (await platformIsMac(page)) {
    await page.keyboard.press("Control+Shift+C");
    await settle(page);
    expect(await clipWrites(page)).toEqual([]);
    return;
  }
  await page.keyboard.press("Control+Shift+C");
  await expect.poll(() => clipWrites(page)).toEqual([expect.stringContaining("copy-me-7731")]);
  await page.keyboard.press("Control+Insert");
  await expect.poll(async () => (await clipWrites(page)).length).toBe(2);
  await page.keyboard.press("Control+Shift+V");
  await page.keyboard.press("Shift+Insert");
  await settle(page);
  // no ^C, ^V or Insert escape reached the program
  expect((await typed(page)).slice(before.length)).not.toMatch(/\x03|\x16|\x1b\[2;2~/);
});

test("Cmd+Home / Ctrl+Home goes to the top of the scrollback, Cmd+End / Ctrl+End back to the bottom; the program gets nothing", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, Array.from({ length: 200 }, (_, i) => `line-${i}`).join("\r\n") + "\r\n");
  await expect.poll(async () => (await viewport(page)).base).toBeGreaterThan(50);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  const mod = (await platformIsMac(page)) ? "Meta" : "Control";
  const before = await typed(page);
  await page.keyboard.press(`${mod}+Home`);
  await expect.poll(async () => (await viewport(page)).y).toBe(0);
  await page.keyboard.press(`${mod}+End`);
  await expect.poll(async () => { const v = await viewport(page); return v.y === v.base; }).toBe(true);
  expect((await typed(page)).slice(before.length)).toBe("");
});

test("on Linux, Ctrl+Shift+V pastes the clipboard's text itself (WebKitGTK has no binding for it)", async ({ page }) => {
  // this test is the Linux page itself; a run that makes every page another platform (OMHER_E2E_PLATFORM) overrides it
  const other = process.env.OMHER_E2E_PLATFORM;
  test.skip(!!other && !/Linux/.test(other), `the run reports ${other} for every page`);
  await page.addInitScript(() => Object.defineProperty(navigator, "platform", { configurable: true, get: () => "Linux x86_64" }));
  await openApp(page, { clipboard: "from-linux-clipboard" });
  await newTerminal(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  const before = await typed(page);
  await page.keyboard.press("Control+Shift+V");
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("from-linux-clipboard");
});
