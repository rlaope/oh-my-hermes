// The right panel on TERMINALS follows the focused pane and says what runs in it. Two Shell rows with Claude Code typed
// in them (the shell reports `claude` in front and names its conversation) are read as Claude Code: the conversation's
// own title and model (cli.title), how long it has run, its live state and the subagents of its own record (runs.cli).
// Focusing the other pane (its box in the split map, a click in it, the keyboard) switches the panel without closing
// it. A plain shell shows its folder, program and running time, and nothing it was not told.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { mock, openApp, platformIsMac } from "./term-find-helpers";
import { dragRowOnto, openFromSidebar } from "./split-drag-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";
const A = "aaaaaaaa-1111-4222-8333-444444444444";
const B = "bbbbbbbb-1111-4222-8333-444444444444";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const details = (page: Page) => page.getByTestId("session-details");

async function shell(page: Page, cwd: string): Promise<string> {
  const id = await start(page, cwd);
  await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
  return id;
}

/** The person types `claude` in shell `id`: the shell reports it in front and, asked, names conversation `sid`. */
async function claudeIn(page: Page, id: string, sid: string) {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  const pty = (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
  await page.evaluate(([p, c]) => void (((window as unknown as { __omherMockFgOwn?: Record<number, string> }).__omherMockFgOwn ??= {})[p as number] = c as string), [pty, sid] as const);
  await page.evaluate((p) => (window as unknown as { __omherEmitSessionFg(x: { id: number; agent: string }): void }).__omherEmitSessionFg({ id: p, agent: "claude" }), pty);
}

/** Two Claude Code shells side by side (b focused), each with its own conversation on record. */
async function twoClaudes(page: Page): Promise<[string, string]> {
  const started = Math.floor(Date.now() / 1000) - 3 * 3600 - 5 * 60;
  await mock("mock.cliTitle", { agent: "claude", session: A, title: "Fix the login redirect", model: "claude-opus-5-5", started });
  await mock("mock.cliTitle", { agent: "claude", session: B, title: "Speed up the test suite", model: "claude-fable-5-2", started: started + 3600 });
  await mock("mock.shellRun", { session: B, cwd: "/home/you/code/api-server", title: "Claude Code session", running: true });
  const a = await shell(page, "/home/you/code/web-app");
  const b = await shell(page, "/home/you/code/api-server");
  await claudeIn(page, a, A);
  await claudeIn(page, b, B);
  await openFromSidebar(page, a);
  await dragRowOnto(page, b, a, "right");
  await expect(page.locator(`[data-testid="split-pane"][data-session="${b}"]`)).toHaveAttribute("data-focused", "true");
  return [a, b];
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("on a split of two Claude Code shells the header's panel button opens what the focused one runs; a focus switch follows it", async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);
  const [a, b] = await twoClaudes(page);
  await page.getByTestId("panel-button").click();
  // the split map stays on top, the focused box marked
  await expect(page.getByTestId("split-map-box")).toHaveCount(2);
  await expect(page.locator(`[data-testid="split-map-box"][data-session="${b}"]`)).toHaveAttribute("data-focused", "true");
  // b: Claude Code, its conversation's own title and model, how long it has run, and its subagents as a graph
  await expect(details(page)).toHaveAttribute("data-session", b);
  await expect(details(page)).toHaveAttribute("data-harness", "claude");
  await expect(page.getByTestId("session-details-harness")).toHaveText("Claude Code");
  // the conversation id is asked 5 s after Claude Code comes to the front
  await expect(page.getByTestId("session-details-title")).toHaveText("Speed up the test suite", { timeout: 15_000 });
  await expect(page.getByTestId("session-details-model")).toHaveText("Fable 5.2");
  await expect(page.getByTestId("session-details-time")).toHaveText(/^2h \d+m$/);
  await expect(page.getByTestId("session-details-program")).toHaveText("claude");
  await expect(page.getByTestId("session-details-folder")).toHaveText("~/code/api-server");
  await expect(page.getByTestId("session-details-state")).toBeVisible();
  const box = page.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", `claude:${B}`);
  await expect(box.locator("[data-testid=run-node]")).toHaveCount(2);
  await expect(box.getByTestId("node-title")).toHaveText(["Map the API routes", "Check the tests"]);
  // nothing the source did not give: no percentages, no token counts
  await expect(details(page)).not.toContainText("%");
  await expect(details(page)).not.toContainText(/token/i);

  // the split map's other box: the panel stays open and follows a
  await page.locator(`[data-testid="split-map-box"][data-session="${a}"]`).click();
  await expect(details(page)).toHaveAttribute("data-session", a);
  await expect(page.getByTestId("session-details-title")).toHaveText("Fix the login redirect");
  await expect(page.getByTestId("session-details-model")).toHaveText("Opus 5.5");
  await expect(page.getByTestId("session-details-time")).toHaveText(/^3h \d+m$/);
  // a's conversation keeps no subagent record: said so, never b's graph
  await expect(page.getByTestId("run-graph-box")).toHaveCount(0);
  await expect(page.getByTestId("plans-empty")).toHaveText("Claude Code has no subagents in this conversation yet.");

  // the keyboard's next pane: back to b, the panel still open
  const mac = await platformIsMac(page);
  await term(page, a).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press(mac ? "Meta+BracketRight" : "Control+Tab");
  await expect(details(page)).toHaveAttribute("data-session", b);
  await expect(page.getByTestId("run-graph-box")).toHaveAttribute("data-run", `claude:${B}`);
  // a click in a's pane
  await term(page, a).click();
  await expect(details(page)).toHaveAttribute("data-session", a);
  await expect(page.getByTestId("details-panel")).toBeVisible();
});

test("a plain shell's panel shows its folder, program and running time, and no harness, model or title", async ({ page }) => {
  await openApp(page);
  const id = await shell(page, "/home/you/code/notes");
  await openFromSidebar(page, id);
  await page.getByTestId("panel-button").click();
  await expect(details(page)).toHaveAttribute("data-harness", "shell");
  await expect(page.getByTestId("session-details-harness")).toHaveText("Shell");
  await expect(page.getByTestId("session-details-folder")).toHaveText("~/code/notes");
  await expect(page.getByTestId("session-details-program")).not.toBeEmpty();
  await expect(page.getByTestId("session-details-time")).toHaveText(/^\d+s$/);
  await expect(page.getByTestId("session-details-model")).toHaveCount(0);
  await expect(page.getByTestId("session-details-title")).toHaveCount(0);
  await expect(page.getByTestId("split-map")).toHaveCount(0);
  await expect(page.getByTestId("plans-empty")).toHaveText("No subagents in this session yet.");
});

for (const theme of ["dark", "light"] as const) {
  test(`shots: the terminal panel follows the focused Claude Code pane, and a plain shell (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1440, height: 860 });
    await openApp(page, { theme });
    await twoClaudes(page);
    await page.getByTestId("panel-button").click();
    await expect(page.getByTestId("session-details-title")).toHaveText("Speed up the test suite", { timeout: 15_000 });
    await expect(page.locator("[data-testid=run-graph-box] [data-testid=run-node]")).toHaveCount(2);
    await page.mouse.move(700, 600);
    await page.waitForTimeout(400);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `dside-split-claude-${theme}.png`), animations: "disabled" });
    const plain = await shell(page, "/home/you/code/notes");
    await openFromSidebar(page, plain);
    await expect(details(page)).toHaveAttribute("data-harness", "shell");
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(SHOTS, `dside-plain-shell-${theme}.png`), animations: "disabled" });
  });
}
