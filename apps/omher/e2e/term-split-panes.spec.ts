// TERMINALS splits like Otty / Orca: ⌘D splits right and ⌘⇧D down (Ctrl+Shift+D / Alt+Shift+D off macOS), up to four
// sessions in any nesting; each split asks which session goes in the new pane (a running TERMINALS session, or a new
// Shell in the focused pane's folder, the one its shell last reported). The focused pane is the session open in the
// main column; the others are dimmed (Settings › Terminal › Dim unfocused panes). ⌘⌥arrows / ⌘] ⌘[ move the keyboard,
// ⌘⇧⌥arrows move the pane, ⌘⇧↩ zooms it, ⌘⌃= evens them out, ⌘W closes it (the session keeps running; the menu's
// Close Window does the same while a split has the keyboard, and closes the window otherwise). Rows in the split
// carry a glyph, Plans draws the split small, and the split comes back after a restart. Bot chats never split.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
type Call = { op: string; id?: number; agent?: string; cwd?: string | null; data?: string };
const start = (page: Page, cwd: string, agent = "shell") => page.evaluate(([c, a]) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal(a, c), [cwd, agent] as const);
const ptyOf = async (page: Page, id: string) => {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
};
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const pane = (page: Page, id: string) => page.locator(`[data-testid="split-pane"][data-session="${id}"]`);
const textarea = (page: Page, id: string) => term(page, id).locator(".xterm-helper-textarea");
const focusedTerm = (page: Page) => page.evaluate(() => document.activeElement?.closest('[data-testid="terminal"]')?.getAttribute("data-session") ?? null);
const shellStarts = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "start"));
const writes = (page: Page) => page.evaluate(() => [...((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []), ...((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? [])].filter((c) => c.op === "write"));

async function keys(page: Page) {
  const mac = await platformIsMac(page);
  return {
    right: mac ? "Meta+d" : "Control+Shift+D",
    down: mac ? "Meta+Shift+D" : "Alt+Shift+D",
    close: mac ? "Meta+w" : "Control+Shift+W",
    focus: (d: "Left" | "Right" | "Up" | "Down") => (mac ? `Meta+Alt+Arrow${d}` : `Control+Alt+Arrow${d}`),
    move: (d: "Left" | "Right" | "Up" | "Down") => (mac ? `Meta+Alt+Shift+Arrow${d}` : `Control+Alt+Shift+Arrow${d}`),
    next: mac ? "Meta+BracketRight" : "Control+Tab",
    prev: mac ? "Meta+BracketLeft" : "Control+Shift+Tab",
    zoom: mac ? "Meta+Shift+Enter" : "Control+Shift+Enter",
    even: mac ? "Meta+Control+Equal" : "Control+Alt+Equal",
  };
}

/** Sessions started in each folder (the last one opens); waits for each terminal's first line. */
async function sessions(page: Page, folders: string[]): Promise<string[]> {
  const ids: string[] = [];
  for (const f of folders) {
    const id = await start(page, f);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  return ids;
}

async function splitWith(page: Page, from: string, key: string, pick: string | "new") {
  await textarea(page, from).focus();
  await page.keyboard.press(key);
  await expect(page.getByTestId("split-picker")).toBeVisible();
  if (pick === "new") await page.getByTestId("split-new-shell").click();
  else await page.locator(`[data-testid="split-pick"][data-session="${pick}"]`).click();
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("⌘D right and ⌘⇧D down: four TERMINALS sessions in a nested split, no fifth; each pane takes its own output", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b, c, d, e] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d", "/w/e"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  // b went right of a and has the keyboard
  await expect.poll(() => focusedTerm(page)).toBe(b);
  await splitWith(page, b, k.down, c);
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "3");
  // c is under b, both right of a
  const [ra, rb, rc] = [(await term(page, a).boundingBox())!, (await term(page, b).boundingBox())!, (await term(page, c).boundingBox())!];
  expect(rb.x).toBeGreaterThan(ra.x + ra.width - 2);
  expect(rc.y).toBeGreaterThan(rb.y + rb.height - 2);
  expect(Math.abs(rc.x - rb.x)).toBeLessThan(2);
  await splitWith(page, a, k.down, d);
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "4");
  await expect(page.getByTestId("terminal")).toHaveCount(4);
  // the split is full: the key opens no picker, and nothing reaches the program
  await textarea(page, d).focus();
  await page.keyboard.press(k.right);
  await page.waitForTimeout(150);
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
  await expect(term(page, e)).toHaveCount(0);
  // each pane its own program's output
  for (const id of [a, b, c, d]) await out(page, await ptyOf(page, id), `from-${id}-pane\r\n`);
  for (const id of [a, b, c, d]) await expect(term(page, id).locator(".xterm-rows")).toContainText(`from-${id}-pane`);
  await expect(term(page, a).locator(".xterm-rows")).not.toContainText(`from-${b}-pane`);
  expect(await writes(page)).toEqual([]);
});

test("New Shell here starts a shell in the folder the focused pane's shell reported (OSC 7)", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a] = await sessions(page, ["/home/you/code/web-app"]);
  await out(page, await ptyOf(page, a), "\x1b]7;file:///home/you/code/web-app/packages/ui\x07");
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-cwd")).toHaveText("ui");
  await splitWith(page, a, k.down, "new");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await expect.poll(async () => (await shellStarts(page)).length).toBe(2);
  expect((await shellStarts(page)).at(-1)).toMatchObject({ cwd: "/home/you/code/web-app/packages/ui" });
  // the new shell is under the first and has the keyboard
  const id = await page.locator('[data-testid="split-pane"][data-focused="true"]').getAttribute("data-session");
  expect(id).not.toBe(a);
  const [ra, rn] = [(await term(page, a).boundingBox())!, (await term(page, id!).boundingBox())!];
  expect(rn.y).toBeGreaterThan(ra.y + ra.height - 2);
  await expect.poll(() => focusedTerm(page)).toBe(id);
});

test("the focused pane is the open session; the others are dimmed to the setting; focus, step, move, zoom and even keys", async ({ page }) => {
  await openApp(page, { term: { dimUnfocused: 0.6 } });
  const k = await keys(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  await splitWith(page, b, k.down, c);
  // c has the keyboard: it is the open session (header, row), drawn full; a and b are dimmed to 0.6
  await expect(page.getByTestId(`session-${c}`)).toHaveClass(/active/);
  await expect(pane(page, c)).toHaveAttribute("data-focused", "true");
  const opacity = (id: string) => pane(page, id).locator(".term-wrap").evaluate((el) => getComputedStyle(el).opacity);
  await expect.poll(() => opacity(c)).toBe("1");
  await expect.poll(() => opacity(a)).toBe("0.6");
  await expect.poll(() => opacity(b)).toBe("0.6");
  // the focused pane carries an accent line
  expect(await pane(page, c).evaluate((el) => getComputedStyle(el, "::after").boxShadow)).toContain("inset");
  // ⌘⌥← to a, ⌘⌥→ back to b (the nearest lined up), ⌘⌥↓ to c
  await page.keyboard.press(k.focus("Left"));
  await expect.poll(() => focusedTerm(page)).toBe(a);
  await expect(page.getByTestId(`session-${a}`)).toHaveClass(/active/);
  await expect.poll(() => opacity(a)).toBe("1");
  await page.keyboard.press(k.focus("Right"));
  await expect.poll(() => focusedTerm(page)).toBe(b);
  await page.keyboard.press(k.focus("Down"));
  await expect.poll(() => focusedTerm(page)).toBe(c);
  // ⌘] / ⌘[ step in reading order, wrapping
  await page.keyboard.press(k.next);
  await expect.poll(() => focusedTerm(page)).toBe(a);
  await page.keyboard.press(k.prev);
  await expect.poll(() => focusedTerm(page)).toBe(c);
  // a click in a pane focuses it
  await term(page, a).click();
  await expect(page.getByTestId(`session-${a}`)).toHaveClass(/active/);
  // ⌘⇧⌥→ moves a to the right (it trades places with the pane beside it) and keeps the keyboard
  const x0 = (await term(page, a).boundingBox())!.x;
  await textarea(page, a).focus();
  await page.keyboard.press(k.move("Right"));
  await expect.poll(async () => (await term(page, a).boundingBox())!.x).toBeGreaterThan(x0 + 100);
  await expect.poll(() => focusedTerm(page)).toBe(a);
  // ⌘⇧↩ zooms: only a shows, at full size; again: all three
  await page.keyboard.press(k.zoom);
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-zoom", "true");
  await expect(page.getByTestId("terminal")).toHaveCount(1);
  await expect(page.getByTestId("split-zoomed")).toBeVisible();
  await page.keyboard.press(k.zoom);
  await expect(page.getByTestId("terminal")).toHaveCount(3);
  // drag the first divider, then ⌘⌃= evens it out again
  const div = page.locator('[data-testid="split-divider"][data-path=""]');
  const d = (await div.boundingBox())!;
  await page.mouse.move(d.x + d.width / 2, d.y + 200);
  await page.mouse.down();
  await page.mouse.move(d.x - 200, d.y + 200, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => Number(await div.getAttribute("aria-valuenow"))).toBeLessThan(40);
  await textarea(page, a).focus();
  await page.keyboard.press(k.even);
  await expect.poll(async () => Number(await div.getAttribute("aria-valuenow"))).toBe(50);
  // none of these keys reached a program
  expect(await writes(page)).toEqual([]);
});

test("⌘W closes the focused pane (its session keeps running), the nearest pane takes the keyboard; the menu's Close Window does the same, then closes the window", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  await splitWith(page, b, k.down, c);
  await page.keyboard.press(k.close);
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await expect(pane(page, c)).toHaveCount(0);
  await expect.poll(() => focusedTerm(page)).toBe(b);
  // c still runs and is listed
  await expect(page.getByTestId(`session-${c}`)).toBeVisible();
  await expect(page.getByTestId(`session-${c}`)).toHaveAttribute("data-status", "running");
  // the menu's Close Window while the split has the keyboard (a later press: the menu hearing the same ⌘W just after
  // the key closed a pane is that press, and closes nothing more): the focused pane goes, never the window
  await page.evaluate(() => (window as unknown as { __omherMenuClose(): Promise<void> }).__omherMenuClose());
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await page.waitForTimeout(400);
  await textarea(page, b).focus();
  await page.evaluate(() => (window as unknown as { __omherMenuClose(): Promise<void> }).__omherMenuClose());
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveCount(1);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
  expect(await page.evaluate(() => (window as unknown as { __omherWindowCloses?: number }).__omherWindowCloses ?? 0)).toBe(0);
  // no split: ⌘W in a terminal is nothing of omher's here, and the menu's Close Window closes the window
  await textarea(page, a).focus();
  await page.evaluate(() => (window as unknown as { __omherMenuClose(): Promise<void> }).__omherMenuClose());
  expect(await page.evaluate(() => (window as unknown as { __omherWindowCloses?: number }).__omherWindowCloses ?? 0)).toBe(1);
  // nothing was stopped
  const closes = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []).filter((x) => x.op === "close"));
  expect(closes).toEqual([]);
});

test("the menu's Close Window and the ⌘W key close the pane that holds the keyboard, not the pane last clicked", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  await splitWith(page, b, k.down, c);
  await pane(page, a).click();
  await expect(pane(page, a)).toHaveAttribute("data-focused", "true");
  await expect(textarea(page, a)).toBeFocused();
  // the keyboard moves into b without a click there (Tab from its close button)
  await pane(page, b).getByTestId("split-close").focus();
  await page.keyboard.press("Tab");
  await expect(textarea(page, b)).toBeFocused();
  await expect(pane(page, a)).toHaveAttribute("data-focused", "true");
  await page.evaluate(() => (window as unknown as { __omherMenuClose(): Promise<void> }).__omherMenuClose());
  await expect(pane(page, b)).toHaveCount(0);
  await expect(pane(page, a)).toHaveCount(1);
  await expect(pane(page, c)).toHaveCount(1);
  // the same for the key: c holds the keyboard, a is still the pane last clicked
  await page.waitForTimeout(400);
  await pane(page, c).getByTestId("split-close").focus();
  await page.keyboard.press("Tab");
  await expect(textarea(page, c)).toBeFocused();
  await page.keyboard.press(k.close);
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
  expect(await page.evaluate(() => (window as unknown as { __omherWindowCloses?: number }).__omherWindowCloses ?? 0)).toBe(0);
});

test("rows in the open split carry a glyph (the focused one marked); Plans draws the split small and a click there focuses that pane", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-split-glyph")).toBeVisible();
  await expect(page.getByTestId(`session-${b}`)).toHaveAttribute("data-split", "focused");
  await expect(page.getByTestId(`session-${a}`)).toHaveAttribute("data-split", "in");
  await expect(page.getByTestId(`session-${c}`).getByTestId("term-split-glyph")).toHaveCount(0);
  // Plans: two boxes side by side, b filled
  await page.keyboard.press((await platformIsMac(page)) ? "Meta+." : "Control+.");
  await expect(page.getByTestId("split-map")).toBeVisible();
  await expect(page.getByTestId("split-map-box")).toHaveCount(2);
  const boxA = page.locator(`[data-testid="split-map-box"][data-session="${a}"]`);
  const boxB = page.locator(`[data-testid="split-map-box"][data-session="${b}"]`);
  await expect(boxB).toHaveAttribute("data-focused", "true");
  // bare shells are named by their folder in the map and in the row glyph's label, not "Shell" each
  await expect(boxA).toHaveAttribute("title", "a");
  await expect(boxB).toHaveAttribute("title", "b");
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-split-glyph")).toHaveAttribute("aria-label", /: a$/);
  // both boxes measured in one frame, polled while the panel opens: b's left edge meets a's right edge, same top
  const beside = () =>
    page.evaluate(([ia, ib]) => {
      const r = (i: string) => document.querySelector(`[data-testid="split-map-box"][data-session="${i}"]`)!.getBoundingClientRect();
      const [ra, rb] = [r(ia), r(ib)];
      return rb.x > ra.x + ra.width - 2 && Math.abs(rb.y - ra.y) < 2;
    }, [a, b] as const);
  await expect.poll(beside).toBe(true);
  // the session's own plans are still below it
  await expect(page.getByTestId("plans-empty")).toBeVisible();
  await boxA.click();
  await expect(boxA).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId(`session-${a}`)).toHaveAttribute("data-split", "focused");
  await expect.poll(() => focusedTerm(page)).toBe(a);
  // a session alone has no map
  await page.getByTestId(`session-${c}`).locator(".ss-open").click();
  await expect(page.getByTestId("split-map")).toHaveCount(0);
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-split-glyph")).toHaveCount(0);
});

test("the picker opens under the focused pane's bar, so the bar's x stays clickable", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await splitWith(page, a, k.right, b);
  // b has the keyboard; split again from it
  await textarea(page, b).focus();
  await page.keyboard.press(k.down);
  const picker = page.getByTestId("split-picker");
  await expect(picker).toBeVisible();
  const x = pane(page, b).getByTestId("split-close");
  const [p, xb] = [(await picker.boundingBox())!, (await x.boundingBox())!];
  const overlaps = p.x < xb.x + xb.width && xb.x < p.x + p.width && p.y < xb.y + xb.height && xb.y < p.y + p.height;
  expect(overlaps).toBe(false);
  expect(p.y).toBeGreaterThanOrEqual(xb.y + xb.height);
  // the x at the centre of its box is the x itself, not the picker
  const hit = await page.evaluate(([cx, cy]) => !!document.elementFromPoint(cx, cy)?.closest('[data-testid="split-close"]'), [xb.x + xb.width / 2, xb.y + xb.height / 2] as const);
  expect(hit).toBe(true);
  await page.locator(`[data-testid="split-pick"][data-session="${c}"]`).click();
  await expect(page.getByTestId("split-pane")).toHaveCount(3);
});

test("bot chats never split: the keys do nothing there, and the picker lists TERMINALS sessions only", async ({ page }) => {
  await openApp(page);
  const k = await keys(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  // the bot chat: ⌘D opens no picker and no split
  await page.getByTestId("bot-kami").click();
  await page.getByTestId("composer-input").or(page.locator("textarea").first()).first().focus();
  await page.keyboard.press(k.right);
  await page.waitForTimeout(150);
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  // the picker in a TERMINALS session offers the other TERMINALS session and New Shell, nothing else
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await textarea(page, a).focus();
  await page.keyboard.press(k.right);
  await expect(page.getByTestId("split-pick")).toHaveCount(1);
  await expect(page.getByTestId("split-pick")).toHaveAttribute("data-session", b);
  await expect(page.getByTestId("split-new-shell")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
  await expect.poll(() => focusedTerm(page)).toBe(a);
});
