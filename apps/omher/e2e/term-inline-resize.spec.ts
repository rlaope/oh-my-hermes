// Inline TUIs (omh, Claude Code's Ink, Codex's ratatui viewport) and full-screen ones (vim/htop, OmO/opencode) in a
// SESSIONS terminal, against what omher does to xterm's screen behind the program's back.
//
//   1. A resize that comes back to the size the program was told (a show re-fits in the DOM renderer's cells, then in
//      the GPU's: 142 -> 127 -> 142 columns within 5 ms) used to send nothing, so the program never redrew a screen
//      xterm had reflowed and trimmed (sessions.ts `tellSize`). Now the program is told, and a pty resize to its own
//      size sends no SIGWINCH, so it is told one size off and then the real one.
//   2. Session switching with the GPU renderer: xterm does take the transient sizes (printed), and the program is told.
//   3. Parked then shown: the screen equals a never-parked twin's, for each program's drawing style.
// Chromium (Playwright's headless shell) on the mock host; nothing here ran in the Tauri window.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Call = { op: string; cols?: number; rows?: number };
const resizes = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []).filter((c) => c.op === "resize"));

const ESC = "\x1b";
const pad = (s: string, n: number) => s + " ".repeat(Math.max(0, n - [...s].length));

/** The programs' drawing styles, each as the bytes of a settled screen at `cols` x `rows`. */
const PROGRAMS: Record<string, (cols: number, rows: number) => string> = {
  // src/tui/screen.py `_compose`: sync begin, hide cursor, autowrap off, rows by CUU/CUD + CR + EL, cursor in the composer
  omh: (cols, rows) => {
    const box = ["╭" + "─".repeat(cols - 2) + "╮", "│ skills" + " ".repeat(cols - 10) + "│", "│ hermes  apple  +18 more" + " ".repeat(cols - 27) + "│", "╰" + "─".repeat(cols - 2) + "╯"];
    const region = [...box, "❯ Ask Hermes anything", "  high"];
    return `${ESC}[2J${ESC}[H` + "history\r\n".repeat(rows - region.length - 1) + `${ESC}[?2026h${ESC}[?25l${ESC}[?7l\r` + region.map((r) => r + `${ESC}[K`).join(`${ESC}[1B\r`) + `${ESC}[?7h${ESC}[1A\r${ESC}[2C${ESC}[?25h${ESC}[?2026l`;
  },
  // Ink (Claude Code): inline, normal screen; erases its last frame with EL + CUU, rewrites it, parks below it
  "claude-ink": (cols, rows) => {
    const frame = ["╭" + "─".repeat(cols - 2) + "╮", "│ > Try \"fix the failing test\"" + " ".repeat(cols - 31) + "│", "╰" + "─".repeat(cols - 2) + "╯", "  ? for shortcuts"];
    return `${ESC}[2J${ESC}[H` + "history\r\n".repeat(rows - frame.length - 1) + `${ESC}[?2026h` + frame.join("\r\n") + "\r\n" + `${ESC}[2K${ESC}[1A`.repeat(frame.length) + `${ESC}[2K${ESC}[G` + frame.join("\r\n") + `\r\n${ESC}[?2026l${ESC}[?25l`;
  },
  // ratatui inline viewport (Codex): history inserted above through a scroll region, viewport at the bottom by CUP
  "codex-ratatui": (cols, rows) => {
    const top = rows - 5;
    let s = `${ESC}[2J${ESC}[H`;
    s += `${ESC}[1;${top}r${ESC}[${top};1H` + "history line\r\n".repeat(3) + `${ESC}[r`;
    const vp = ["╭" + "─".repeat(cols - 2) + "╮", "│ " + pad("› Ask Codex to do anything", cols - 4) + " │", "╰" + "─".repeat(cols - 2) + "╯", "  gpt-5 · 83% context left", ""];
    vp.forEach((r, i) => (s += `${ESC}[${top + 1 + i};1H${r}${ESC}[K`));
    return s + `${ESC}[${top + 2};5H`;
  },
  // vim/htop: alternate screen, absolute positioning, a status line on the last row
  "alt-screen": (cols, rows) => {
    let s = `${ESC}[?1049h${ESC}[H${ESC}[2J${ESC}[?25l`;
    for (let r = 1; r < rows; r++) s += `${ESC}[${r};1H${pad(`  ${r}  line of the file`, cols)}`;
    return s + `${ESC}[${rows};1H${ESC}[7m${pad(" status ", cols)}${ESC}[0m${ESC}[3;5H${ESC}[?25h`;
  },
  // OmO / opencode (OpenTUI): alternate screen with mouse and kitty keyboard on
  "alt-screen-mouse": (cols, rows) => {
    let s = `${ESC}[?1049h${ESC}[?1000h${ESC}[?1006h${ESC}[>1u${ESC}[H${ESC}[2J${ESC}[?25l`;
    for (let r = 1; r < rows - 2; r++) s += `${ESC}[${r};1H${pad(`  ${r}  message`, cols)}`;
    s += `${ESC}[${rows - 1};1H${pad("┃ ask anything", cols)}${ESC}[${rows};1H${pad("  tab agents  ctrl+p commands", cols)}`;
    return s;
  },
};

type T = { element?: HTMLElement; cols: number; rows: number; resize(c: number, r: number): void; buffer: { active: { type: string; cursorX: number; cursorY: number; baseY: number; length: number; getLine(i: number): { translateToString(t: boolean): string } } } };

const shot = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    const b = t.buffer.active;
    const lines: string[] = [];
    for (let y = 0; y < b.length; y++) lines.push(b.getLine(y).translateToString(true));
    return { type: b.type, cols: t.cols, rows: t.rows, cursor: [b.cursorX, b.cursorY], baseY: b.baseY, lines };
  });

/** xterm to `size + d` and back inside one task: the settle timer ends on the size the program was told. */
const roundTrip = (page: Page, dc: number, dr: number) =>
  page.evaluate(([c, r]) => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    const { cols, rows } = t;
    t.resize(cols + c, rows + r);
    t.resize(cols, rows);
  }, [dc, dr] as const);

for (const [prog, draw] of Object.entries(PROGRAMS)) {
  for (const [name, dc, dr] of [["rows -4", 0, -4], ["cols -30", -30, 0]] as const) {
    test(`${prog}: xterm resized ${name} and back, the program is told`, async ({ page }) => {
      await openApp(page);
      await newTerminal(page);
      const { cols, rows } = await shot(page);
      await feed(page, draw(cols, rows));
      const before = await shot(page);
      const sent = (await resizes(page)).length;
      await roundTrip(page, dc, dr);
      await page.waitForTimeout(300); // the settle (32 ms) and then some
      const after = await shot(page);
      const told = (await resizes(page)).slice(sent);
      const same = JSON.stringify(after) === JSON.stringify(before);
      console.log(`${prog} ${name}: screen ${same ? "UNCHANGED" : "CHANGED by the round trip"}; resizes sent:`, JSON.stringify(told.map((c) => `${c.cols}x${c.rows}`)));
      // whatever xterm did to its screen, the program learns of it and ends on the real size
      expect(told.length).toBeGreaterThan(0);
      expect(told.at(-1)).toMatchObject({ cols, rows });
    });
  }
}

/** A new Claude session; with the GPU renderer the rows are not in the DOM, so only the session id is awaited. */
async function openTerminal(page: Page): Promise<string> {
  const term = page.getByTestId("terminal");
  const before = (await term.count()) ? await term.getAttribute("data-session") : null;
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-claude").click();
  await expect(term).toHaveAttribute("data-session", /./);
  if (before) await expect(term).not.toHaveAttribute("data-session", before);
  await expect(page.locator('[data-testid="terminal"] .xterm')).toHaveCount(1);
  await page.waitForTimeout(500);
  return (await term.getAttribute("data-session")) as string;
}

const showSession = async (page: Page, id: string) => {
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
};

for (const gpu of ["off", "on"] as const) {
  test(`session switching, gpu ${gpu}: the sizes xterm takes, and the program is told`, async ({ page }) => {
    await openApp(page, { term: { gpu } });
    const a = await openTerminal(page);
    if (gpu === "on") await expect.poll(() => page.locator('[data-testid="terminal"] .xterm canvas').count()).toBeGreaterThan(0);
    await page.waitForTimeout(300);
    const { cols, rows } = await shot(page);
    await feed(page, PROGRAMS.omh(cols, rows));
    const before = await shot(page);
    await page.evaluate(() => {
      const host = document.querySelector('[data-testid="terminal"] .xterm');
      const t = [...(window as unknown as { __omherTerms: Set<{ element?: HTMLElement; onResize(f: (e: { cols: number; rows: number }) => void): void }> }).__omherTerms].find((x) => x.element === host)!;
      const log: string[] = ((window as unknown as { __rz: string[] }).__rz = []);
      t.onResize((e) => log.push(`${e.cols}x${e.rows}`));
    });
    const sent = (await resizes(page)).length;
    const b = await openTerminal(page);
    for (let i = 0; i < 4; i++) {
      await showSession(page, a);
      await showSession(page, b);
    }
    await showSession(page, a);
    await page.waitForTimeout(400);
    const after = await shot(page);
    const rz = await page.evaluate(() => (window as unknown as { __rz: string[] }).__rz);
    const told = (await resizes(page)).slice(sent);
    console.log(`gpu ${gpu}: xterm resized`, rz.length, "times", JSON.stringify(rz.slice(0, 4)), "program told", told.length, "times; screen", JSON.stringify(after) === JSON.stringify(before) ? "unchanged" : "CHANGED");
    // showing a terminal at the size it had changes nothing: no transient fit in the standard renderer's cells, so
    // xterm's screen is as the program drew it and the program is not made to redraw on every switch
    expect(rz).toEqual([]);
    expect(told).toEqual([]);
    expect(JSON.stringify(after)).toBe(JSON.stringify(before));
    expect(told.at(-1) ?? { cols, rows }).toMatchObject({ cols, rows });
  });
}

// ---- parked then shown, equal to a twin that never parked ----
const fast = (page: Page) =>
  page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
const parkedCount = (page: Page) => page.evaluate(() => (window as unknown as { __omherPark: { parked(): number } }).__omherPark.parked());
const ptyOf = (page: Page, id: string) => page.evaluate((sid) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(sid)!, id);
const out = (page: Page, pty: number, d: string) =>
  page.evaluate(([p, data]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, data as string), [pty, d] as const);

for (const [prog, draw] of Object.entries(PROGRAMS)) {
  test(`${prog}: parked then shown equals a twin that never parked`, async ({ page }) => {
    await openApp(page);
    const a = await newTerminal(page);
    const twin = await newTerminal(page);
    const { cols, rows } = await shot(page);
    const bytes = draw(cols, rows);
    for (const id of [a, twin]) expect(await out(page, await ptyOf(page, id), bytes)).toBe(true);
    await page.waitForTimeout(200);
    const want = await shot(page); // the twin is shown
    await fast(page);
    if (prog === "alt-screen-mouse") {
      // mouse tracking is on: the snapshot cannot carry it (park.ts `cannotPark`), so it stays as it is
      await page.waitForTimeout(800);
      expect(await parkedCount(page)).toBe(0);
      return;
    }
    await expect.poll(() => parkedCount(page)).toBe(1);
    await page.evaluate(() => (window as unknown as { __omherPark: { set(l: object): void } }).__omherPark.set({ hiddenMs: 999_999, idleMs: 999_999, sweepMs: 1000 }));
    await showSession(page, a);
    await page.waitForTimeout(300);
    const got = await shot(page);
    expect(got.lines).toEqual(want.lines);
    expect(got.cursor).toEqual(want.cursor);
    expect(got.type).toBe(want.type);
  });
}
