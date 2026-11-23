// A program's progress done (OSC 9;4;0) that nobody saw is quiet news: the row shows news and no notification goes
// out. It must never swallow a real ring after it: a bell (an approval or a question) that comes while that done is
// still unseen notifies as a fresh bell does. Reporting working again clears the quiet done (the chip says working,
// not a stale news). A bell nobody has seen is not downgraded to quiet by a later done.
// (Cross-model re-review, 2026-11-23: a quiet completion swallowed the next approval alert.)
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp } from "./term-find-helpers";

type W = { __omherNotes: { title: string; body?: string }[]; __omherMockOut(p: number, d: string): boolean; __omherSessions: { startTerminal(a: string, f: string): string; ptyOf(id: string): number | null } };
const ST = "\x1b\\";
const working = `\x1b]9;4;3${ST}`;
const done = `\x1b]9;4;0${ST}`;

test.beforeEach(async ({ page }) => {
  await mock("mock.reset");
  await page.addInitScript(() => {
    const w = window as unknown as W & { Notification: unknown };
    w.__omherNotes = [];
    w.Notification = class {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string } = {}) {
        w.__omherNotes.push({ title, body: opts.body });
      }
      close() {}
    };
  });
  await openApp(page);
});

const notes = (page: Page) => page.evaluate(() => (window as unknown as W).__omherNotes.slice());
async function start(page: Page, folder: string): Promise<string> {
  const id = await page.evaluate((f) => (window as unknown as W).__omherSessions.startTerminal("claude", f), folder);
  await expect(page.locator(`[data-testid="terminal"][data-session="${id}"] .xterm-rows`)).toContainText("(mock)");
  return id;
}
const out = (page: Page, id: string, d: string) =>
  page.evaluate(([i, s]) => {
    const w = window as unknown as W;
    return w.__omherMockOut(w.__omherSessions.ptyOf(i)!, s);
  }, [id, d] as const);
const row = (page: Page, id: string) => page.getByTestId(`session-${id}`);

test("a quiet done is news with no notification, and a real bell after it still notifies once", async ({ page }) => {
  const a = await start(page, "/w/quiet");
  await start(page, "/w/other"); // the person looks at another session: a is unseen
  expect(await out(page, a, working)).toBe(true);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "busy");
  await out(page, a, done);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "news");
  await page.waitForTimeout(300);
  expect(await notes(page)).toEqual([]);
  // the approval comes while the done is still unseen: it rings, and the person is told
  await out(page, a, "\x07");
  await expect.poll(() => notes(page)).toHaveLength(1);
  expect((await notes(page))[0].title).toContain("quiet");
  await expect(row(page, a)).toHaveAttribute("data-term-status", "news");
  // a done after that unseen bell does not turn it quiet: the bell is not told again, the row stays news
  await out(page, a, working);
  await out(page, a, done);
  await page.waitForTimeout(300);
  expect(await notes(page)).toHaveLength(1);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "news");
});

test("working again clears a quiet done, so the next done is news again and a bell after it notifies", async ({ page }) => {
  const a = await start(page, "/w/again");
  await start(page, "/w/other");
  await out(page, a, working);
  await out(page, a, done);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "news");
  // the next task starts without the person visiting: the row says busy, not a stale news
  await out(page, a, working);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "busy");
  await out(page, a, `\x07${done}`);
  await expect.poll(() => notes(page)).toHaveLength(1);
  await expect(row(page, a)).toHaveAttribute("data-term-status", "news");
});
