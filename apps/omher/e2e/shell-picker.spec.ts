// Shell picker (kshell, mock host): the TERMINALS + menu's Shell row has a chevron (Shell ▸) when the computer has
// more than one shell; it lists them (the default marked) and picking one starts a Shell row whose shell start carries
// only that id. Arrows, Enter and Esc work in the list. The plain Shell row keeps the default (no id). Settings ›
// Terminal › Default shell picks the shell a plain Shell row runs and is kept; a row keeps its shell across a restart,
// and a split's "new Shell" uses the focused pane's shell. An id the computer no longer has opens the default shell and
// the row says so. One shell only: no chevron.
// Shots: OMHER_SHOTS=<dir> -> kshell-menu-{dark,light}.png, kshell-setting-{dark,light}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { mock, usePlatform } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";
const FOLDER = "/home/you/code/web-app";

type ShellCall = { op: string; id?: number; cwd?: string | null; shell?: string };
const shellStarts = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherShellCalls?: ShellCall[] }).__omherShellCalls ?? []).filter((c) => c.op === "start").map((c) => c.shell ?? null));
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const mac = (page: Page) => page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

async function open(page: Page, o: { theme?: "dark" | "light"; shells?: unknown[] } = {}) {
  await usePlatform(page);
  await page.addInitScript(
    ([folder, theme, shells]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.splits", "omher.termpanel.tabs", "__omherMockHistory", "omher.term"]) localStorage.removeItem(k);
        sessionStorage.setItem("__kept", "1");
      }
      if (theme) localStorage.setItem("omher.theme", theme as string);
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = folder;
      w.__omherMockAgents = ["claude", "codex"];
      if (shells) w.__omherMockShells = shells;
    },
    [FOLDER, o.theme ?? "", o.shells ?? null] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function plusMenu(page: Page) {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(page.getByTestId("session-agent-shell")).toBeVisible();
}

const openTerm = async (page: Page) => {
  await expect(page.getByTestId("terminal")).toBeVisible();
  const id = (await page.getByTestId("terminal").getAttribute("data-session"))!;
  await expect(term(page, id).locator(".xterm-rows")).toContainText("login shell in");
  return id;
};

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Shell ▸ lists this computer's shells, the default marked; picking zsh/fish sends only its id; the plain Shell sends none", async ({ page }) => {
  await open(page);
  await plusMenu(page);
  const more = page.getByTestId("session-shell-more");
  await expect(more).toBeVisible();
  await expect(page.getByTestId("session-shells")).toHaveCount(0);
  await more.click();
  const picks = page.getByTestId("session-shell-pick");
  await expect(picks).toHaveCount(3);
  await expect(picks).toHaveText([/^zsh\s*default$/, /^bash$/, /^fish$/]);
  await picks.filter({ hasText: "zsh" }).click();
  await openTerm(page);
  expect(await shellStarts(page)).toEqual(["unix:/bin/zsh"]);

  // keyboard: → on Shell opens the list, ↓ moves, Esc closes the list only, Enter picks
  await plusMenu(page);
  await page.getByTestId("session-agent-shell").focus();
  await page.keyboard.press("ArrowRight");
  await expect(picks).toHaveCount(3);
  await expect(picks.first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-shells")).toHaveCount(0);
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(more).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(picks.first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(picks.nth(2)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
  await expect.poll(() => shellStarts(page)).toEqual(["unix:/bin/zsh", "unix:/opt/homebrew/bin/fish"]);
  await expect(page.locator('[data-testid="terminal"]:visible .xterm-rows')).toContainText("fish login shell in");

  // the plain Shell row: today's default, no id
  await plusMenu(page);
  await page.getByTestId("session-agent-shell").click();
  await expect.poll(() => shellStarts(page)).toEqual(["unix:/bin/zsh", "unix:/opt/homebrew/bin/fish", null]);
});

test("one shell only: no chevron", async ({ page }) => {
  await open(page, { shells: [{ id: "unix:/bin/zsh", label: "zsh", path: "/bin/zsh", default: true }] });
  await plusMenu(page);
  await expect(page.getByTestId("session-shell-more")).toHaveCount(0);
});

test("Settings › Terminal › Default shell: kept, used by the plain Shell row; the row keeps its shell after a restart and a split's new Shell uses it", async ({ page }) => {
  await open(page);
  const m = await mac(page);
  await page.keyboard.press(m ? "Meta+," : "Control+,");
  await page.getByTestId("settings-tab-terminal").or(page.getByRole("button", { name: /^Terminal$/ })).first().click();
  const sel = page.getByTestId("term-default-shell");
  await expect(sel).toBeVisible();
  // the default is today's: the login shell, stored as nothing
  await expect(sel).toHaveValue("unix:/bin/zsh");
  await expect(sel.locator("option")).toHaveText(["zsh (default)", "bash", "fish"]);
  await sel.selectOption("unix:/bin/bash");
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").defaultShell)).toBe("unix:/bin/bash");
  await page.keyboard.press("Escape");

  // the plain Shell row now runs bash, and the menu marks bash as the default
  await plusMenu(page);
  await page.getByTestId("session-shell-more").click();
  await expect(page.getByTestId("session-shell-pick")).toHaveText([/^zsh$/, /^bash\s*default$/, /^fish$/]);
  await page.keyboard.press("Escape");
  await page.getByTestId("session-agent-shell").click();
  const a = await openTerm(page);
  expect(await shellStarts(page)).toEqual(["unix:/bin/bash"]);
  await expect(term(page, a).locator(".xterm-rows")).toContainText("bash login shell in");

  // a split's "new Shell in this folder" runs the focused pane's shell
  await term(page, a).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press(m ? "Meta+d" : "Control+Shift+D");
  await page.getByTestId("split-new-shell").click();
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await expect.poll(() => shellStarts(page)).toEqual(["unix:/bin/bash", "unix:/bin/bash"]);

  // the setting outlives a reload; the rows come back with their shell and Resume starts it again
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "{}").sessions?.map((s: { shell?: string }) => s.shell))).toEqual(["unix:/bin/bash", "unix:/bin/bash"]);
  await page.evaluate(() => {
    const r = JSON.parse(localStorage.getItem("omher.term") || "{}");
    localStorage.setItem("omher.term", JSON.stringify({ ...r, defaultShell: "" }));
  });
  await page.reload();
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  const paused = page.locator(`[data-testid="split-pane"][data-session="${a}"]`).getByTestId("session-paused").or(page.getByTestId("session-paused").first());
  await paused.getByRole("button").first().click();
  await expect.poll(() => shellStarts(page)).toEqual(["unix:/bin/bash"]);
});

test("a row whose shell is gone opens the default shell and says so", async ({ page }) => {
  await open(page);
  // made on a computer with Git Bash: this one does not have it
  const id = await page.evaluate((f) => (window as unknown as { __omherSessions: { startTerminal(a: string, c: string, s?: string): string } }).__omherSessions.startTerminal("shell", f, "gitbash"), FOLDER);
  await expect(term(page, id).locator(".xterm-rows")).toContainText("gitbash not found, opened the default shell");
  await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock) login shell in");
  expect(await shellStarts(page)).toEqual(["gitbash"]);
});

test("shots: light", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  await open(page, { theme: "light" });
  await plusMenu(page);
  await page.getByTestId("session-shell-more").click();
  await expect(page.getByTestId("session-shell-pick")).toHaveCount(3);
  await shot(page, "kshell-menu-light");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  const m = await mac(page);
  await page.keyboard.press(m ? "Meta+," : "Control+,");
  await page.getByTestId("settings-tab-terminal").or(page.getByRole("button", { name: /^Terminal$/ })).first().click();
  await page.getByTestId("term-default-shell-row").scrollIntoViewIfNeeded();
  await shot(page, "kshell-setting-light");
});

test("shots: dark menu and setting (theme forced)", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  await open(page, { theme: "dark" });
  await plusMenu(page);
  await page.getByTestId("session-shell-more").click();
  await expect(page.getByTestId("session-shell-pick")).toHaveCount(3);
  await shot(page, "kshell-menu-dark");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  const m = await mac(page);
  await page.keyboard.press(m ? "Meta+," : "Control+,");
  await page.getByTestId("settings-tab-terminal").or(page.getByRole("button", { name: /^Terminal$/ })).first().click();
  await page.getByTestId("term-default-shell-row").scrollIntoViewIfNeeded();
  await shot(page, "kshell-setting-dark");
});
