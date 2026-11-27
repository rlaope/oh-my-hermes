// The text a terminal showed before omher restarted is written back above a "--- restored <time> ---" divider
// (term-restore.spec.ts). It is omher's text, not the new program's: a plain drag selects it even after the program
// turned mouse reporting on (as Antigravity CLI's full-window TUI does), while a press below the divider still goes to
// the program as a mouse report (mock host; engine-restored.ts).
import { expect, test, type Page } from "@playwright/test";
import { mock } from "./term-find-helpers";

const FOLDER = "/home/you/code/web-app";
const CONV = "01a1f29c-c5b1-7301-a199-2dd07ff4b024";

type Call = { op: string; agent?: string; resume?: string; key?: string; data?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const ptyOf = (page: Page, id: string) => page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id);
const out = (page: Page, pty: number, d: string) => page.evaluate(([p, x]) => (window as unknown as { __omherMockOut(id: number, d: string): boolean }).__omherMockOut(p as number, x as string), [pty, d] as const);

/** Where `needle` starts and ends on the open terminal's screen (page pixels), or null. */
const spot = (page: Page, needle: string) =>
  page.evaluate((n) => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; cols: number; rows: number; buffer: { active: { viewportY: number; getLine(i: number): { translateToString(t: boolean): string } | undefined } } }> };
    const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host);
    if (!term) return null;
    const screen = host!.querySelector(".xterm-screen")!.getBoundingClientRect();
    const cw = screen.width / term.cols;
    const ch = screen.height / term.rows;
    for (let r = 0; r < term.rows; r++) {
      const c = (term.buffer.active.getLine(term.buffer.active.viewportY + r)?.translateToString(true) ?? "").indexOf(n);
      if (c >= 0) return { x1: screen.left + c * cw + 2, x2: screen.left + (c + n.length) * cw - 2, y: screen.top + (r + 0.5) * ch };
    }
    return null;
  }, needle);

/** The middle of the row right under the divider (the new program's first row), or null. */
const below = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; cols: number; rows: number; buffer: { active: { viewportY: number; getLine(i: number): { translateToString(t: boolean): string } | undefined } } }> };
    const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host);
    if (!term) return null;
    const screen = host!.querySelector(".xterm-screen")!.getBoundingClientRect();
    for (let r = 0; r + 1 < term.rows; r++) {
      if (!/^--- .+ ---$/.test((term.buffer.active.getLine(term.buffer.active.viewportY + r)?.translateToString(true) ?? "").trim())) continue;
      return { x: screen.left + screen.width / 4, y: screen.top + (r + 1.5) * (screen.height / term.rows) };
    }
    return null;
  });

const selected = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; getSelection(): string }> };
    return [...w.__omherTerms].find((t) => t.element === host)?.getSelection() ?? "";
  });

async function drag(page: Page, needle: string) {
  await expect.poll(() => spot(page, needle)).not.toBeNull();
  const p = (await spot(page, needle))!;
  await page.mouse.move(p.x1, p.y);
  await page.mouse.down();
  await page.mouse.move((p.x1 + p.x2) / 2, p.y, { steps: 4 });
  await page.mouse.move(p.x2, p.y, { steps: 4 });
  await page.mouse.up();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("restored text above the divider selects with a plain drag while the program has the mouse; below it the program gets the press", async ({ page }) => {
  await page.addInitScript((folder) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "__omherMockHistory", "omher.term"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = folder;
    w.__omherMockAgents = ["claude", "codex", "omh", "agy"];
  }, FOLDER);
  await page.goto("/");
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-agy").click();
  await expect(page.locator("[data-testid=terminal] .xterm-rows")).toContainText("(mock)");
  const id = (await page.getByTestId("terminal").getAttribute("data-session"))!;
  const pty = (await ptyOf(page, id))!;
  // what it showed before the restart, and the conversation its Antigravity is on
  await out(page, pty, "kept-before-the-restart\r\n");
  await page.evaluate(([p, c]) => void (((window as unknown as { __omherMockAgyOwn?: Record<number, string> }).__omherMockAgyOwn ??= {})[p as number] = c as string), [pty, CONV] as const);
  await expect.poll(async () => JSON.parse((await page.evaluate(() => localStorage.getItem("omher.resume"))) || "null")?.sessions?.[0]?.agentSession, { timeout: 15_000 }).toBe(CONV);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await expect.poll(async () => (await calls(page)).some((c) => c.op === "history.save" && c.key === id && !!c.data?.includes("kept-before-the-restart"))).toBe(true);

  await page.reload();
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "start")).toEqual([expect.objectContaining({ agent: "agy", resume: CONV })]);
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.locator("[data-testid=terminal] .xterm-rows")).toContainText(/--- restored .+ ---/);
  await expect(page.locator("[data-testid=terminal] .xterm-rows")).toContainText("(mock)");
  // the new program turns mouse reporting on (press, drag and SGR reports), as a full-window TUI does
  const now = (await ptyOf(page, id))!;
  await out(page, now, "\x1b[?1000h\x1b[?1002h\x1b[?1006hfresh-program-line\r\n");
  await expect(page.locator("[data-testid=terminal] .xterm-rows")).toContainText("fresh-program-line");
  const writes = async () => (await calls(page)).filter((c) => c.op === "write").map((c) => c.data ?? "").join("");

  // a plain drag over the restored line selects it, and nothing of it reaches the program
  const before = await writes();
  await drag(page, "kept-before-the-restart");
  await expect.poll(() => selected(page)).toBe("kept-before-the-restart");
  await page.waitForTimeout(200);
  expect((await writes()).slice(before.length)).not.toContain("\x1b[<");

  // the row right under the divider is the new program's first row: a press there is the program's
  await page.mouse.click(5, 5);
  const first = (await below(page))!;
  const atFirst = await writes();
  await page.mouse.click(first.x, first.y);
  await expect.poll(async () => (await writes()).slice(atFirst.length)).toContain("\x1b[<0;");

  // below the divider the press is the program's: a mouse report goes out, and no selection is made
  await page.mouse.click(5, 5);
  const p = (await spot(page, "fresh-program-line"))!;
  const mid = await writes();
  await page.mouse.move(p.x1, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x2, p.y, { steps: 4 });
  await page.mouse.up();
  await expect.poll(async () => (await writes()).slice(mid.length)).toContain("\x1b[<0;");
  expect(await selected(page)).toBe("");
});
