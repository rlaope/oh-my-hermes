// A terminal that is not on the page draws nothing (src/sessions/term/engine-hidden.ts), and loses nothing:
//   1. four SESSIONS terminals, three hidden ones printing scrolling lines and a spinner: the hidden ones render no
//      rows of any kind (xterm's row renders and its selection redraws are counted on the renderer), the shown one
//      still does;
//   2. a hidden one, shown again: its buffer equals a never-hidden twin's that took the same bytes (every line and
//      the cursor), and the rows it draws are that buffer's screen;
//   3. a selection made before it was hidden is drawn again when it is shown, where the text it covers now is;
//   4. a hidden terminal flooded with more than 2 MiB keeps acknowledging every byte;
//   5. the bell and an OSC 9 message from a hidden terminal still reach its TERMINALS row;
//   6. the bottom panel's terminal, hidden, draws nothing either and shows what its shell printed meanwhile;
//   7. with the GPU renderer on, a hidden terminal draws nothing and takes a live GPU context again when shown.
// Chromium (Playwright's headless shell) on the mock host; nothing here ran in the Tauri window.
import { expect, test, type Page } from "@playwright/test";
import { mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Flow = { op: "feed" | "ack"; id: number; bytes: number };
type Call = { op: string; id?: number };
const flow = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionFlow?: Flow[] }).__omherSessionFlow ?? []);
const sum = (steps: Flow[], op: Flow["op"], id: number) => steps.filter((f) => f.op === op && f.id === id).reduce((n, f) => n + f.bytes, 0);
const MIB = 1024 * 1024;
/** FLOW_HIGH in src-tauri/src/sessions.rs: the shell stops reading a program this far ahead of the page. */
const FLOW_HIGH = 2 * MIB;

/** Show session `id` (its TERMINALS row). */
const show = async (page: Page, id: string) => {
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
};

/** A new terminal session, its xterm tagged with the session id so a hidden one can be found again. `gpu`: the
 *  terminal draws on a canvas, so the program's banner is read from its buffer, not its rows. */
async function tagged(page: Page, gpu = false): Promise<string> {
  let id: string;
  if (!gpu) id = await newTerminal(page);
  else {
    const term = page.getByTestId("terminal");
    const before = (await term.count()) ? await term.getAttribute("data-session") : null;
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await page.getByTestId("session-agent-claude").click();
    await expect(term).toHaveAttribute("data-session", /./);
    if (before) await expect(term).not.toHaveAttribute("data-session", before);
    id = (await term.getAttribute("data-session")) as string;
  }
  await page.evaluate((sid) => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; __sid?: string }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...w.__omherTerms].find((x) => x.element === host);
    if (!t) throw new Error("no terminal");
    t.__sid = sid;
  }, id);
  await expect.poll(async () => (await screenOf(page, id)).lines.join("\n")).toContain("(mock)");
  return id;
}

/** Counts, from now, every row render and every selection redraw that reaches each terminal's current renderer
 *  (the DOM renderer's `handleSelectionChanged` renders every row, so it is counted in `rows` too). */
const count = (page: Page) =>
  page.evaluate(() => {
    type R = { renderRows(a: number, b: number): void; handleSelectionChanged(...a: unknown[]): void; __c?: { rows: number; sel: number } };
    type T = { __c?: { rows: number; sel: number }; _core: { _renderService: { _renderer: { value?: R } } } };
    for (const t of (window as unknown as { __omherTerms: Set<T> }).__omherTerms) {
      const r = t._core._renderService._renderer.value;
      if (!r) continue;
      if (!r.__c) {
        const c = (r.__c = { rows: 0, sel: 0 });
        const rows = r.renderRows.bind(r);
        const sel = r.handleSelectionChanged.bind(r);
        r.renderRows = (a, b) => (c.rows++, rows(a, b));
        r.handleSelectionChanged = (...a) => (c.sel++, sel(...a));
      }
      r.__c.rows = 0;
      r.__c.sel = 0;
      t.__c = r.__c;
    }
  });
/** The counts by session id (`panel` for the bottom panel's terminal). */
const counts = (page: Page) =>
  page.evaluate(() => {
    type T = { __sid?: string; __c?: { rows: number; sel: number }; element?: HTMLElement };
    const out: Record<string, { rows: number; sel: number }> = {};
    for (const t of (window as unknown as { __omherTerms: Set<T> }).__omherTerms) {
      const key = t.__sid ?? (t.element?.closest('[data-testid="termpanel-terminal"]') ? "panel" : "?");
      if (t.__c) out[key] = { ...t.__c };
    }
    return out;
  });

/** Every 100 ms for `ms`, each of `ids` prints what an agent does while it works: a spinner line rewritten in place,
 *  and every fifth tick a new line that scrolls the screen. The same bytes, in the same order, to each. */
const stream = (page: Page, ids: string[], ms: number) =>
  page.evaluate(
    async ([sids, dur]) => {
      const w = window as unknown as { __omherSessions: { ptyOf(id: string): number | null }; __omherMockOut(p: number, d: string): boolean };
      const spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
      const ptys = (sids as string[]).map((id) => w.__omherSessions.ptyOf(id)!);
      for (let n = 1; n <= (dur as number) / 100; n++) {
        let out = `\x1b[2K\r\x1b[33m${spin[n % 10]}\x1b[0m Working… (${n}s · ${n * 37} tokens · esc to interrupt)`;
        if (n % 5 === 0) out = `\x1b[2K\r  ⎿  Read src/file-${n}.ts (120 lines)\r\n` + out;
        for (const p of ptys) if (!w.__omherMockOut(p, out)) throw new Error(`no pty ${p}`);
        await new Promise((r) => setTimeout(r, 100));
      }
    },
    [ids, ms] as const,
  );

/** A terminal's whole buffer as text, its cursor, and (when it is on the page) the screen its rows draw. */
const screenOf = (page: Page, sid: string) =>
  page.evaluate(async (want) => {
    type Buf = { length: number; cursorX: number; cursorY: number; baseY: number; viewportY: number; getLine(i: number): { translateToString(t: boolean): string } | undefined };
    type T = { __sid?: string; rows: number; element?: HTMLElement; write(d: string, cb: () => void): void; buffer: { active: Buf } };
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.__sid === want);
    if (!t) throw new Error(`no terminal ${want}`);
    await new Promise<void>((r) => t.write("", r));
    const b = t.buffer.active;
    const lines: string[] = [];
    for (let i = 0; i < b.length; i++) lines.push(b.getLine(i)?.translateToString(true) ?? "");
    const view = lines.slice(b.viewportY, b.viewportY + t.rows);
    const drawn = t.element?.isConnected ? [...t.element.querySelectorAll(".xterm-rows > div")].map((d) => (d.textContent ?? "").replace(/\u00a0/g, " ").trimEnd()) : null;
    return { lines, cursor: { x: b.cursorX, y: b.cursorY, baseY: b.baseY }, view, drawn };
  }, sid);

test("hidden terminals printing a spinner and scrolling lines render no rows; the shown one does", async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);
  const ids = [await tagged(page), await tagged(page), await tagged(page), await tagged(page)];
  const [a, b, c, d] = ids;
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", d);
  await page.waitForTimeout(300); // what showing and hiding drew has been drawn
  await count(page);
  await stream(page, ids, 2000);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const n = await counts(page);
  for (const id of [a, b, c]) expect(n[id], `hidden ${id}`).toEqual({ rows: 0, sel: 0 });
  expect(n[d].rows, "the shown terminal").toBeGreaterThan(0);

  // 2. each hidden one, shown again, holds what the never-hidden one holds, and draws it
  const twin = await screenOf(page, d);
  expect(twin.lines.join("\n")).toContain("Read src/file-20.ts");
  for (const id of [a, b, c]) {
    await show(page, id);
    const s = await screenOf(page, id);
    expect(s.lines).toEqual(twin.lines);
    expect(s.cursor).toEqual(twin.cursor);
    await expect.poll(async () => (await screenOf(page, id)).drawn).toEqual(s.view);
  }
});

test("a selection made before hiding is drawn again when shown, over the text it covers now", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  await stream(page, [a], 1000);
  // select the line printed last ("Read src/file-10.ts") while the terminal is on the page
  const picked = await page.evaluate(() => {
    type T = { __sid?: string; select(c: number, r: number, l: number): void; getSelection(): string; buffer: { active: { baseY: number; cursorY: number } } };
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.__sid)!;
    const row = t.buffer.active.baseY + t.buffer.active.cursorY - 1;
    t.select(2, row, 26);
    return t.getSelection();
  });
  expect(picked).toContain("Read src/file-10.ts");
  const selDivs = () => page.locator('[data-testid="terminal"] .xterm-selection div');
  await expect(selDivs()).not.toHaveCount(0);

  // hidden: another session is shown and the first one's output scrolls its screen by two lines
  const b = await tagged(page);
  await page.waitForTimeout(300);
  await count(page);
  await stream(page, [a, b], 1000);
  expect((await counts(page))[a]).toEqual({ rows: 0, sel: 0 });

  await show(page, a);
  const want = await page.evaluate(() => {
    type T = { __sid?: string; getSelection(): string; getSelectionPosition(): { start: { y: number } } | undefined; buffer: { active: { viewportY: number } } };
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.__sid && x.getSelection())!;
    return { text: t.getSelection(), row: t.getSelectionPosition()!.start.y - t.buffer.active.viewportY };
  });
  expect(want.text).toBe(picked);
  // the selection is drawn on the row its text is on now
  await expect(selDivs()).not.toHaveCount(0);
  const drawnRow = await page.evaluate(() => {
    const sel = document.querySelector<HTMLElement>('[data-testid="terminal"] .xterm-selection div')!;
    const row = document.querySelector<HTMLElement>('[data-testid="terminal"] .xterm-rows > div')!;
    return Math.round(parseFloat(sel.style.top) / row.getBoundingClientRect().height);
  });
  expect(drawnRow).toBe(want.row);
  const onRow = await page.evaluate((r) => document.querySelectorAll('[data-testid="terminal"] .xterm-rows > div')[r]?.textContent ?? "", want.row);
  expect(onRow).toContain("Read src/file-10.ts");
});

test("a hidden terminal flooded with more than 2 MiB keeps acknowledging every byte, and draws nothing meanwhile", async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);
  const a = await tagged(page);
  const calls = await page.evaluate(() => (window as unknown as { __omherSessionCalls: Call[] }).__omherSessionCalls);
  const idA = calls.filter((c) => c.op === "start").at(-1)!.id!;
  await tagged(page);
  await page.waitForTimeout(200);
  await count(page);
  expect((await flow(page)).filter((f) => f.id === idA && f.bytes === 64 * 1024)).toHaveLength(0);
  // the flood starts only now, once the draws are counted (a timer started before could fire before the count on a
  // busy machine): 3 MiB as 48 messages of 64 KiB, the mock's own `flood` message, from its pty
  await page.evaluate((p) => {
    const w = window as unknown as { __omherMockOut(p: number, d: string): boolean };
    const message = `${"build output ".repeat(5).slice(0, 62)}\r\n`.repeat(1024);
    for (let i = 0; i < 48; i++) if (!w.__omherMockOut(p, message)) throw new Error(`no pty ${p}`);
  }, idA);
  await expect.poll(async () => sum(await flow(page), "feed", idA), { timeout: 20_000 }).toBeGreaterThanOrEqual(3 * MIB);
  await expect.poll(async () => sum(await flow(page), "ack", idA), { timeout: 20_000 }).toBe(sum(await flow(page), "feed", idA));
  expect(sum(await flow(page), "ack", idA)).toBeGreaterThan(FLOW_HIGH);
  const mine = (await flow(page)).filter((f) => f.id === idA);
  expect(mine.filter((f) => f.op === "ack").map((f) => f.bytes)).toEqual(mine.filter((f) => f.op === "feed").map((f) => f.bytes));
  expect((await counts(page))[a]).toEqual({ rows: 0, sel: 0 });
  // shown, it has all of it
  await show(page, a);
  const s = await screenOf(page, a);
  expect(s.lines.at(-2) ?? "").toContain("build output");
  await expect.poll(async () => (await screenOf(page, a)).drawn).toEqual(s.view);
});

test("the bell and an OSC 9 message from a hidden terminal still reach its row", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  const row = page.getByTestId(`session-${a}`);
  const type = async (line: string) => {
    await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
    await page.keyboard.type(line);
    await page.keyboard.press("Enter");
  };
  await type("after 1200 bell");
  const b = await tagged(page);
  await expect(row).toHaveAttribute("data-term-status", "bell", { timeout: 8000 });
  await show(page, a);
  await expect(row).not.toHaveAttribute("data-term-status", "bell");
  await type("after 1200 osc9");
  await show(page, b);
  await expect(row).toHaveAttribute("data-term-status", "bell", { timeout: 8000 });
});

test("the bottom panel's terminal, hidden, draws nothing and shows what its shell printed meanwhile", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  const shown = page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');
  await expect(shown).toContainText("login shell in");
  const pty = await page.evaluate(() => (window as unknown as { __omherShellCalls: Call[] }).__omherShellCalls.filter((c) => c.op === "start").at(-1)!.id!);
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest('[data-testid="termpanel-terminal"]'))).toBe(true);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeHidden();
  await page.waitForTimeout(200);
  await count(page);
  await page.evaluate(async (p) => {
    const w = window as unknown as { __omherMockOut(p: number, d: string): boolean };
    for (let n = 1; n <= 40; n++) {
      w.__omherMockOut(p, `\x1b[2K\rline ${n} of the build\r\n⠋ building`);
      await new Promise((r) => setTimeout(r, 25));
    }
  }, pty);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  expect((await counts(page)).panel).toEqual({ rows: 0, sel: 0 });
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(shown).toContainText("line 40 of the build");
  await expect(shown).toContainText("⠋ building");
});

test("GPU renderer on: a hidden terminal draws nothing and takes a live GPU context again when shown", async ({ page }) => {
  await openApp(page, { term: { gpu: "on" } });
  const renderer = () => page.evaluate(async () => (await import("/src/sessions/term/engine.ts" as string)).rendererInUse() as string | null);
  const glLive = () =>
    page.evaluate(() => {
      for (const c of document.querySelectorAll<HTMLCanvasElement>('[data-testid="terminal"] .xterm canvas')) {
        const gl = c.getContext("webgl2");
        if (gl) return !gl.isContextLost();
      }
      return false;
    });
  const a = await tagged(page, true);
  await expect.poll(renderer).toBe("gpu");
  await expect.poll(glLive).toBe(true);
  await tagged(page, true);
  await expect.poll(glLive).toBe(true);
  await page.waitForTimeout(300);
  await count(page);
  await stream(page, [a], 1500);
  expect((await counts(page))[a]).toEqual({ rows: 0, sel: 0 });
  await show(page, a);
  await expect.poll(glLive).toBe(true);
  await expect.poll(renderer).toBe("gpu");
  const s = await screenOf(page, a);
  expect(s.lines.join("\n")).toContain("Read src/file-15.ts");
});
