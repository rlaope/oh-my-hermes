// The Kitty keyboard protocol (xterm 6.1, Settings > Terminal > Modern key encoding, on by default), on the mock
// host: a program that asks for it (`CSI > 1 u`, as Claude Code and Codex do) gets Shift+Enter as `CSI 13;2 u`; one
// that does not ask, or any program with the setting off, gets `\r` as before. A terminal parked and made again
// keeps what its program asked for. Option+drag selects inside a program that reports the mouse (macOS).
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp, platformIsMac, pointAt, settle, typed } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

const focus = (page: Page) => page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();

/** What the page sends the program for one key press. */
async function sends(page: Page, key: string): Promise<string> {
  await focus(page);
  const before = (await typed(page)).length;
  await page.keyboard.press(key);
  await expect.poll(async () => (await typed(page)).length).toBeGreaterThan(before);
  await settle(page, 150);
  return (await typed(page)).slice(before);
}

const flags = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(window as unknown as { __omherTerms: Set<{ element?: HTMLElement; _core?: { coreService?: { kittyKeyboard?: { flags?: number } } } }> }).__omherTerms].find((x) => x.element === host);
    return t?._core?.coreService?.kittyKeyboard?.flags ?? -1;
  });

test("a program that asks for the Kitty protocol gets Shift+Enter as CSI 13;2 u, and Enter stays \\r", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\x1b[>1u");
  await expect.poll(() => flags(page)).toBe(1);
  expect(await sends(page, "Shift+Enter")).toBe("\x1b[13;2u");
  expect(await sends(page, "Enter")).toBe("\r");
  // the program pops it when it ends: back to the legacy bytes
  await feed(page, "\x1b[<u");
  expect(await sends(page, "Shift+Enter")).toBe("\r");
});

test("a program that does not ask keeps today's bytes: Shift+Enter is \\r", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  expect(await flags(page)).toBe(0);
  expect(await sends(page, "Shift+Enter")).toBe("\r");
  expect(await sends(page, "Enter")).toBe("\r");
});

test("with the setting off, a program's request is ignored and Shift+Enter is \\r", async ({ page }) => {
  await openApp(page, { term: { kittyKeys: false } });
  await newTerminal(page);
  await feed(page, "\x1b[>1u");
  expect(await flags(page)).toBe(0);
  expect(await sends(page, "Shift+Enter")).toBe("\r");
});

test("a query is answered only with the protocol on (CSI ? u -> CSI ? flags u)", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  const before = (await typed(page)).length;
  await feed(page, "\x1b[>1u\x1b[?u");
  await expect.poll(async () => (await typed(page)).slice(before)).toBe("\x1b[?1u");
});

test("Settings > Terminal: Modern key encoding (Kitty) is on by default, and off reaches an open terminal", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\x1b[>1u");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const row = page.getByTestId("term-kitty-row");
  await expect(row).toContainText("Modern key encoding (Kitty)");
  const sw = page.getByTestId("term-kitty");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Off" }).click();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ kittyKeys: false });
  await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  expect(await sends(page, "Shift+Enter")).toBe("\r");
});

test("a terminal parked and made again keeps the protocol its program asked for", async ({ page }) => {
  await openApp(page);
  const first = await newTerminal(page);
  await page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
  await feed(page, "\x1b[>1u");
  await expect.poll(() => flags(page)).toBe(1);
  await newTerminal(page); // the first one leaves the page
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherPark: { parked(): number } }).__omherPark.parked()), { timeout: 10_000 }).toBeGreaterThan(0);
  await page.getByTestId(`session-${first}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", first);
  await expect.poll(() => flags(page)).toBe(1);
  expect(await sends(page, "Shift+Enter")).toBe("\x1b[13;2u");
});

test("Option+drag selects text inside a program that reports the mouse, and sends it no mouse report", async ({ page }) => {
  await openApp(page);
  test.skip(!(await platformIsMac(page)), "Option-click selection is xterm's macOS behaviour");
  await newTerminal(page);
  await feed(page, "\r\nselect-me-please\r\n\x1b[?1000h\x1b[?1006h"); // a TUI turns mouse reporting on
  const a = await pointAt(page, "select-me-please", 0, 1);
  const b = await pointAt(page, "select-me-please", 15, 1);
  const before = (await typed(page)).length;
  await page.keyboard.down("Alt");
  await page.mouse.move(a.x - 2, a.y);
  await page.mouse.down();
  await page.mouse.move((a.x + b.x) / 2, b.y, { steps: 4 });
  await page.mouse.move(b.x + 2, b.y, { steps: 4 });
  await page.mouse.up();
  await page.keyboard.up("Alt");
  const selected = await page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    return [...(window as unknown as { __omherTerms: Set<{ element?: HTMLElement; getSelection(): string }> }).__omherTerms].find((t) => t.element === host)?.getSelection() ?? "";
  });
  expect(selected).toContain("select-me");
  expect((await typed(page)).slice(before)).not.toMatch(/\x1b\[</);
});
