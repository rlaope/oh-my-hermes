// TERMINALS side by side: the open terminal session shows a second one beside it. ⌘D in a TERMINALS terminal
// (Ctrl+Shift+D off macOS) splits at once with a new Shell in its folder, no picker; another TERMINALS row dragged
// onto the open terminal's right half shows that session beside it; both sides then show and both take their
// program's output; the divider drags; the x on either side returns to one terminal (the other side's session stays
// open).
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";
import { dragRowOnto } from "./split-drag-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const ptyOf = async (page: Page, id: string) => {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
};
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const splitKey = async (page: Page) => ((await platformIsMac(page)) ? "Meta+d" : "Control+Shift+D");

async function twoSessions(page: Page): Promise<[string, string]> {
  await openApp(page);
  const a = await start(page, "/home/you/code/web-app");
  await expect(term(page, a).locator(".xterm-rows")).toContainText("login shell in");
  const b = await start(page, "/home/you/code/api-server");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("login shell in");
  return [a, b];
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("⌘D in a TERMINALS terminal splits right at once with a new Shell in its folder, no picker; both terminals take their own output", async ({ page }) => {
  const [a, b] = await twoSessions(page);
  // b is open; its terminal has the keyboard
  await term(page, b).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press(await splitKey(page));
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await expect(page.getByTestId("terminal")).toHaveCount(2);
  // the new pane is a new Shell (not a, the other running session), started in b's folder, and has the keyboard
  const n = (await page.locator('[data-testid="split-pane"][data-focused="true"]').getAttribute("data-session"))!;
  expect([a, b]).not.toContain(n);
  await expect(term(page, a)).toHaveCount(0);
  const starts = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string; agent?: string; cwd?: string | null }[] }).__omherShellCalls ?? []).filter((c) => c.op === "start"));
  expect(starts).toHaveLength(3);
  expect(starts.at(-1)).toMatchObject({ cwd: "/home/you/code/api-server" });
  await expect(term(page, n).locator(".xterm-rows")).toContainText("login shell in");
  // side by side
  const [bb, bn] = [(await term(page, b).boundingBox())!, (await term(page, n).boundingBox())!];
  expect(bn.x).toBeGreaterThan(bb.x + bb.width - 2);
  // each shows its own program's output, at once
  await out(page, await ptyOf(page, n), "from-the-right-session-n\r\n");
  await out(page, await ptyOf(page, b), "from-the-left-session-b\r\n");
  await expect(term(page, n).locator(".xterm-rows")).toContainText("from-the-right-session-n");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("from-the-left-session-b");
  await expect(term(page, n).locator(".xterm-rows")).not.toContainText("from-the-left-session-b");
  // the ⌘D never reached a program
  const writes = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string; data?: string }[] }).__omherShellCalls ?? []).filter((c) => c.op === "write"));
  expect(writes).toEqual([]);
});

test("a TERMINALS row dragged onto the open terminal's right half shows it beside; the divider drags; closing either side returns to one", async ({ page }) => {
  const [a, b] = await twoSessions(page);
  // the background menu has no split entry: a drag puts an existing session in a split
  await page.getByTestId("side-sessions").click({ button: "right", position: { x: 40, y: 8 } });
  await expect(page.getByTestId("sessions-context-menu")).toBeVisible();
  await expect(page.getByTestId("session-split-with")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await dragRowOnto(page, a, b, "right");
  await expect(page.getByTestId("session-split")).toBeVisible();
  expect(await page.locator('[data-testid="split-pane"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-session")))).toEqual([b, a]);
  // drag the divider left: the left side shrinks and its shell hears the new size
  const w0 = (await term(page, b).boundingBox())!.width;
  const d = (await page.getByTestId("split-divider").boundingBox())!;
  await page.mouse.move(d.x + d.width / 2, d.y + 200);
  await page.mouse.down();
  await page.mouse.move(d.x - 150, d.y + 200, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => (await term(page, b).boundingBox())!.width).toBeLessThan(w0 - 100);
  const pb = await ptyOf(page, b);
  await expect
    .poll(async () => {
      const calls = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string; id: number; cols?: number }[] }).__omherShellCalls ?? []).filter((c) => c.op === "resize"));
      return calls.filter((c) => c.id === pb).at(-1)?.cols ?? 999;
    })
    .toBeLessThan(80);
  // close the right side: b alone
  await page.locator(`[data-testid="split-tools"][data-session="${a}"] [data-testid="split-close"]`).click();
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveCount(1);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", b);
  // split again and close the left side: the right one (a) stays open alone
  await dragRowOnto(page, a, b, "right");
  await expect(page.getByTestId("terminal")).toHaveCount(2);
  await page.locator(`[data-testid="split-tools"][data-session="${b}"] [data-testid="split-close"]`).click();
  await expect(page.getByTestId("terminal")).toHaveCount(1);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
  // nothing was stopped
  const closes = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string }[] }).__omherShellCalls ?? []).filter((c) => c.op === "close"));
  expect(closes).toEqual([]);
});

test("the side beside counts as shown: it is not parked or hidden while both show", async ({ page }) => {
  const [a, b] = await twoSessions(page);
  await dragRowOnto(page, a, b, "right");
  await expect(page.getByTestId("terminal")).toHaveCount(2);
  // a fast park sweep: neither side is parked while both show
  type Park = { set(l: object): void; parked(): number };
  await page.evaluate(() => (window as unknown as { __omherPark: Park }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => (window as unknown as { __omherPark: Park }).__omherPark.parked())).toBe(0);
  await out(page, await ptyOf(page, a), "still-drawn-on-the-right\r\n");
  await expect(term(page, a).locator(".xterm-rows")).toContainText("still-drawn-on-the-right");
  await expect(term(page, a).locator(".xterm-rows")).toContainText("login shell in");
  // closing the split hides the side that left: it is parked like any hidden terminal, and comes back with its text
  await page.locator(`[data-testid="split-tools"][data-session="${a}"] [data-testid="split-close"]`).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherPark: Park }).__omherPark.parked())).toBe(1);
});

test("an app theme change reaches every pane of a split, and back (each view's mount no longer relooks them all)", async ({ page }) => {
  const [, b] = await twoSessions(page);
  await term(page, b).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press(await splitKey(page));
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  // each pane's box takes its terminal's theme background (look.ts applyLook, --term-bg)
  const bgs = () => page.locator('[data-testid="terminal"]').evaluateAll((els) => els.map((el) => (el as HTMLElement).style.getPropertyValue("--term-bg")));
  const setTheme = (t: "light" | "dark") =>
    page.evaluate(async (t) => {
      const m = (await import("/src/state/store.ts" as string)) as { getStore(): { actions: { setTheme(t: string): void } } };
      m.getStore().actions.setTheme(t);
    }, t);
  const first = await bgs();
  expect(first).toHaveLength(2);
  expect(first[0]).toBe(first[1]);
  // whichever theme the app opened in, the other one reaches both panes, then the first comes back to both
  await setTheme(await page.evaluate(() => (document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark")));
  await expect.poll(async () => (await bgs()).every((c) => c && c !== first[0])).toBe(true);
  const other = await bgs();
  expect(other[0]).toBe(other[1]);
  await setTheme(await page.evaluate(() => (document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark")));
  await expect.poll(bgs).toEqual(first);
});
