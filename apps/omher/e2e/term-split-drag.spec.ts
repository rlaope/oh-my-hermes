// Drag to split (VS Code editor groups / Orca): a TERMINALS row dragged from the sidebar onto the open terminal puts
// that session in a pane on the side of the target pane nearest the pointer (right, left, over, under); a translucent
// half of the pane shows where while dragging, and Escape cancels. A row already in the split moves its pane; a full
// split shows no drop zone and takes nothing. A split pane's grip (top centre) drags the pane itself to another pane's
// side, and a click on it opens the pane's menu (zoom, even out, close, each with its key). One pane alone has no grip.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, platformIsMac } from "./term-find-helpers";
import { dragGripOnto, dragRowOnto } from "./split-drag-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string };
type Call = { op: string };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const pane = (page: Page, id: string) => page.locator(`[data-testid="split-pane"][data-session="${id}"]`);
const box = async (page: Page, id: string) => (await pane(page, id).boundingBox())!;
const order = (page: Page) => page.locator('[data-testid="split-pane"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-session")));
const shellStarts = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "start").length);

async function sessions(page: Page, folders: string[]): Promise<string[]> {
  const ids: string[] = [];
  for (const f of folders) {
    const id = await start(page, f);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  return ids;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a row dropped on the right half goes right, on the bottom half below; a row in the split moves its pane; Escape cancels", async ({ page }) => {
  await openApp(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  // c is open alone; a's row onto its right half: a right of c, with the keyboard
  await dragRowOnto(page, a, c, "right");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  expect(await order(page)).toEqual([c, a]);
  await expect(pane(page, a)).toHaveAttribute("data-focused", "true");
  // b's row onto a's bottom half: b under a
  await dragRowOnto(page, b, a, "down");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "3");
  let [rc, ra, rb] = [await box(page, c), await box(page, a), await box(page, b)];
  expect(ra.x).toBeGreaterThan(rc.x + rc.width - 2);
  expect(rb.y).toBeGreaterThan(ra.y + ra.height - 2);
  expect(Math.abs(rb.x - ra.x)).toBeLessThan(2);
  // c's row (already in the split) onto b's top half: c's pane moves over b, under a
  await dragRowOnto(page, c, b, "up");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "3");
  [rc, ra, rb] = [await box(page, c), await box(page, a), await box(page, b)];
  expect(rc.y).toBeGreaterThan(ra.y + ra.height - 2);
  expect(rb.y).toBeGreaterThan(rc.y + rc.height - 2);
  // Escape mid-drag: the zone goes and the drop does nothing
  const before = await order(page);
  await dragRowOnto(page, a, b, "left", { esc: true });
  expect(await order(page)).toEqual(before);
  // a row dragged onto its own pane finds no zone
  await dragRowOnto(page, b, b, "right", { drop: false });
  expect(await order(page)).toEqual(before);
  // nothing was started or stopped by any of it, and nothing reached a program
  expect(await shellStarts(page)).toBe(3);
  const calls = await page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((x) => x.op === "write" || x.op === "close"));
  expect(calls).toEqual([]);
});

test("a full split shows no drop zone and takes no fifth session", async ({ page }) => {
  await openApp(page);
  const [a, b, c, d, e] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d", "/w/e"]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await dragRowOnto(page, b, a, "right");
  await dragRowOnto(page, c, a, "down");
  await dragRowOnto(page, d, b, "down");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "4");
  const before = await order(page);
  await dragRowOnto(page, e, b, "right", { drop: false });
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "4");
  await expect(term(page, e)).toHaveCount(0);
  expect(await order(page)).toEqual(before);
  // a pane of the full split still moves
  await dragRowOnto(page, a, d, "right");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "4");
  const [rd, ra] = [await box(page, d), await box(page, a)];
  expect(ra.x).toBeGreaterThan(rd.x + rd.width - 2);
  expect(Math.abs(ra.y - rd.y)).toBeLessThan(2);
});

test("a pane's grip drags the pane to another pane's side, a click opens its menu; one pane alone has no grip", async ({ page }) => {
  await openApp(page);
  const mac = await platformIsMac(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  // b alone: no split, no grip
  await expect(term(page, b)).toBeVisible();
  await expect(page.getByTestId("split-grip")).toHaveCount(0);
  await dragRowOnto(page, a, b, "right");
  expect(await order(page)).toEqual([b, a]);
  await expect(page.getByTestId("split-grip")).toHaveCount(2);
  // the grip sits at the pane's top centre, over the terminal
  const [g, p] = [(await page.locator(`[data-testid="split-grip"][data-session="${a}"]`).boundingBox())!, await box(page, a)];
  expect(Math.abs(g.x + g.width / 2 - (p.x + p.width / 2))).toBeLessThan(2);
  expect(g.y - p.y).toBeLessThan(10);
  // a's grip onto b's left half: a moves left of b
  await dragGripOnto(page, a, b, "left");
  expect(await order(page)).toEqual([a, b]);
  // and onto b's bottom half: a under b
  await dragGripOnto(page, a, b, "down");
  const [rb, ra] = [await box(page, b), await box(page, a)];
  expect(ra.y).toBeGreaterThan(rb.y + rb.height - 2);
  // let go outside any pane: nothing moves
  await page.locator(`[data-testid="split-pane"][data-session="${a}"]`).hover();
  const ga = (await page.locator(`[data-testid="split-grip"][data-session="${a}"]`).boundingBox())!;
  await page.mouse.move(ga.x + ga.width / 2, ga.y + ga.height / 2);
  await page.mouse.down();
  const side = (await page.getByTestId("side-sessions").boundingBox())!;
  await page.mouse.move(side.x + side.width / 2, side.y + 20, { steps: 10 });
  await expect(page.getByTestId("split-drop")).toHaveCount(0);
  await page.mouse.up();
  expect(await order(page)).toEqual([b, a]);
  // a click on b's grip opens its menu: zoom, even out, close, each with its key
  await page.locator(`[data-testid="split-grip"][data-session="${b}"]`).click();
  const menu = page.getByTestId("split-pane-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem")).toHaveCount(3);
  await expect(menu.getByTestId("split-menu-zoom").locator("kbd")).toHaveText(mac ? "⌘⇧↩" : "Ctrl+Shift+Enter");
  await expect(menu.getByTestId("split-menu-equalize").locator("kbd")).toHaveText(mac ? "⌘⌃=" : "Ctrl+Alt+=");
  await expect(menu.getByTestId("split-menu-close").locator("kbd")).toHaveText(mac ? "⌘W" : "Ctrl+Shift+W");
  // Escape closes it; Zoom zooms b
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await page.locator(`[data-testid="split-grip"][data-session="${b}"]`).click();
  await page.getByTestId("split-menu-zoom").click();
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-zoom", "true");
  await expect(page.getByTestId("split-pane")).toHaveCount(1);
  // Close pane: b leaves the split (its session keeps running), a is alone
  await page.locator(`[data-testid="split-grip"][data-session="${b}"]`).click();
  await page.getByTestId("split-menu-close").click();
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect(page.getByTestId(`session-${b}`)).toHaveAttribute("data-status", "running");
});
