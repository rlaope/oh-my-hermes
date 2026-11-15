// The bottom terminal panel (mock shell host): Ctrl+` opens it at the folder setTerminalCwd named and gives the
// shell the keyboard, typing echoes, Ctrl+` from inside the terminal hides it and brings it back with the scrollback
// kept, Esc stays the shell's, a second tab starts its own shell, and closing a tab stops that shell.
// Shots first: bt-shots/term-{open-dark,open-light,tabs}.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { mock, openApp } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS_DIR || "/Users/khope@sionic.ai/.hermes/profiles/kami/cache/scratch/bt-shots";
const PROJECT = "/Users/you/code/web-app";

type Call = { op: string; id: number; cwd?: string | null; at?: string; data?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []) as Call[]);
const panel = (page: Page) => page.getByTestId("termpanel");
const shown = (page: Page) => page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');

async function setCwd(page: Page, path: string | null) {
  await page.evaluate(async (p) => {
    const m = (await import("/src/terminal/state.ts" as string)) as { setTerminalCwd(p: string | null): void };
    m.setTerminalCwd(p);
  }, path);
}

const focusInTerminal = (page: Page) => page.evaluate(() => !!document.activeElement?.closest('[data-testid="termpanel-terminal"]'));

async function openAt(page: Page, theme: "dark" | "light" = "dark") {
  await openApp(page, { theme });
  await setCwd(page, PROJECT);
  await page.keyboard.press("Control+Backquote");
  await expect(panel(page)).toBeVisible();
  await expect(shown(page)).toContainText(`login shell in ${PROJECT}`);
  await expect.poll(() => focusInTerminal(page)).toBe(true);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test.describe("shots", () => {
  test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
  for (const theme of ["dark", "light"] as const) {
    test(`term-open-${theme}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme });
      await openAt(page, theme);
      await page.keyboard.type("git log --oneline\r");
      await expect(shown(page)).toContainText("Merge pull request #2900");
      await page.keyboard.type("pnpm test\r");
      await expect(shown(page)).toContainText("Test Files");
      await page.screenshot({ path: `${SHOTS}/term-open-${theme}.png`, animations: "disabled" });
    });
  }
  test("term-tabs", async ({ page }) => {
    await openAt(page);
    await page.keyboard.type("pnpm test\r");
    await setCwd(page, "/Users/you/code/api-server");
    await page.getByTestId("termpanel-new").click();
    await expect(shown(page)).toContainText("login shell in /Users/you/code/api-server");
    await setCwd(page, null);
    await page.getByTestId("termpanel-new").click();
    await expect(shown(page)).toContainText("login shell in /Users/you");
    await page.keyboard.type("git log --oneline\r");
    await expect(shown(page)).toContainText("Merge pull request");
    await page.screenshot({ path: `${SHOTS}/term-tabs.png`, animations: "disabled" });
  });
});

test("Ctrl+` opens the panel at the open thread's folder, with the keyboard in the shell", async ({ page }) => {
  await openAt(page);
  const start = (await calls(page)).filter((c) => c.op === "start");
  expect(start).toEqual([expect.objectContaining({ op: "start", cwd: PROJECT, at: PROJECT })]);
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["web-app"]);
  // it sits in the main column, under the view, full width of the column
  const [main, box] = await Promise.all([page.locator("main.main").boundingBox(), panel(page).boundingBox()]);
  expect(Math.round(box!.x)).toBe(Math.round(main!.x));
  expect(Math.round(box!.width)).toBe(Math.round(main!.width));
  expect(Math.round(box!.y + box!.height)).toBe(Math.round(main!.y + main!.height));
});

test("with no thread folder the shell starts at home", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  await expect(shown(page)).toContainText("login shell in /Users/you");
  expect((await calls(page)).find((c) => c.op === "start")).toMatchObject({ cwd: null, at: "/Users/you" });
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["you"]);
});

test("typing echoes; Ctrl+` from inside the terminal hides it, and it comes back with the scrollback and the same shell", async ({ page }) => {
  await openAt(page);
  await page.keyboard.type("echo kept-in-scrollback\r");
  await expect(shown(page)).toContainText("echo kept-in-scrollback");
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "write").map((c) => c.data).join("")).toBe("echo kept-in-scrollback\r");
  // the keyboard is inside xterm: Ctrl+` is still omher's, never the shell's
  expect(await focusInTerminal(page)).toBe(true);
  await page.keyboard.press("Control+Backquote");
  await expect(panel(page)).toBeHidden();
  await expect(panel(page)).toHaveAttribute("data-open", "false");
  await page.keyboard.press("Control+Backquote");
  await expect(panel(page)).toBeVisible();
  await expect(shown(page)).toContainText("echo kept-in-scrollback");
  await expect.poll(() => focusInTerminal(page)).toBe(true);
  const c = await calls(page);
  expect(c.filter((x) => x.op === "start")).toHaveLength(1);
  expect(c.filter((x) => x.op === "close")).toHaveLength(0);
  expect(c.filter((x) => x.op === "write").map((x) => x.data).join("")).not.toContain("`");
});

test("Esc in the terminal goes to the shell and does not close the panel", async ({ page }) => {
  await openAt(page);
  await page.keyboard.press("Escape");
  await expect(panel(page)).toBeVisible();
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "write").map((c) => c.data)).toContain("\x1b");
});

test("a second tab is its own shell; closing a tab stops its shell, the last one hides the panel", async ({ page }) => {
  await openAt(page);
  await page.keyboard.type("echo first\r");
  await setCwd(page, "/Users/you/code/api-server");
  await page.getByTestId("termpanel-new").click();
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["web-app", "api-server"]);
  await expect(shown(page)).toContainText("login shell in /Users/you/code/api-server");
  await expect(shown(page)).not.toContainText("echo first");
  await expect.poll(() => focusInTerminal(page)).toBe(true);
  await page.keyboard.type("echo second\r");
  let c = await calls(page);
  const [a, b] = c.filter((x) => x.op === "start").map((x) => x.id);
  expect(c.filter((x) => x.op === "write" && x.id === b).map((x) => x.data).join("")).toBe("echo second\r");
  // the first tab kept its own output
  await page.getByTestId("termpanel-tab").first().getByRole("tab").click();
  await expect(shown(page)).toContainText("echo first");
  // close the second: its shell (only) is stopped
  await page.getByTestId("termpanel-tab-close").nth(1).click();
  await expect(page.getByTestId("termpanel-tab")).toHaveText(["web-app"]);
  await expect.poll(async () => (await calls(page)).filter((x) => x.op === "close").map((x) => x.id)).toEqual([b]);
  await page.getByTestId("termpanel-tab-close").click();
  await expect(panel(page)).toBeHidden();
  c = await calls(page);
  expect(c.filter((x) => x.op === "close").map((x) => x.id)).toEqual([b, a]);
  // Ctrl+` again: a fresh shell
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel-tab")).toHaveCount(1);
  await expect.poll(async () => (await calls(page)).filter((x) => x.op === "start")).toHaveLength(3);
});

test("the top edge drags to resize, and the height is kept on this computer", async ({ page }) => {
  await openAt(page);
  const before = (await panel(page).boundingBox())!;
  const edge = (await page.getByTestId("termpanel-resizer").boundingBox())!;
  const y = edge.y + edge.height / 2;
  await page.mouse.move(edge.x + edge.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(edge.x + edge.width / 2, y - 100, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => Math.round((await panel(page).boundingBox())!.height)).toBe(Math.round(before.height + 100));
  const saved = await page.evaluate(() => Number(localStorage.getItem("omher.termpanel.h")));
  expect(saved).toBe(Math.round(before.height + 100));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("Control+Backquote");
  await expect.poll(async () => Math.round((await panel(page).boundingBox())?.height ?? 0)).toBe(saved);
});
