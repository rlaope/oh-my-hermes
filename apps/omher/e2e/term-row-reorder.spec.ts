// A TERMINALS row dragged onto another row of its folder in the sidebar moves there (splitDrag.ts rowTargetAt,
// sessions.ts moveRow): a line shows where, letting go puts it there, and the order is what comes back after a
// restart. A row of another folder takes no drop; a press that does not move stays a click.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp, usePlatform } from "./term-find-helpers";

type W = { __omherSessions: { startTerminal(a: string, c: string): string; getState(): { list: { id: string; cwd: string }[] } } };

/** open the app with fresh storage once; a reload keeps it (a restart) */
async function openKept(page: Page) {
  await usePlatform(page);
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.splits", "omher.termpanel.tabs", "__omherMockHistory", "omher.term"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as W).__omherSessions.startTerminal("shell", c), cwd);
const order = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as W).__omherSessions.getState().list.filter((r) => r.cwd === c).map((r) => r.id), cwd);
/** the rows of folder `cwd` as the sidebar shows them, top to bottom */
const shown = (page: Page, ids: string[]) =>
  page.evaluate((list) => {
    const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="session-list"] .ss-row.tr[data-testid^="session-"]')].map((e) => e.getAttribute("data-testid")!.slice(8));
    return rows.filter((r) => list.includes(r));
  }, ids);

/** press row `id`, move over the upper or lower half of row `onto`, check the line, let go */
async function dragRow(page: Page, id: string, onto: string, half: "upper" | "lower", o: { line?: boolean } = {}) {
  const from = (await page.getByTestId(`session-${id}`).locator(".ss-open").boundingBox())!;
  const to = (await page.getByTestId(`session-${onto}`).boundingBox())!;
  await page.mouse.move(from.x + 40, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + 60, to.y + to.height * (half === "upper" ? 0.25 : 0.75), { steps: 10 });
  const line = page.getByTestId("row-drop");
  if (o.line === false) await expect(line).toHaveCount(0);
  else {
    await expect(line).toHaveAttribute("data-session", onto);
    await expect(line).toHaveAttribute("data-after", String(half === "lower"));
  }
  await page.mouse.up();
  await expect(line).toHaveCount(0);
}

test("a row dragged above another row of its folder moves there, and the order survives a restart", async ({ page }) => {
  await openKept(page);
  // newest first: c, b, a
  const a = await start(page, "/w/web");
  const b = await start(page, "/w/web");
  const c = await start(page, "/w/web");
  await expect.poll(() => shown(page, [a, b, c])).toEqual([c, b, a]);
  // a (the bottom row) onto the upper half of c (the top row): a goes first
  await dragRow(page, a, c, "upper");
  await expect.poll(() => shown(page, [a, b, c])).toEqual([a, c, b]);
  expect(await order(page, "/w/web")).toEqual([a, c, b]);
  // c onto the lower half of b: c goes last
  await dragRow(page, c, b, "lower");
  await expect.poll(() => shown(page, [a, b, c])).toEqual([a, b, c]);
  // the saved list is written a moment later
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.resume") ?? "")).toMatch(new RegExp(`"${a}".*"${b}".*"${c}"`));
  await page.reload();
  await expect.poll(() => shown(page, [a, b, c])).toEqual([a, b, c]);
});

test("a row of another folder takes no drop, and a press that does not move opens the row", async ({ page }) => {
  await openApp(page);
  const a = await start(page, "/w/web");
  const b = await start(page, "/w/api");
  await dragRow(page, a, b, "upper", { line: false });
  expect(await order(page, "/w/web")).toEqual([a]);
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", a);
});
