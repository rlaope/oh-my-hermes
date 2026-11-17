// A terminal off the page and quiet long enough is parked (src/sessions/term/park.ts): its xterm is disposed and kept
// as a snapshot, and it is made again when shown or when its program prints. The thresholds are shortened through the
// dev build's `__omherPark` hook.
//   1. fidelity: plain lines, SGR colours, wide CJK and emoji, a TUI in the alternate screen, a line rewritten in place.
//      Parked, then shown, each equals a never-parked twin fed the same bytes: every line, the cursor, the buffer,
//      the modes, a sample of cells' colours and the title;
//   2. a parked terminal that gets output is made again off the page and acknowledges every byte;
//   3. a parked terminal's BEL and OSC 9 ring its row;
//   4. closing a parked terminal stops its program;
//   5. ten parked terminals hold at least 80% less xterm buffer than they did;
//   6. the bottom panel's terminal parks while the panel is hidden and shows its shell's output when opened;
//   7. one in a mode the snapshot cannot restore (mouse tracking) is not parked.
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

/** Park quickly: off the page 200 ms, quiet 200 ms, looked at every 100 ms. */
const fast = (page: Page) =>
  page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
const parkedCount = (page: Page) => page.evaluate(() => (window as unknown as { __omherPark: { parked(): number } }).__omherPark.parked());

const show = async (page: Page, id: string) => {
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
};

/** A new terminal session. Its element (where xterm opens, and where a parked one is made again) is tagged with the
 *  session id, so the terminal can be found whichever xterm it is now. */
async function tagged(page: Page): Promise<string> {
  const id = await newTerminal(page);
  await page.evaluate((sid) => {
    const host = document.querySelector('[data-testid="terminal"] .xterm')!.parentElement as HTMLElement & { __sid?: string };
    host.__sid = sid;
  }, id);
  return id;
}

const ptyOf = (page: Page, id: string) => page.evaluate((sid) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(sid)!, id);
const out = (page: Page, pty: number, d: string) =>
  page.evaluate(([p, data]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, data as string), [pty, d] as const);

/** Whether session `id` has a live xterm now (a parked one has none). */
const hasXterm = (page: Page, id: string) =>
  page.evaluate((sid) => [...(window as unknown as { __omherTerms: Set<{ element?: HTMLElement }> }).__omherTerms].some((t) => (t.element?.parentElement as { __sid?: string } | null)?.__sid === sid), id);

/** Everything compared against the twin, read once the terminal has taken what it was sent. */
const stateOf = (page: Page, sid: string) =>
  page.evaluate(async (want) => {
    type Cell = { getChars(): string; getWidth(): number; getFgColorMode(): number; getFgColor(): number; getBgColorMode(): number; getBgColor(): number; isBold(): number };
    type Line = { translateToString(t: boolean): string; getCell(x: number): Cell | undefined };
    type Buf = { type: string; length: number; cursorX: number; cursorY: number; baseY: number; getLine(i: number): Line | undefined };
    type T = { element?: HTMLElement; cols: number; modes: object; write(d: string, cb: () => void): void; buffer: { active: Buf }; _core: { _inputHandler: { _windowTitle: string }; coreService: { isCursorHidden: boolean } } };
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => (x.element?.parentElement as { __sid?: string } | null)?.__sid === want);
    if (!t) throw new Error(`no terminal ${want}`);
    await new Promise<void>((r) => t.write("", r));
    const b = t.buffer.active;
    const lines: string[] = [];
    const cells: unknown[] = [];
    for (let y = 0; y < b.length; y++) {
      const l = b.getLine(y)!;
      lines.push(l.translateToString(true));
      for (let x = 0; x < t.cols; x += 5) {
        const c = l.getCell(x)!;
        // a colour as xterm draws it: the 16- and 256-colour modes are one palette to its renderers (`38;5;1` and
        // `31` draw the same), and the snapshot writes an index under 16 in the short form
        const mode = (m: number) => (m === 0x1000000 || m === 0x2000000 ? "palette" : m);
        cells.push([c.getChars(), c.getWidth(), mode(c.getFgColorMode()), c.getFgColor(), mode(c.getBgColorMode()), c.getBgColor(), c.isBold()]);
      }
    }
    return { type: b.type, lines, cells, cursor: [b.cursorX, b.cursorY, b.baseY], modes: t.modes, title: t._core._inputHandler._windowTitle, cursorHidden: t._core.coreService.isCursorHidden };
  }, sid);

const many = (n: number, f: (i: number) => string) => Array.from({ length: n }, (_, i) => f(i)).join("");
const CASES: [string, string][] = [
  ["plain lines", many(60, (i) => `plain line ${i} of the program's output\r\n`)],
  ["SGR colour lines", many(40, (i) => `\x1b[3${i % 8}m${i}\x1b[0m \x1b[1;38;5;${(i * 7) % 256}mbold 256\x1b[0m \x1b[48;2;${i};40;90mrgb\x1b[0m \x1b[7minverse\x1b[0m\r\n`)],
  ["wide CJK and emoji", many(30, (i) => `${i} 한글 출력 漢字 テスト 😀👍🏽 ✅ done\r\n`)],
  [
    "a TUI in the alternate screen",
    many(30, (i) => `scrollback ${i}\r\n`) +
      "\x1b]2;✻ claude · repo\x07\x1b[?1049h\x1b[H\x1b[2J\x1b[?25l\x1b[?2004h" +
      "\x1b[2;3H╭────────────────────────────────╮\x1b[3;3H│ \x1b[1;38;5;174m✻\x1b[0m Welcome to Claude Code      │\x1b[4;3H╰────────────────────────────────╯" +
      "\x1b[8;1H\x1b[2m? for shortcuts\x1b[0m\x1b[6;3H\x1b[36m>\x1b[0m fix the bug",
  ],
  ["a line rewritten in place", "build:\r\n" + many(12, (i) => `\r\x1b[2K\x1b[33m${"⠋⠙⠹⠸⠼⠴"[i % 6]}\x1b[0m Working… (${i}s)`) + "\r\x1b[2K  ⎿  done in 12s\r\n$ "],
];

for (const [name, bytes] of CASES) {
  test(`fidelity, parked then shown: ${name}`, async ({ page }) => {
    await openApp(page);
    const a = await tagged(page);
    const twin = await tagged(page); // shown: never parked
    const [pa, pt] = [await ptyOf(page, a), await ptyOf(page, twin)];
    for (let i = 0; i < bytes.length; i += 500) {
      // the same bytes, in the same chunks and order, to both
      expect(await out(page, pa, bytes.slice(i, i + 500))).toBe(true);
      expect(await out(page, pt, bytes.slice(i, i + 500))).toBe(true);
    }
    const want = await stateOf(page, twin);
    await fast(page);
    await expect.poll(() => parkedCount(page)).toBe(1);
    expect(await hasXterm(page, a)).toBe(false);
    await show(page, a);
    expect(await stateOf(page, a)).toEqual(want);
    // drawn: the rows on the page are the buffer's screen
    if (want.type === "alternate") await expect(page.locator('[data-testid="terminal"] .xterm-rows')).toContainText("Welcome to Claude Code");
  });
}

test("a parked terminal that gets output is made again off the page and acknowledges every byte", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  await tagged(page);
  const pa = await ptyOf(page, a);
  await fast(page);
  await expect.poll(() => parkedCount(page)).toBe(1);
  const before = sum(await flow(page), "feed", pa);
  const chunk = many(200, (i) => `line ${i} after parking\r\n`);
  for (let k = 0; k < 20; k++) await out(page, pa, chunk);
  await expect.poll(async () => sum(await flow(page), "ack", pa)).toBe(sum(await flow(page), "feed", pa));
  expect(sum(await flow(page), "feed", pa) - before).toBe(20 * chunk.length);
  const mine = (await flow(page)).filter((f) => f.id === pa);
  expect(mine.filter((f) => f.op === "ack").map((f) => f.bytes)).toEqual(mine.filter((f) => f.op === "feed").map((f) => f.bytes));
  // made again where it was: off the page
  expect(await hasXterm(page, a)).toBe(true);
  expect(await page.evaluate((sid) => [...(window as unknown as { __omherTerms: Set<{ element?: HTMLElement }> }).__omherTerms].find((t) => (t.element?.parentElement as { __sid?: string } | null)?.__sid === sid)!.element!.isConnected, a)).toBe(false);
  await show(page, a);
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).toContainText("line 199 after parking");
});

test("a parked terminal's bell and OSC 9 ring its row", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  const b = await tagged(page);
  const row = page.getByTestId(`session-${a}`);
  const pa = await ptyOf(page, a);
  await fast(page);
  await expect.poll(() => parkedCount(page)).toBe(1);
  await out(page, pa, "waiting for you\x07");
  await expect(row).toHaveAttribute("data-term-status", "bell");
  await show(page, a);
  await expect(row).not.toHaveAttribute("data-term-status", "bell");
  await show(page, b);
  await expect.poll(() => parkedCount(page)).toBe(1);
  await out(page, pa, "\x1b]9;Claude needs your permission\x07");
  await expect(row).toHaveAttribute("data-term-status", "bell");
});

// integrate (run omher-mt): the remade xterm writes its row's activity through termActivity like the first one did,
// the second line from the readLine timer reading the NEW xterm, the OSC title from the handler `wire` mounts on it
test("a parked terminal that prints updates its row's second line and OSC title from the remade xterm", async ({ page }) => {
  await openApp(page);
  // two Shell terminals, as the + menu starts them; the second is shown, the first is hidden and parks
  const [a] = await page.evaluate(async () => {
    const s = (window as unknown as { __omherSessions: { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null } }).__omherSessions;
    const ids: string[] = [];
    for (let i = 0; i < 2; i++) {
      const id = s.startTerminal("shell", "/home/you/code/repo");
      ids.push(id);
      for (let k = 0; k < 300 && s.ptyOf(id) === null; k++) await new Promise((r) => setTimeout(r, 10));
    }
    return ids;
  });
  const row = page.getByTestId(`session-${a}`);
  const pa = await ptyOf(page, a!);
  await fast(page);
  await expect.poll(() => parkedCount(page)).toBe(1);
  await out(page, pa, "printed after parking, line one\r\n$ ");
  await expect.poll(() => parkedCount(page)).toBe(0);
  // the line is read from the screen a moment later: from the xterm made again, not the disposed one
  await expect(row.getByTestId("term-line")).toContainText("printed after parking, line one");
  // parked again, then the program clears its screen and sets a title: the title is the second line
  await expect.poll(() => parkedCount(page), { timeout: 10_000 }).toBe(1);
  await out(page, pa, "\x1b[2J\x1b[H\x1b]2;watching after a park\x07");
  await expect.poll(() => parkedCount(page)).toBe(0);
  await expect(row.getByTestId("term-meta")).toContainText("watching after a park");
});

test("closing a parked terminal stops its program", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  await tagged(page);
  const pa = await ptyOf(page, a);
  await fast(page);
  await expect.poll(() => parkedCount(page)).toBe(1);
  await page.evaluate((sid) => (window as unknown as { __omherSessions: { close(id: string): unknown } }).__omherSessions.close(sid), a);
  await expect.poll(async () => (await page.evaluate(() => (window as unknown as { __omherSessionCalls: Call[] }).__omherSessionCalls)).some((c) => c.op === "close" && c.id === pa)).toBe(true);
  await expect.poll(() => parkedCount(page)).toBe(0);
  await expect(page.getByTestId(`session-${a}`)).toHaveCount(0);
});

test("ten parked terminals hold at least 80% less xterm buffer than before", async ({ page }) => {
  test.setTimeout(120_000);
  await openApp(page);
  const ids = await page.evaluate(async () => {
    const s = (window as unknown as { __omherSessions: { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null } }).__omherSessions;
    const out: string[] = [];
    for (let i = 0; i < 11; i++) {
      const id = s.startTerminal("shell", `/home/you/code/repo-${i % 3}`);
      out.push(id);
      for (let k = 0; k < 300 && s.ptyOf(id) === null; k++) await new Promise((r) => setTimeout(r, 10));
    }
    return out;
  });
  /** xterm buffer bytes of every terminal object still around (live ones and the parked, disposed ones), plus the
   *  parked ones' snapshots. */
  const bytes = () =>
    page.evaluate(async () => {
      type T = { write(d: string, cb: () => void): void; _core: { buffers: { normal: { lines: { length: number; get(i: number): { _data?: Uint32Array } | undefined } }; alt: { lines: { length: number; get(i: number): { _data?: Uint32Array } | undefined } } } } };
      const w = window as unknown as { __omherTerms: Set<T>; __omherPark: { held(): T[]; snapshotBytes(): number } };
      const all = [...w.__omherTerms, ...w.__omherPark.held()];
      // what parking keeps instead counts too
      let n = w.__omherPark.snapshotBytes();
      for (const t of all)
        for (const b of [t._core.buffers.normal, t._core.buffers.alt]) for (let i = 0; i < b.lines.length; i++) n += b.lines.get(i)?._data?.byteLength ?? 0;
      return n;
    });
  await page.evaluate(async (sids) => {
    const w = window as unknown as { __omherSessions: { ptyOf(id: string): number | null }; __omherMockOut(p: number, d: string): boolean; __omherTerms: Set<{ write(d: string, cb: () => void): void }> };
    let chunk = "";
    for (let i = 0; chunk.length < 32 * 1024; i++) chunk += (`\x1b[32m${i}\x1b[0m ` + "agent tool result file path diff patch status ".repeat(3)).slice(0, 118) + "\r\n";
    for (const id of sids) for (let k = 0; k < 16; k++) w.__omherMockOut(w.__omherSessions.ptyOf(id)!, chunk);
    await Promise.all([...w.__omherTerms].map((t) => new Promise<void>((r) => t.write("", () => r()))));
  }, ids);
  const full = await bytes();
  await fast(page);
  await expect.poll(() => parkedCount(page), { timeout: 20_000 }).toBe(10);
  const left = await bytes();
  // eleven terminals before, one live and ten parked after: the parked ten's share is what dropped
  const one = full / 11;
  const parkedBefore = full - one;
  const parkedAfter = left - one;
  console.log(`park e2e: ${(full / 1048576).toFixed(1)} MB -> ${(left / 1048576).toFixed(1)} MB (ten parked: ${(parkedBefore / 1048576).toFixed(1)} -> ${(parkedAfter / 1048576).toFixed(2)} MB)`);
  expect(parkedAfter).toBeLessThanOrEqual(parkedBefore * 0.2);
});

test("the bottom panel's terminal parks while hidden and shows its shell's output when opened", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  const shown = page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');
  await expect(shown).toContainText("login shell in");
  const pty = await page.evaluate(() => (window as unknown as { __omherShellCalls: Call[] }).__omherShellCalls.filter((c) => c.op === "start").at(-1)!.id!);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeHidden();
  await fast(page);
  await expect.poll(() => parkedCount(page)).toBe(1);
  await page.evaluate((p) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p, "printed while parked\r\n$ "), pty);
  await expect.poll(() => parkedCount(page)).toBe(0);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(shown).toContainText("login shell in");
  await expect(shown).toContainText("printed while parked");
});

test("a terminal in a mode the snapshot cannot restore (mouse tracking) is not parked", async ({ page }) => {
  await openApp(page);
  const a = await tagged(page);
  const b = await tagged(page);
  await out(page, await ptyOf(page, a), "\x1b[?1002h\x1b[?1006h");
  await out(page, await ptyOf(page, b), "\x1b[?1002h\x1b[?1006h");
  await fast(page);
  await page.waitForTimeout(1200);
  expect(await parkedCount(page)).toBe(0);
  expect(await hasXterm(page, a)).toBe(true);
});
