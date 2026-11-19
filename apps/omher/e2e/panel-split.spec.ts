// Bottom panel split panes (Otty split_right/down, Orca terminal panes): ⌘D splits the focused pane right and ⌘⇧D down
// (Ctrl+Shift+D / Alt+Shift+D off macOS), each pane its own login shell (`shell_start` with the pane's size) in the
// focused pane's folder, at most four. A divider drags (the panes' shells get their new sizes) and a double click evens
// them. A shell that exits closes its pane and the sibling takes the room; ⌘W closes the focused pane; the last pane
// closes the tab. ⌘⌥arrows move the keyboard between panes, and the focused pane is marked.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";

const PROJECT = "/home/you/code/web-app";
type Call = { op: string; id: number; cwd?: string | null; at?: string; cols?: number; rows?: number; data?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []) as Call[]);
const starts = async (page: Page) => (await calls(page)).filter((c) => c.op === "start");
const panes = (page: Page) => page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]');
const focusedPane = (page: Page) => page.evaluate(() => document.activeElement?.closest('[data-testid="termpanel-terminal"]')?.getAttribute("data-pane") ?? null);

async function keys(page: Page) {
  const mac = await platformIsMac(page);
  return {
    right: mac ? "Meta+d" : "Control+Shift+D",
    down: mac ? "Meta+Shift+D" : "Alt+Shift+D",
    close: mac ? "Meta+w" : "Control+Shift+W",
    move: (dir: "Left" | "Right" | "Up" | "Down") => (mac ? `Meta+Alt+Arrow${dir}` : `Control+Alt+Arrow${dir}`),
  };
}

async function openPanel(page: Page) {
  await openApp(page);
  await page.evaluate(async (p) => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd(p);
  }, PROJECT);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(panes(page).first().locator(".xterm-rows")).toContainText(`login shell in ${PROJECT}`);
  await expect.poll(() => focusedPane(page)).not.toBeNull();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("⌘D twice: three panes, three login shells started with their own sizes, in the focused pane's folder", async ({ page }) => {
  await openPanel(page);
  const k = await keys(page);
  await page.keyboard.press(k.right);
  await expect(panes(page)).toHaveCount(2);
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  await expect.poll(() => focusedPane(page)).toBe(await panes(page).nth(1).getAttribute("data-pane"));
  await page.keyboard.press(k.down);
  await expect(panes(page)).toHaveCount(3);
  await expect.poll(async () => (await starts(page)).length).toBe(3);
  const s = await starts(page);
  // every shell in the folder the first one started in, each with a real size
  expect(s.map((c) => c.at)).toEqual([PROJECT, PROJECT, PROJECT]);
  for (const c of s) {
    expect(c.cols).toBeGreaterThan(10);
    expect(c.rows).toBeGreaterThan(1);
  }
  // the right-hand pane split again, down: its two halves are narrower than the first pane's full height
  expect(s[1].cols).toBeLessThan(s[0].cols! + 1);
  expect(s[2].rows).toBeLessThan(s[0].rows!);
  await expect(page.getByTestId("termpanel-split")).toHaveCount(2);
  // each pane is its own shell: typing goes to the focused one only
  await page.keyboard.type("echo third\r");
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "write" && c.id === s[2].id).map((c) => c.data).join("")).toBe("echo third\r");
  expect((await calls(page)).filter((c) => c.op === "write" && c.id !== s[2].id)).toEqual([]);
  // the first pane, now narrower, was told its new size
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "resize" && c.id === s[0].id).length).toBeGreaterThan(0);
  // the focused pane is marked, the others are not
  await expect(page.locator(".termpanel .term-wrap.focused")).toHaveCount(1);
  await expect(page.locator(".termpanel .term-wrap.focused")).toHaveAttribute("data-pane", (await panes(page).nth(2).getAttribute("data-pane"))!);
});

test("at most four panes in a tab", async ({ page }) => {
  await openPanel(page);
  const k = await keys(page);
  for (let i = 0; i < 5; i++) await page.keyboard.press(i % 2 ? k.down : k.right);
  await expect(panes(page)).toHaveCount(4);
  await page.waitForTimeout(150);
  expect(await starts(page)).toHaveLength(4);
  await expect(page.getByTestId("termpanel-split-right")).toBeDisabled();
});

test("dragging the divider resizes both shells; a double click evens the panes again", async ({ page }) => {
  await openPanel(page);
  await page.keyboard.press((await keys(page)).right);
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  const [a, b] = await starts(page);
  // let the split's own sizes settle first: the left shell was told it is narrower than the whole width now
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "resize" && c.id === a.id).at(-1)?.cols ?? 999).toBeLessThan(a.cols!);
  await page.waitForTimeout(150);
  const left0 = (await panes(page).nth(0).boundingBox())!;
  const d = (await page.getByTestId("termpanel-divider").boundingBox())!;
  await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2);
  await page.mouse.down();
  await page.mouse.move(d.x - 200, d.y + d.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => Math.round((await panes(page).nth(0).boundingBox())!.width)).toBeLessThan(Math.round(left0.width - 150));
  // each shell hears its new size once it settles: the last size each was told, once those stop changing (a slow
  // machine is still sending the drag's steps after the mouse is up), has the left shell narrower than the right
  const last = async () => {
    const c = (await calls(page)).filter((x) => x.op === "resize");
    return [c.filter((x) => x.id === a.id).at(-1)?.cols ?? 0, c.filter((x) => x.id === b.id).at(-1)?.cols ?? 0];
  };
  let seen = "";
  await expect
    .poll(async () => {
      const now = JSON.stringify(await last());
      const still = now === seen;
      seen = now;
      return still;
    }, { intervals: [250] })
    .toBe(true);
  const [lastA, lastB] = JSON.parse(seen) as number[];
  expect(lastA).toBeLessThan(lastB);
  // a pane keeps at least 120px
  await page.mouse.move(d.x - 200, d.y + d.height / 2);
  await page.mouse.down();
  await page.mouse.move(0, d.y + d.height / 2, { steps: 6 });
  await page.mouse.up();
  expect((await panes(page).nth(0).boundingBox())!.width).toBeGreaterThanOrEqual(119);
  // double click: half and half
  const d2 = (await page.getByTestId("termpanel-divider").boundingBox())!;
  await page.mouse.dblclick(d2.x + d2.width / 2, d2.y + d2.height / 2);
  await expect
    .poll(async () => {
      const [l, r] = [(await panes(page).nth(0).boundingBox())!, (await panes(page).nth(1).boundingBox())!];
      return Math.abs(l.width - r.width) < 4;
    })
    .toBe(true);
});

test("a shell that exits closes its pane and the sibling takes its room; ⌘W closes the focused pane; the last pane closes the tab", async ({ page }) => {
  await openPanel(page);
  const k = await keys(page);
  await page.keyboard.press(k.right);
  await expect.poll(async () => (await starts(page)).length).toBe(2);
  const [a, b] = await starts(page);
  const leftW = (await panes(page).nth(0).boundingBox())!.width;
  await expect.poll(() => focusedPane(page)).toBe(await panes(page).nth(1).getAttribute("data-pane"));
  await page.keyboard.type("exit\r");
  await expect(panes(page)).toHaveCount(1);
  await expect(page.getByTestId("termpanel-tab")).toHaveCount(1);
  // the left pane grew into the room and its shell was told the wider size
  await expect.poll(async () => (await panes(page).nth(0).boundingBox())!.width).toBeGreaterThan(leftW + 100);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "resize" && c.id === a.id).at(-1)?.cols ?? 0).toBeGreaterThan(b.cols! + 10);
  await expect.poll(() => focusedPane(page)).toBe(await panes(page).nth(0).getAttribute("data-pane"));
  // ⌘W on a split: that pane's shell only is stopped
  await page.keyboard.press(k.right);
  await expect.poll(async () => (await starts(page)).length).toBe(3);
  const c = (await starts(page))[2];
  await expect.poll(() => focusedPane(page)).toBe(await panes(page).nth(1).getAttribute("data-pane"));
  await page.keyboard.press(k.close);
  await expect(panes(page)).toHaveCount(1);
  await expect.poll(async () => (await calls(page)).filter((x) => x.op === "close").map((x) => x.id)).toEqual([c.id]);
  // ⌘W on the last pane closes the tab, and with it the panel
  await expect.poll(() => focusedPane(page)).not.toBeNull();
  await page.keyboard.press(k.close);
  await expect(page.getByTestId("termpanel")).toBeHidden();
  await expect.poll(async () => (await calls(page)).filter((x) => x.op === "close").map((x) => x.id)).toEqual([c.id, a.id]);
});

test("⌘⌥arrows move the keyboard between panes", async ({ page }) => {
  await openPanel(page);
  const k = await keys(page);
  await page.keyboard.press(k.right);
  await expect(panes(page)).toHaveCount(2);
  await page.keyboard.press(k.down);
  await expect(panes(page)).toHaveCount(3);
  const ids = await panes(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-pane")));
  // 1 | 2
  //   | 3      (focus on 3)
  await expect.poll(() => focusedPane(page)).toBe(ids[2]);
  await page.keyboard.press(k.move("Up"));
  await expect.poll(() => focusedPane(page)).toBe(ids[1]);
  await page.keyboard.press(k.move("Left"));
  await expect.poll(() => focusedPane(page)).toBe(ids[0]);
  await page.keyboard.press(k.move("Right"));
  await expect.poll(() => focusedPane(page)).toBe(ids[1]);
  await expect(page.locator(".termpanel .term-wrap.focused")).toHaveAttribute("data-pane", ids[1]!);
  // the arrows never reached a shell
  expect((await calls(page)).filter((c) => c.op === "write")).toEqual([]);
});
