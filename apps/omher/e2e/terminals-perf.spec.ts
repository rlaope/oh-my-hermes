// terminals-perf (run omher-mt, sidebar lane, 2026-11-17): a hidden terminal's output re-renders its own TERMINALS
// row only, never the list, the other rows or the folder headers.
// 1. 7 terminals: 5 hidden ones print a status line every 100 ms for 3 s; one hidden and the shown one stay idle.
//    The idle rows do not render at all; the list renders at most a handful of times; a printing row renders when
//    what it shows changes (its spinner, its second line), not per output.
// 2. The hidden printing rows still show it live: the spinner while output flows, the last printed line, then idle.
// Render counts come from `window.__omherRenders` (dev builds only, termActivity.ts `countRender`).
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page) {
  await page.addInitScript(() => {
    for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders"]) localStorage.removeItem(k);
    (window as unknown as Record<string, unknown>).__omherMockAgents = ["claude", "codex", "omh"];
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** Start `n` Shell terminals in two folders through the session store, as the + menu does; the last one is shown. */
async function startShells(page: Page, n: number): Promise<string[]> {
  const ids = await page.evaluate(async (n) => {
    const s = (window as any).__omherSessions;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const ids: string[] = [];
    for (let i = 0; i < n; i++) {
      const id = s.startTerminal("shell", `/home/you/code/repo-${i % 2}`);
      ids.push(id);
      for (let k = 0; k < 300 && s.ptyOf(id) === null; k++) await sleep(10);
    }
    return ids;
  }, n);
  for (const id of ids) await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  return ids;
}

/** Each of `ids` prints a spinner line every 100 ms for `ms` (a new line every fifth tick), as an agent does. */
const printFor = (page: Page, ids: string[], ms: number) =>
  page.evaluate(
    async ([ids, ms]) => {
      const s = (window as any).__omherSessions;
      const spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
      const t0 = performance.now();
      for (let n = 1; performance.now() - t0 < (ms as number); n++) {
        for (const id of ids as string[]) {
          let out = `\x1b[2K\r${spin[n % 10]} Working ${id} (${n} ticks)`;
          if (n % 5 === 0) out = `\x1b[2K\r  Read src/file-${n}.ts\r\n` + out;
          (window as any).__omherMockOut(s.ptyOf(id), out);
        }
        await new Promise((r) => setTimeout(r, 100));
      }
    },
    [ids, ms] as const,
  );

const renders = (page: Page) => page.evaluate(() => ({ ...((window as any).__omherRenders ?? {}) }) as Record<string, number>);

test("hidden output re-renders only its own row: idle rows never, the list a handful of times", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  const ids = await startShells(page, 7);
  const shown = ids.at(-1)!;
  const idleHidden = ids[0]!;
  const printing = ids.slice(1, 6);
  // the shown terminal is the last one started; let the start-up settle (prompt lines, first marks)
  await page.waitForTimeout(2_500);
  const before = await renders(page);
  await printFor(page, printing, 3_000);
  const after = await renders(page);
  const d = (k: string) => (after[k] ?? 0) - (before[k] ?? 0);
  const rows = Object.fromEntries(ids.map((id) => [id, d(`row:${id}`)]));
  // idle rows: not one render
  expect(rows[shown], JSON.stringify(rows)).toBe(0);
  expect(rows[idleHidden], JSON.stringify(rows)).toBe(0);
  // the list: a handful at most (it renders zero times when nothing about the sessions changed)
  expect(d("SessionList"), JSON.stringify(after)).toBeLessThanOrEqual(3);
  // a printing row renders when its spinner or line changes: its line is read at most twice a second
  for (const id of printing) {
    expect(rows[id], JSON.stringify(rows)).toBeGreaterThan(0);
    expect(rows[id], JSON.stringify(rows)).toBeLessThanOrEqual(12);
  }
});

test("a hidden printing row keeps its spinner and second line live, then goes idle", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  const ids = await startShells(page, 3);
  const hidden = ids[0]!;
  const row = page.getByTestId(`session-${hidden}`);
  await expect(row).toHaveAttribute("data-term-status", "idle");
  const run = printFor(page, [hidden], 2_500);
  // the spinner while output flows
  await expect(row).toHaveAttribute("data-term-status", "busy", { timeout: 2_000 });
  await expect(row.getByTestId("term-status")).toHaveAttribute("data-status", "busy");
  // the second line follows what it prints
  await expect(row.getByTestId("term-line")).toContainText(`Working ${hidden}`, { timeout: 2_000 });
  const first = await row.getByTestId("term-line").textContent();
  await expect.poll(() => row.getByTestId("term-line").textContent(), { timeout: 3_000 }).not.toBe(first);
  await run;
  // output stopped: idle again (BUSY_MS 2 s after the last mark), the last line stays
  await expect(row).toHaveAttribute("data-term-status", "idle", { timeout: 4_000 });
  await expect(row.getByTestId("term-line")).toContainText(`Working ${hidden}`);
  await expect(row.getByTestId("term-age")).toHaveText("now");
  // the program's title (OSC 2) is the second line while its screen shows nothing printed (cleared)
  const quiet = ids[1]!;
  await page.evaluate((id) => {
    const s = (window as any).__omherSessions;
    (window as any).__omherMockOut(s.ptyOf(id), "\x1b[2J\x1b[H\x1b]2;deploy watcher\x07");
  }, quiet);
  await expect(page.getByTestId(`session-${quiet}`).getByTestId("term-meta")).toContainText("deploy watcher");
});

test("a collapsed folder's spinner follows its hidden sessions' output", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  const ids = await startShells(page, 3);
  // repo-0 holds ids[0] and ids[2] (shown); repo-1 holds ids[1]
  const group = page.locator(`[data-testid=term-group][data-cwd="/home/you/code/repo-1"]`);
  await group.getByTestId("term-group-toggle").click();
  await expect(group).toHaveAttribute("data-collapsed", "true");
  await expect(group.getByTestId("term-group-summary")).not.toHaveAttribute("data-busy", "true");
  const run = printFor(page, [ids[1]!], 1_500);
  await expect(group.getByTestId("term-group-summary")).toHaveAttribute("data-busy", "true", { timeout: 2_000 });
  await run;
  await expect(group.getByTestId("term-group-summary")).not.toHaveAttribute("data-busy", "true", { timeout: 4_000 });
});
