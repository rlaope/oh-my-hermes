// Terminal font size keys: Cmd+= / Cmd+- / Cmd+0 on macOS, Ctrl with the same keys elsewhere, pressed with the
// keyboard in a terminal. They move Settings > Terminal's font size (kept on this computer), every open terminal
// takes it, and the program never sees the key.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

const PROJECT = "/home/you/code/web-app";
const pane = (page: Page) => page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]').first();
const stored = (page: Page) => page.evaluate(() => (JSON.parse(localStorage.getItem("omher.term") ?? "{}") as { fontSize?: number }).fontSize ?? null);
const cellHeight = (page: Page) => pane(page).locator(".xterm-rows > div").first().evaluate((el) => el.getBoundingClientRect().height);
type Call = { op: string; data?: string };
const written = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "write").map((c) => c.data ?? "").join(""));

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Cmd/Ctrl+= makes terminal text bigger, - smaller, 0 the default; the shell gets none of it", async ({ page }) => {
  await openApp(page);
  await page.evaluate(async (p) => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd(p);
  }, PROJECT);
  await page.keyboard.press("Control+Backquote");
  await expect(pane(page).locator(".xterm-rows")).toContainText(`login shell in ${PROJECT}`);
  await pane(page).locator(".xterm-helper-textarea").focus();
  const mod = (await platformIsMac(page)) ? "Meta" : "Control";
  const before = await cellHeight(page);
  const sent = await written(page);

  await page.keyboard.press(`${mod}+Equal`);
  await page.keyboard.press(`${mod}+Equal`);
  await expect.poll(() => stored(page)).toBe(15);
  await expect.poll(() => cellHeight(page)).toBeGreaterThan(before);

  await page.keyboard.press(`${mod}+Minus`);
  await expect.poll(() => stored(page)).toBe(14);

  await page.keyboard.press(`${mod}+Digit0`);
  await expect.poll(() => stored(page)).toBe(13);
  await expect.poll(() => cellHeight(page)).toBe(before);
  expect(await written(page)).toBe(sent);
});
