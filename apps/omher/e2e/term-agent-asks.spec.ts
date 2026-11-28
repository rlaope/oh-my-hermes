// A Claude Code or Codex in a TERMINALS row that stops on its permission dialog is an ask (mock host): the screen
// recorded from Claude Code 2.1.332 is printed into a Claude Code row's mock pty and the Needs-you strip shows it
// within a second, the Dock count goes up by one, its row's mark says it waits, and ⌘J/Ctrl+J opens that row with
// the keyboard in its terminal. Output that clears the dialog takes it away; the same words printed by a plain shell
// never count; with the setting off nothing shows. With OMHER_SHOTS=<dir> it writes dask-needs-{dark,light}.png.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { mock, openApp, usePlatform } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";
// the recording without the terminal queries Claude Code sends at start (device attributes, version, keyboard mode)
// and its focus reporting: the mock pty echoes what the terminal answers back onto the screen, where the real program
// reads it instead
const recorded = (name: string) =>
  readFileSync(new URL(`../src/sessions/term/fixtures/${name}`, import.meta.url))
    .toString("utf8")
    .replace(/\x1b\[c|\x1b\[>0q|\x1b\[\?u|\x1b\]7501;\?\x07|\x1b\[\?1004h/g, "");
const DIALOG = recorded("claude-bash-dialog.bin");
const ANSWERED = recorded("claude-bash-answered.bin");

type Sessions = { startTerminal(agent: string, cwd?: string): string | null; ptyOf(id: string): number | null };
const sessions = "__omherSessions";
const start = (page: Page, agent: string, cwd: string) => page.evaluate(([a, c, k]) => (window as unknown as Record<string, Sessions>)[k as string].startTerminal(a as string, c as string), [agent, cwd, sessions] as const);
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const badge = (page: Page) => page.evaluate(() => (window as unknown as { __omherBadge?: number }).__omherBadge ?? 0);
const mod = async (page: Page) => ((await page.evaluate(() => /Mac/.test(navigator.platform))) ? "Meta" : "Control");
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);

async function ptyOf(page: Page, id: string): Promise<number> {
  await expect.poll(() => page.evaluate(([i, k]) => (window as unknown as Record<string, Sessions>)[k as string].ptyOf(i as string), [id, sessions] as const)).not.toBeNull();
  return (await page.evaluate(([i, k]) => (window as unknown as Record<string, Sessions>)[k as string].ptyOf(i as string), [id, sessions] as const))!;
}

/** A Claude Code row (its own program, no shell under it) with its mock banner drawn. */
async function claudeRow(page: Page, cwd = "/home/you/code/web-app"): Promise<{ id: string; pty: number }> {
  const id = (await start(page, "claude", cwd))!;
  await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
  return { id, pty: await ptyOf(page, id) };
}

/** Clear the screen and draw the recorded dialog, as Claude Code does when it stops to ask. */
const showDialog = (page: Page, pty: number) => out(page, pty, `\x1b[2J\x1b[H${DIALOG}`);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a Claude Code row's permission dialog is an ask: strip, Dock count, row mark; ⌘J focuses its terminal; answered, it leaves", async ({ page }) => {
  await openApp(page);
  const before = await badge(page);
  const a = await claudeRow(page);
  // another row in front, so ⌘J has somewhere to go
  const b = await claudeRow(page, "/home/you/code/api-server");
  await expect(term(page, b.id)).toBeVisible();
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);

  const t0 = Date.now();
  await showDialog(page, a.pty);
  await expect(page.getByTestId("needs-strip")).toBeVisible({ timeout: 1000 });
  expect(Date.now() - t0).toBeLessThan(1000);
  await expect(page.getByTestId("needs-line")).toContainText("web-app · Claude Code");
  await expect.poll(() => badge(page)).toBe(before + 1);
  await expect(page.getByTestId(`session-${a.id}`).getByTestId("term-status")).toHaveAttribute("data-status", "bell");

  // the list: the agent's mark, Approve, the dialog's one line
  await page.getByTestId("needs-strip").click();
  const item = page.getByTestId("needs-item");
  await expect(item).toHaveCount(1);
  await expect(item.getByTestId("needs-tag")).toHaveText("Approve");
  await expect(item).toContainText("Bash command: touch probe.txt");
  await expect(item.getByTestId("session-face")).toBeVisible();
  await page.keyboard.press("Escape");

  // ⌘J (Ctrl+J off macOS) opens the asking row with the keyboard in its terminal
  await page.locator("body").click({ position: { x: 2, y: 2 } });
  await page.keyboard.press(`${await mod(page)}+KeyJ`);
  await expect(term(page, a.id)).toBeVisible();
  await expect.poll(() => page.evaluate((id) => !!document.activeElement?.closest(`[data-testid="terminal"][data-session="${id}"]`), a.id)).toBe(true);

  // answered: the screen after the dialog has no dialog, and the ask leaves
  await out(page, a.pty, `\x1b[2J\x1b[H${ANSWERED}`);
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
  await expect.poll(() => badge(page)).toBe(before);
  await expect(page.getByTestId(`session-${a.id}`).getByTestId("term-status")).not.toHaveAttribute("data-status", "bell");
});

test("Ctrl+J off macOS opens the asking row too", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "platform", { configurable: true, get: () => "Win32" }));
  await usePlatform(page);
  await openApp(page);
  const a = await claudeRow(page);
  const b = await claudeRow(page, "/home/you/code/api-server");
  await expect(term(page, b.id)).toBeVisible();
  await showDialog(page, a.pty);
  await expect(page.getByTestId("needs-strip")).toBeVisible();
  await page.locator("body").click({ position: { x: 2, y: 2 } });
  await page.keyboard.press("Control+KeyJ");
  await expect(term(page, a.id)).toBeVisible();
  await expect.poll(() => page.evaluate((id) => !!document.activeElement?.closest(`[data-testid="terminal"][data-session="${id}"]`), a.id)).toBe(true);
});

test("a plain shell printing the same dialog never counts", async ({ page }) => {
  await openApp(page);
  const id = (await start(page, "shell", "/home/you/code/web-app"))!;
  await expect(term(page, id).locator(".xterm-rows")).toContainText("login shell in");
  const pty = await ptyOf(page, id);
  await showDialog(page, pty);
  await expect(term(page, id).locator(".xterm-rows")).toContainText("Do you want to proceed?");
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
});

test("with the setting off nothing shows; turned off while one shows, it leaves", async ({ page }) => {
  await openApp(page, { term: { agentAsks: false } });
  const a = await claudeRow(page);
  await showDialog(page, a.pty);
  await expect(term(page, a.id).locator(".xterm-rows")).toContainText("Do you want to proceed?");
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);

  // on in Settings › Terminal: the next output reads it
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ agentAsks: true });
  });
  await showDialog(page, a.pty);
  await expect(page.getByTestId("needs-strip")).toBeVisible();
  // and off again: gone at once
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ agentAsks: false });
  });
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
});

test("the Settings › Terminal switch is on by default", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const row = page.getByTestId("term-agent-asks-row");
  await expect(row).toContainText("Show terminal agents' questions in Needs you");
  await expect(page.getByTestId("term-agent-asks").getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
});

for (const theme of ["dark", "light"] as const) {
  test(`shot: the Needs-you list with a terminal agent's ask (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "set OMHER_SHOTS to write screenshots");
    await page.setViewportSize({ width: 1280, height: 800 });
    await openApp(page, { theme });
    const a = await claudeRow(page);
    await showDialog(page, a.pty);
    await expect(page.getByTestId("needs-strip")).toBeVisible();
    await page.getByTestId("needs-strip").click();
    await expect(page.getByTestId("needs-item")).toHaveCount(1);
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, `dask-needs-${theme}.png`) });
  });
}
