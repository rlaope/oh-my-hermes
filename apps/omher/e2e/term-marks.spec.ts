// What a shell or CLI says of itself through its own escapes (src/sessions/term/engine-marks.ts), on the mock host
// with bytes fed as the program's output (`__omherMockOut`):
//   1. OSC 133 prompt marks: four commands (three end 0, one ends 1) and a fifth prompt; Cmd+Up moves the view to each
//      earlier prompt in turn, Cmd+Down / Cmd+PageDown back; each prompt has a gutter mark, the failed one red;
//   2. a terminal that sent no marks: Cmd+Up moves nothing (as before);
//   3. OSC 7: `file:///tmp/x%20y` renames the bottom panel's tab to "x y"; a TERMINALS row shows that folder on its
//      second line; another computer's folder, a relative path or a non-file address changes neither; this computer's
//      own name (the mock shell's start reply says `mybox.local`) counts, with and without `.local`;
//   4. OSC 9;4: `9;4;3` keeps the row working while nothing prints; `9;4;0` while the person looks at another session
//      marks the row as the bell does (and raises no notification); done without working first marks nothing.
// Chromium (Playwright's headless shell); nothing here ran in the Tauri window.
import { expect, test, type Page } from "@playwright/test";
import { mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

const OSC = (body: string) => `\x1b]${body}\x07`;

/** The pty session `id`'s terminal runs on. */
const ptyOf = (page: Page, id: string) =>
  page.evaluate((sid) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(sid), id);

/** Print `text` as program `pty`'s output, and wait until the shown terminal has parsed it. */
async function out(page: Page, pty: number, text: string) {
  const ok = await page.evaluate(([p, d]) => (window as unknown as { __omherMockOut(id: number, d: string): boolean }).__omherMockOut(p as number, d as string), [pty, text] as const);
  expect(ok).toBe(true);
  await page.evaluate(async () => {
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; write(d: string, cb: () => void): void }> };
    for (const t of w.__omherTerms ?? []) if (t.element?.isConnected) await new Promise<void>((r) => t.write("", r));
  });
}

type View = { top: number; base: number; rows: number; lines: string[] };
/** The shown session terminal's view top, scrollback base, rows and every buffer line. */
const view = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; rows: number; buffer: { active: { viewportY: number; baseY: number; length: number; getLine(i: number): { translateToString(t: boolean): string } | undefined } } }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(w.__omherTerms ?? [])].find((x) => x.element === host);
    if (!t) throw new Error("no terminal");
    const b = t.buffer.active;
    const lines: string[] = [];
    for (let i = 0; i < b.length; i++) lines.push(b.getLine(i)?.translateToString(true) ?? "");
    return { top: b.viewportY, base: b.baseY, rows: t.rows, lines } as View;
  });
const lineOf = (v: View, needle: string) => v.lines.findIndex((l) => l.startsWith(needle));

/** One shell round: prompt `name`, command, `n` lines of output, finished with `code`. */
const round = (name: string, n: number, code: number) =>
  `${OSC("133;A")}${name}$ ${OSC("133;B")}run ${name}\r\n${OSC("133;C")}${Array.from({ length: n }, (_, i) => `${name} output ${i}\r\n`).join("")}${OSC(`133;D;${code}`)}`;

const focusTerm = (page: Page) => page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();

test("OSC 133: Cmd+Up and Cmd+Down move between prompts, and each prompt has a gutter mark, red when its command failed", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  const pty = (await ptyOf(page, id))!;
  await out(page, pty, `\r\n${round("p1", 60, 0)}${round("p2", 60, 1)}${round("p3", 60, 0)}${round("p4", 60, 0)}${OSC("133;A")}p5$ ${OSC("133;B")}`);
  const v = await view(page);
  const at = ["p1$", "p2$", "p3$", "p4$", "p5$"].map((p) => lineOf(v, p));
  expect(at.every((l) => l >= 0)).toBe(true);
  expect(v.top).toBe(v.base); // at the bottom, the live prompt in view
  expect(at[3]).toBeLessThan(v.base); // every earlier prompt can come to the top of the view
  await focusTerm(page);
  const writesBefore = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).filter((c) => c.op === "write").length);
  for (const want of [at[3], at[2], at[1], at[0], at[0]]) {
    await page.keyboard.press("Meta+ArrowUp");
    await expect.poll(async () => (await view(page)).top).toBe(want);
  }
  await page.keyboard.press("Meta+ArrowDown");
  await expect.poll(async () => (await view(page)).top).toBe(at[1]);
  // on p2 (its command ended 1): the mark at the top row is red, the next one in view is not
  // (a mark whose line is out of view stays in the page, hidden)
  const marks = page.locator('[data-testid="terminal"] .xterm-decoration.term-mark:visible');
  await expect(marks.first()).toHaveClass(/\berr\b/);
  const screenTop = await page.locator('[data-testid="terminal"] .xterm-screen').evaluate((e) => e.getBoundingClientRect().top);
  const errTop = await page.locator('[data-testid="terminal"] .term-mark.err:visible').evaluate((e) => e.getBoundingClientRect().top);
  expect(Math.abs(errTop - screenTop)).toBeLessThan(2);
  await page.keyboard.press("Meta+PageDown");
  await expect.poll(async () => (await view(page)).top).toBe(at[2]);
  await expect(marks.first()).not.toHaveClass(/\berr\b/);
  await expect(page.locator('[data-testid="terminal"] .term-mark.err:visible')).toHaveCount(0);
  // past the last prompt: back to the bottom
  await page.keyboard.press("Meta+ArrowDown");
  await page.keyboard.press("Meta+ArrowDown");
  await expect.poll(async () => (await view(page)).top).toBe(v.base);
  // the keys reached the jump only, never the program
  const writesAfter = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).filter((c) => c.op === "write").length);
  expect(writesAfter).toBe(writesBefore);
});

test("OSC 133: a terminal that sent no marks keeps Cmd+Up as it was (the view does not move)", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  const pty = (await ptyOf(page, id))!;
  await out(page, pty, Array.from({ length: 120 }, (_, i) => `plain line ${i}\r\n`).join(""));
  const v = await view(page);
  expect(v.base).toBeGreaterThan(0);
  await focusTerm(page);
  await page.keyboard.press("Meta+ArrowUp");
  await page.waitForTimeout(150);
  expect((await view(page)).top).toBe(v.base);
  await expect(page.locator('[data-testid="terminal"] .term-mark')).toHaveCount(0);
});

test("OSC 7: the bottom panel's tab follows the folder its shell reports, from this computer only", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("login shell in");
  const shellPty = await page.evaluate(() => (window as unknown as { __omherShellCalls: { op: string; id: number }[] }).__omherShellCalls.filter((c) => c.op === "start").at(-1)!.id);
  const tab = page.getByTestId("termpanel-tab").locator(".termpanel-tab-name");
  // named by the folder it started in (the mock's home)
  await expect(tab).toHaveText("you");
  await out(page, shellPty, OSC("7;file:///tmp/x%20y"));
  await expect(tab).toHaveText("x y");
  await expect(tab).toHaveAttribute("title", "/tmp/x y");
  for (const bad of ["7;file://build-box/srv/other", "7;http://localhost/tmp/web", "7;file:relative/dir", "7;file:///tmp/a%0Ab"]) await out(page, shellPty, OSC(bad));
  await page.waitForTimeout(100);
  await expect(tab).toHaveText("x y");
  await out(page, shellPty, OSC("7;file://localhost/home/you/code/api-server"));
  await expect(tab).toHaveText("api-server");
});

test("OSC 7: the reported folder only names the panel tab; after a restart the tab starts again where its shell started", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  const shown = page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');
  await expect(shown).toContainText("login shell in");
  const starts = () => page.evaluate(() => (window as unknown as { __omherShellCalls: { op: string; id: number; at: string }[] }).__omherShellCalls.filter((c) => c.op === "start"));
  const first = (await starts())[0];
  const tab = page.getByTestId("termpanel-tab").locator(".termpanel-tab-name");
  await out(page, first.id, OSC("7;file://localhost/home/you/code/api-server"));
  await expect(tab).toHaveText("api-server");
  // the kept tab names the folder the shell started in, never the reported one
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.termpanel.tabs") || "{}").tabs?.[0]?.cwd)).toBe(first.at);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(300);
  if (!(await page.getByTestId("termpanel").isVisible())) await page.keyboard.press("Control+Backquote");
  await expect(shown).toContainText("login shell in");
  expect((await starts())[0].at).toBe(first.at);
});

test("OSC 7: a folder from this computer's own name counts, the name the shell start reported", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("login shell in");
  const shellPty = await page.evaluate(() => (window as unknown as { __omherShellCalls: { op: string; id: number }[] }).__omherShellCalls.filter((c) => c.op === "start").at(-1)!.id);
  const tab = page.getByTestId("termpanel-tab").locator(".termpanel-tab-name");
  await expect(tab).toHaveText("you");
  // the mock computer is "mybox.local": its short name, as zsh's $HOST gives it, counts
  await out(page, shellPty, OSC("7;file://mybox/tmp/x%20y"));
  await expect(tab).toHaveText("x y");
  await out(page, shellPty, OSC("7;file://MyBox.local/tmp/full"));
  await expect(tab).toHaveText("full");
  // another computer's name still does not
  await out(page, shellPty, OSC("7;file://otherbox/tmp/elsewhere"));
  await page.waitForTimeout(100);
  await expect(tab).toHaveText("full");
});

test("OSC 7: a TERMINALS row's folder line follows the folder its shell reports, from this computer only", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  const pty = (await ptyOf(page, id))!;
  const row = page.getByTestId(`session-${id}`);
  await expect(row.getByTestId("term-cwd")).toHaveCount(0);
  await out(page, pty, OSC("7;file:///tmp/x%20y"));
  await expect(row.getByTestId("term-cwd")).toHaveText("x y");
  await expect(row.getByTestId("term-cwd")).toHaveAttribute("title", "/tmp/x y");
  await out(page, pty, OSC("7;file://elsewhere.example/etc"));
  await page.waitForTimeout(100);
  await expect(row.getByTestId("term-cwd")).toHaveText("x y");
});

test("OSC 7: a TERMINALS row takes this computer's own name before the bottom panel ever opened", async ({ page }) => {
  await openApp(page);
  const id = await newTerminal(page);
  const pty = (await ptyOf(page, id))!;
  const row = page.getByTestId(`session-${id}`);
  // the mock computer is "mybox.local"; no panel shell has started in this page load
  expect(await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string }[] }).__omherShellCalls ?? []).filter((c) => c.op === "start").length)).toBe(0);
  await out(page, pty, OSC("7;file://mybox/home/you/code/api-server"));
  await expect(row.getByTestId("term-cwd")).toHaveText("api-server");
});

test("OSC 9;4: progress keeps the row working, and done while the person looks elsewhere marks it as the bell does", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __notes: string[]; Notification: unknown };
    w.__notes = [];
    w.Notification = class {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick = null;
      constructor(title: string) {
        w.__notes.push(title);
      }
      close() {}
    };
  });
  await openApp(page);
  const a = await newTerminal(page);
  const ptyA = (await ptyOf(page, a))!;
  const row = page.getByTestId(`session-${a}`);
  // done with no working before it, while looked at: nothing
  await out(page, ptyA, OSC("9;4;0"));
  // working (indeterminate): the spinner holds past the output window (BUSY_MS, 2 s) with nothing printed
  await out(page, ptyA, OSC("9;4;3"));
  await expect(row).toHaveAttribute("data-term-status", "busy");
  await page.waitForTimeout(2600);
  await expect(row).toHaveAttribute("data-term-status", "busy");
  // the person goes to another session; the program reports done
  const b = await newTerminal(page);
  expect(b).not.toBe(a);
  await out(page, ptyA, OSC("9;4;1;80"));
  await out(page, ptyA, OSC("9;4;0"));
  await expect(row).toHaveAttribute("data-term-status", "bell");
  expect(await page.evaluate(() => (window as unknown as { __notes: string[] }).__notes)).toEqual([]);
  // the escape's text is not on the row
  await expect(row).not.toContainText("9;4");
  // back to it: seen
  await row.locator(".ss-open").click();
  await expect(row).not.toHaveAttribute("data-term-status", "bell");
  // done while looked at, after working: no mark
  await out(page, ptyA, OSC("9;4;1;10"));
  await out(page, ptyA, OSC("9;4;0"));
  await page.waitForTimeout(100);
  await expect(row).not.toHaveAttribute("data-term-status", "bell");
});
