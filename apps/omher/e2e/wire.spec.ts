// wire (run omher-terminals, 2026-11-16): the TERMINALS row's mark follows the shell's `session-fg` event, the
// Orca-style folders, and a bot click that slides its row to the top of BOTS.
// 1. session-fg: a Shell row shows the shell icon -> the event names claude -> Claude Code's mark with the live frame
//    and "Claude Code running" -> null -> the shell icon; two terminals follow their own CLIs; the bottom panel's tab
//    shows the mark of its shell's foreground CLI; reduced motion: nothing turns;
// 2. status glyph from the same session events: amber arc while output flows, check on exit 0, x on a non-zero exit;
// 3. the row the main area shows is always in the TERMINALS list and in view (dock pins and a short region too);
// 4. folders: collapse/expand persists across a reload; a collapsed header shows the count and the live summary;
//    opening a session in a collapsed folder opens it; Collapse all; right-click menu; drag reorder persists;
// 5. bot click: its row slides to the top of BOTS with its threads under it; TERMINALS stays; reduced motion jumps;
// 6. the dock (owner correction, polish 7): BOTS ONLY, and only while BOTS is scrolled: its tiles are exactly the bots
//    scrolled out of view at the top; none at the top; a tile click is the bot reveal; 4 tiles fill 2x2, the running
//    ring sits centred inside its tile;
// 7. no row is ever drawn cut at a region's bottom edge (the row there is hidden whole under the "more" chevron).
// Shots: OMHER_SHOTS=<dir> (1440x900) -> sidebar-dark, sidebar-light, plus-menu, many-rows-scroll, terminal-open,
// threads-chat, terminals-folders-collapsed, bot-reveal-before, bot-reveal-after, sidebar-dark-scrolled (the dock).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

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

async function shot(page: Page, name: string, clip?: { x: number; y: number; width: number; height: number }) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  // no mock wording and no home path of this Mac in a picture
  const text = await page.evaluate(() => document.body.innerText);
  expect(text).not.toContain("(mock)");
  expect(text).not.toMatch(/\/Users\//);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial", clip });
}

const WEB = "/home/you/code/web-app";
const API = "/home/you/code/api-server";
const NOTES = "/home/you/code/notes";

async function open(page: Page, o: { theme?: "dark" | "light"; roster?: string[]; keep?: boolean; reduced?: boolean } = {}) {
  if (o.reduced) await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(
    ([theme, roster, keep]) => {
      if (!keep || !sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders"]) localStorage.removeItem(k);
        sessionStorage.setItem("__kept", "1");
      }
      if (theme) localStorage.setItem("omher.theme", theme as string);
      if (roster) localStorage.setItem("omher.roster", JSON.stringify(roster));
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = "/home/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "grok", "opencode", "omh", "pi", "omp", "omo"];
      w.__omherBranches = { "/home/you/code/web-app": "feature/checkout-flow", "/home/you/code/api-server": "main", "/home/you/code/notes": "" };
    },
    [o.theme ?? null, o.roster ?? null, !!o.keep] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** Start `agent` (or `shell`) from the TERMINALS + menu in `folder`; its session id. */
async function newTerm(page: Page, agent: string, folder: string): Promise<string> {
  const before = await page.evaluate(() => (window as any).__omherSessions.getState().list.map((r: { id: string }) => r.id));
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  const recent = page.locator(`[data-testid=session-folder-pick][title="${folder}"]`);
  if (await recent.count()) await recent.click();
  else {
    await page.evaluate((f) => ((window as unknown as Record<string, unknown>).__omherPickFolder = f), folder);
    await page.getByTestId("session-choose").click();
  }
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  const id = await expect
    .poll(() => page.evaluate((b) => (window as any).__omherSessions.getState().list.find((r: { id: string }) => !b.includes(r.id))?.id ?? null, before))
    .not.toBeNull()
    .then(() => page.evaluate((b) => (window as any).__omherSessions.getState().list.find((r: { id: string }) => !b.includes(r.id)).id as string, before));
  await expect.poll(() => pty(page, id)).not.toBeNull();
  // the program's first screen has printed (a seeded screen goes after it, not under it)
  await expect(page.locator(".xterm-rows").last()).toContainText(/\S/);
  await page.waitForTimeout(60);
  return id;
}

const pty = (page: Page, id: string) => page.evaluate((i) => (window as any).__omherSessions.ptyOf(i) as number | null, id);
/** The shell's `session-fg` event for session `id`'s pty. */
async function fg(page: Page, id: string, agent: string | null) {
  const p = await pty(page, id);
  await page.evaluate(([p, a]) => (window as any).__omherEmitSessionFg({ id: p, agent: a }), [p, agent] as const);
}
/** Print `text` into session `id`'s terminal, as its program would. */
async function out(page: Page, id: string, text: string) {
  const p = await pty(page, id);
  expect(await page.evaluate(([p, t]) => (window as any).__omherMockOut(p, t), [p, text] as const)).toBe(true);
}

const CLEAR = "\x1b[2J\x1b[3J\x1b[H";
const CLAUDE_SCREEN =
  CLEAR +
  "\x1b[38;2;217;119;87m╭───────────────────────────────────────────────╮\x1b[0m\r\n" +
  "\x1b[38;2;217;119;87m│\x1b[0m \x1b[38;2;217;119;87m✻\x1b[0m Welcome to \x1b[1mClaude Code\x1b[0m                      \x1b[38;2;217;119;87m│\x1b[0m\r\n" +
  "\x1b[38;2;217;119;87m│\x1b[0m   \x1b[2mcwd: ~/code/web-app\x1b[0m                         \x1b[38;2;217;119;87m│\x1b[0m\r\n" +
  "\x1b[38;2;217;119;87m╰───────────────────────────────────────────────╯\x1b[0m\r\n\r\n" +
  "\x1b[1m>\x1b[0m Make the checkout total update when a coupon is removed\r\n\r\n" +
  "\x1b[38;2;217;119;87m⏺\x1b[0m I'll look at how the cart total is computed.\r\n\r\n" +
  "\x1b[38;2;217;119;87m⏺\x1b[0m \x1b[1mRead\x1b[0m(src/checkout/cart.ts)\r\n" +
  "  ⎿  Read 142 lines\r\n\r\n" +
  "\x1b[38;2;217;119;87m⏺\x1b[0m \x1b[1mUpdate\x1b[0m(src/checkout/cart.ts)\r\n" +
  "  ⎿  Updated src/checkout/cart.ts with 2 additions and 1 removal\r\n" +
  "      \x1b[2m88\x1b[0m   \x1b[48;2;60;20;20m-   if (!coupon) return subtotal;\x1b[0m\r\n" +
  "      \x1b[2m88\x1b[0m   \x1b[48;2;20;60;30m+   const discount = coupon ? applyCoupon(subtotal, coupon) : 0;\x1b[0m\r\n" +
  "      \x1b[2m89\x1b[0m   \x1b[48;2;20;60;30m+   return Math.max(0, subtotal - discount);\x1b[0m\r\n\r\n" +
  "\x1b[38;2;217;119;87m✻\x1b[0m \x1b[38;2;217;119;87mRunning tests…\x1b[0m \x1b[2m(12s · esc to interrupt)\x1b[0m\r\n";
const CODEX_SCREEN =
  CLEAR +
  "\x1b[1m>_ OpenAI Codex\x1b[0m \x1b[2m(v0.92.0)\x1b[0m\r\n\x1b[2mmodel: gpt-5.2-codex   directory: ~/code/web-app\x1b[0m\r\n\r\n" +
  "\x1b[36muser\x1b[0m\r\nAdd a retry with backoff to the payment webhook handler\r\n\r\n" +
  "\x1b[35mcodex\x1b[0m\r\nI'll wrap the handler in a retry helper.\r\n\x1b[2m• Edited\x1b[0m src/payments/webhook.ts (+18 -4)\r\n\x1b[2m• Ran\x1b[0m pnpm test payments \x1b[32m✓ 24 passed\x1b[0m\r\n\r\n▌ ";
const GROK_SCREEN = CLEAR + "\x1b[1mGrok\x1b[0m \x1b[2m· api-server\x1b[0m\r\n\r\n> Summarise the 5xx spikes in logs/api.log since Monday\r\n\r\nReading logs/api.log…\r\n";
const SHELL_SCREEN = (dir: string) => `${CLEAR}\x1b[32myou@laptop\x1b[0m \x1b[34m${dir}\x1b[0m % git status -sb\r\n## main...origin/main\r\n M src/routes/orders.ts\r\n\x1b[32myou@laptop\x1b[0m \x1b[34m${dir}\x1b[0m % `;
const PI_SCREEN = CLEAR + "\x1b[1mπ pi\x1b[0m  \x1b[2mapi-server\x1b[0m\r\n\r\n> Draft the release notes for 2.4\r\nWrote docs/RELEASE-2.4.md\r\n";

/** web-app: a Shell where the person typed `claude` (Claude Code's mark from the session-fg event, output flowing),
 *  Codex (running); api-server: a plain Shell, an exited pi. `grok: true` adds a Shell running Grok. */
async function seed(page: Page, o: { grok?: boolean } = {}) {
  const shell = await newTerm(page, "shell", API);
  await out(page, shell, SHELL_SCREEN("api-server"));
  let shellGrok: string | null = null;
  if (o.grok) {
    shellGrok = await newTerm(page, "shell", API);
    await out(page, shellGrok, GROK_SCREEN);
    await fg(page, shellGrok, "grok");
  }
  // pi in web-app too (it ended): the exited one shows under the running two
  const pi = await newTerm(page, "pi", WEB);
  await out(page, pi, PI_SCREEN);
  const codex = await newTerm(page, "codex", WEB);
  await out(page, codex, CODEX_SCREEN);
  const claude = await newTerm(page, "shell", WEB);
  await fg(page, claude, "claude");
  // pi ends (exit 0): the check
  await page.getByTestId(`session-${pi}`).locator(".ss-open").click();
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type("exit\r");
  await expect(page.getByTestId(`session-${pi}`)).toHaveAttribute("data-term-status", "ok");
  await page.getByTestId(`session-${claude}`).locator(".ss-open").click();
  await out(page, claude, CLAUDE_SCREEN);
  return { claude, codex, shellGrok, shell, pi };
}

/** Kami's threads in every state (running with a Codex part, needs you, done, failed, idle). */
const THREADS = [
  { title: "Release notes for 2.4", ago: 4 * 3600, messages: [["user", "Draft the release notes for 2.4"], ["assistant", "The draft is in docs/RELEASE-2.4.md."]] },
  { title: "Nightly build failure", ago: 3 * 3600 },
  { title: "Tighten the Slack alert copy", ago: 2 * 3600 },
  { title: "Docs dark mode contrast", ago: 3600 },
  { title: "Gateway 502s on checkout", ago: 60, cwd: "/home/you/code/api-server", messages: [["user", "Checkout returns 502s since this morning. Find out why."], ["assistant", "I'll split it: Codex scans the gateway log for the 502 pattern, Claude compares the keep-alive settings."]] },
];
async function seedThreads(page: Page) {
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: THREADS });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  const [notes, nightly, slack, docs, gw] = threads as string[];
  await expect(page.getByTestId(`thread-row-${gw}`)).toBeVisible();
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami", session: gw },
      { event: "tool.start", bot: "kami", session: gw, tool_id: "d1", name: "delegate_task", detail: "gateway logs (+1 more)" },
      { event: "subagent", bot: "kami", session: gw, id: "sa-1", index: 0, count: 2, delegation: "deleg_gw", state: "running", goal: "Find the 502 pattern in gateway.log", agent: "codex", model: "gpt-5.2-codex", tool: "terminal", step: "rg ' 502 ' logs/gateway.log" },
      { event: "subagent", bot: "kami", session: gw, id: "sa-2", index: 1, count: 2, delegation: "deleg_gw", state: "running", goal: "Compare keep-alive settings", agent: "claude", model: "claude-opus-5-5" },
      { event: "turn.start", bot: "kami", session: docs },
      { event: "approval.request", bot: "kami", session: docs, request_id: "ap-docs", title: "Run shell command", command: "pnpm build:docs", choices: ["once", "deny"] },
      { event: "turn.start", bot: "kami", session: slack },
      { event: "message", bot: "kami", session: slack, id: "m-slack", text: "Here are three tighter versions of the alert." },
      { event: "turn.end", bot: "kami", session: slack, outcome: "done" },
      { event: "turn.start", bot: "kami", session: nightly },
      { event: "turn.end", bot: "kami", session: nightly, outcome: "error", error: "gateway timeout" },
    ],
  });
  await expect(page.getByTestId(`thread-row-${gw}`)).toHaveAttribute("data-state", "running");
  return { notes, nightly, slack, docs, gw };
}

/** Friren's last turn failed (its dock tile's red dot when it scrolls out of view). */
async function failFriren() {
  await mock("mock.manual", { bot: "friren" });
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "friren" }, { event: "turn.end", bot: "friren", outcome: "error", error: "provider timeout" }] });
  await mock("mock.manual", { bot: "friren", on: false });
}

/** Every bot row and thread row of BOTS, and every folder header and row of TERMINALS, is drawn whole or not at all
 *  at its list's bottom edge (the list's box less its bottom clip); at the top edge only when scrolled past. */
async function noCutRows(page: Page) {
  // settled: a scroll that brings the dock in re-lays the regions out over a frame or two
  await expect.poll(() => cutRows(page), { message: "rows drawn cut at a region edge", timeout: 3000 }).toEqual([]);
}
async function cutRows(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const bad: string[] = [];
    for (const list of document.querySelectorAll<HTMLElement>(".side-sec > .bot-list")) {
      const box = list.getBoundingClientRect();
      // inset(top right bottom left), as the browser writes it back (it drops repeated values: "0px 0px 56px")
      const v = (/inset\(([^)]*)\)/.exec(getComputedStyle(list).clipPath)?.[1] ?? "").trim().split(/\s+/).map(parseFloat).filter((n) => !Number.isNaN(n));
      const bottom = box.bottom - (v.length ? (v[2] ?? v[0] ?? 0) : 0);
      for (const r of list.querySelectorAll<HTMLElement>(".bot-w > .bot, .th-row, .tg-h, .ss-row")) {
        const b = r.getBoundingClientRect();
        if (b.height === 0) continue;
        // a row partly above the top edge is one the person scrolled past (the top shadow says so); the bottom edge
        // never cuts one
        const whole = (b.top >= box.top - 0.5 || list.scrollTop > 0) && b.bottom <= bottom + 0.5;
        const out = b.bottom <= box.top + 0.5 || b.top >= bottom - 0.5;
        if (!whole && !out) bad.push(`${r.closest("[data-testid]")?.getAttribute("data-testid")} ${Math.round(b.top)}..${Math.round(b.bottom)} in ${Math.round(box.top)}..${Math.round(bottom)} (box end ${Math.round(box.bottom)}, clip "${getComputedStyle(list).clipPath}", more ${list.dataset.more ?? "-"})`);
      }
    }
    return bad;
  });
}

test.beforeEach(async () => {
  await mock("mock.reset");
});
test.afterEach(async () => {
  await mock("mock.manual", { bot: "kami", on: false });
});

test.describe("shots", () => {
  test.use({ deviceScaleFactor: 2, viewport: { width: 1440, height: 900 } });
  for (const theme of ["dark", "light"] as const) {
    test(`shots: sidebar (${theme})${theme === "dark" ? ", plus menu, terminal open, threads chat, folders, bot reveal" : ""}`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      test.setTimeout(180_000);
      await open(page, { theme });
      await seedThreads(page);
      const ids = await seed(page);
      await failFriren();
      // BOTS at its top: every bot in view, so no dock
      await expect(page.getByTestId("dock")).toHaveCount(0);
      // output flowing in both CLIs: their arcs turn
      await out(page, ids.codex, "\x1b[2m• Running\x1b[0m pnpm test payments\r\n");
      await out(page, ids.claude, "");
      await expect(page.getByTestId(`session-${ids.codex}`)).toHaveAttribute("data-term-status", "busy");
      await page.mouse.move(900, 600);
      await expect(page.getByTestId(`session-${ids.claude}`)).toBeInViewport();
      await noCutRows(page);
      await shot(page, `sidebar-${theme}`);
      // Kami's five threads, one per state, as chat cards (tidy, 2026-11-16)
      const tree = (await page.getByTestId("bot-row-kami").boundingBox())!;
      const side = (await page.getByTestId("sidebar").boundingBox())!;
      await shot(page, `threads-rows-${theme}`, { x: side.x, y: tree.y - 8, width: side.width, height: tree.height + 16 });
      if (theme !== "dark") return;
      // a shorter window: each region ends on a whole row, no blank band
      await page.setViewportSize({ width: 1440, height: 760 });
      await page.waitForTimeout(400);
      await noCutRows(page);
      await shot(page, "sidebar-dark-760");
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.waitForTimeout(400);
      await shot(page, "terminal-open");
      await page.getByTestId("session-new").click();
      await expect(page.getByTestId("session-agent-shell")).toBeVisible();
      await shot(page, "plus-menu");
      await page.keyboard.press("Escape");
      // collapsed folders: api-server collapsed shows its count and live summary (Grok running in its Shell)
      await fg(page, ids.shell, "grok");
      await out(page, ids.shell, GROK_SCREEN);
      await page.locator(`[data-testid=term-group][data-cwd="${API}"]`).getByTestId("term-group-toggle").click();
      await expect(page.locator(`[data-testid=term-group][data-cwd="${API}"]`).getByTestId("term-group-running")).toBeVisible();
      await page.mouse.move(900, 600);
      await noCutRows(page);
      await shot(page, "terminals-folders-collapsed");
      // a thread chat with the agent chat view: Kami splits the release-notes thread between Codex and Claude, live
      const rel = page.locator('[data-testid^="thread-row-"]').filter({ hasText: "Release notes" });
      await rel.getByTestId("thread-open").click();
      await expect(page.getByTestId("thread-chat")).toBeVisible();
      const relId = (await rel.getAttribute("data-testid"))!.slice("thread-row-".length);
      await mock("mock.emit", {
        events: [
          { event: "turn.start", bot: "kami", session: relId },
          { event: "tool.start", bot: "kami", session: relId, tool_id: "r1", name: "delegate_task", detail: "changelog since 2.3 (+1 more)" },
          { event: "subagent", bot: "kami", session: relId, id: "sr-1", index: 0, count: 2, delegation: "deleg_rel", state: "running", goal: "Collect the merged PRs since 2.3", agent: "codex", model: "gpt-5.2-codex", tool: "terminal", step: "gh pr list --state merged --search 'merged:>2026-10-30'" },
          { event: "subagent", bot: "kami", session: relId, id: "sr-2", index: 1, count: 2, delegation: "deleg_rel", state: "running", goal: "Draft the upgrade notes", agent: "claude", model: "claude-opus-5-5" },
        ],
      });
      await page.waitForTimeout(1500);
      await mock("mock.emit", {
        events: [{ event: "subagent", bot: "kami", session: relId, id: "sr-2", index: 1, count: 2, delegation: "deleg_rel", state: "done", goal: "Draft the upgrade notes", agent: "claude", model: "claude-opus-5-5", summary: "Upgrade notes drafted: config key renamed, one migration" }],
      });
      await expect(rel).toHaveAttribute("data-state", "running");
      await page.mouse.move(900, 600);
      await shot(page, "threads-chat");
    });
  }

  test("shots: the dark sidebar with BOTS scrolled: the bots gone above are the dock's tiles (bots only)", async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    test.setTimeout(180_000);
    const { bots } = await mock("mock.manyBots", { n: 6 });
    await open(page, { theme: "dark", roster: ["kami", "friren", "default", "omh-tui", ...(bots as string[])] });
    await seedThreads(page);
    await seed(page);
    await failFriren();
    const botList = page.getByTestId("side-bots").locator(".bot-list");
    await expect(page.getByTestId("dock")).toHaveCount(0);
    // scrolled until Kami, Friren and the next bot are above the list's top
    await page.evaluate(() => {
      const list = document.querySelector('[data-testid="side-bots"] .bot-list') as HTMLElement;
      const rows = [...list.querySelectorAll(':scope > [data-testid^="bot-row-"]')];
      list.scrollTop += rows[3]!.getBoundingClientRect().top - list.getBoundingClientRect().top;
    });
    await expect.poll(() => page.getByTestId("dock").locator(".dk-t").count()).toBe(3);
    await expect(page.getByTestId("dock-tile-bot:friren")).toHaveAttribute("data-state", "failed");
    await expect(page.locator('[data-testid^="dock-tile-term:"]')).toHaveCount(0);
    expect(await botList.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    await page.mouse.move(900, 600);
    await noCutRows(page);
    await shot(page, "sidebar-dark-scrolled");
  });

  test("shots: many rows (12 bots x 6 threads, 15 terminals, both scrolled midway) and the bot reveal", async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    test.setTimeout(240_000);
    const { bots } = await mock("mock.manyBots", { n: 12 });
    const names = ["Billing fixes", "Flaky e2e on CI", "Onboarding copy", "Search ranking", "Pricing page A/B", "Deploy checklist"];
    for (const b of bots as string[]) await mock("mock.threads", { bot: b, threads: names.map((title, i) => ({ title, ago: (i + 1) * 600 })) });
    await open(page, { roster: ["kami", ...(bots as string[])] });
    const kinds = ["claude", "codex", "shell"];
    const folders = [WEB, API, NOTES];
    for (let i = 0; i < 15; i++) {
      const folder = folders[Math.floor(i / 5)]!;
      const id = await newTerm(page, kinds[i % 3]!, folder);
      if (kinds[i % 3] === "shell") await out(page, id, SHELL_SCREEN(folder.split("/").pop()!));
    }
    await page.mouse.move(900, 600);
    const botList = page.getByTestId("side-bots").locator(".bot-list");
    const termList = page.getByTestId("side-sessions").locator(".ss-list");
    // BOTS first (the dock comes in, TERMINALS gets shorter), then TERMINALS by the wheel, as a person scrolls it
    await botList.evaluate((el) => (el.scrollTop = (el.scrollHeight - el.clientHeight) / 2));
    await page.waitForTimeout(300);
    const tb = (await termList.boundingBox())!;
    await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2);
    await page.mouse.wheel(0, 1);
    await termList.evaluate((el) => (el.scrollTop = (el.scrollHeight - el.clientHeight) / 2));
    await page.mouse.move(900, 600);
    await page.waitForTimeout(300);
    const mid = await Promise.all([botList, termList].map((l) => l.evaluate((el) => ({ top: el.scrollTop, max: el.scrollHeight - el.clientHeight, more: el.dataset.more ?? null }))));
    for (const m of mid) {
      expect(m.top).toBeGreaterThan(0);
      expect(m.top).toBeLessThan(m.max);
      expect(m.more).toBe("both");
    }
    // BOTS scrolled midway: the bots gone out of view at the top are the dock's tiles, bots only
    await expect(page.getByTestId("dock").locator(".dk-t").first()).toBeVisible();
    await expect(page.locator('[data-testid^="dock-tile-term:"]')).toHaveCount(0);
    await noCutRows(page);
    await shot(page, "many-rows-scroll");
    await botList.evaluate((el) => (el.scrollTop = 0));
    // at the top of BOTS: no dock
    await expect(page.getByTestId("dock")).toHaveCount(0);
    await shot(page, "bot-reveal-before");
    await page.getByTestId("bot-bot06").click();
    await expect(botList).toHaveAttribute("data-revealed", "bot06");
    await page.mouse.move(900, 600);
    await shot(page, "bot-reveal-after");
  });
});

test("session-fg: shell icon -> Claude mark with the live frame and tooltip -> shell again; two terminals follow their own CLIs", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  const a = await newTerm(page, "shell", WEB);
  const b = await newTerm(page, "shell", API);
  const mark = (id: string) => page.getByTestId(`session-${id}`).getByTestId("term-row-mark");
  await expect(mark(a)).toHaveAttribute("data-agent", "shell");
  await expect(mark(a)).not.toHaveAttribute("data-live", "true");
  await fg(page, a, "claude");
  await expect(mark(a)).toHaveAttribute("data-agent", "claude");
  await expect(mark(a)).toHaveAttribute("data-live", "true");
  await expect(mark(a)).toHaveAttribute("title", "Claude Code running");
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-meta")).toContainText("claude");
  // the other terminal keeps its own: codex there, claude here
  await fg(page, b, "codex");
  await expect(mark(b)).toHaveAttribute("data-agent", "codex");
  await expect(mark(a)).toHaveAttribute("data-agent", "claude");
  // the CLI quits: back to the shell icon, no frame colour, no tooltip
  await fg(page, a, null);
  await expect(mark(a)).toHaveAttribute("data-agent", "shell");
  await expect(mark(a)).not.toHaveAttribute("data-live", "true");
  await expect(mark(a)).not.toHaveAttribute("title", /running/);
  await expect(mark(b)).toHaveAttribute("data-agent", "codex");
  // an unknown program the shell names gets the neutral mark, never a company's logo
  await fg(page, a, "htop");
  await expect(mark(a)).toHaveAttribute("data-agent", "generic");
  // the open session's header follows too
  await page.getByTestId(`session-${b}`).locator(".ss-open").click();
  await expect(page.getByTestId("header").getByTestId("term-row-mark")).toHaveAttribute("data-agent", "codex");
  // the session ends: no CLI is in front any more
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type("exit\r");
  await expect(page.getByTestId(`session-${b}`)).toHaveAttribute("data-term-status", "ok");
  await expect(mark(b)).toHaveAttribute("data-agent", "shell");
});

test("session-fg on the bottom panel: the tab shows its shell's foreground CLI", async ({ page }) => {
  await open(page);
  await page.locator("body").click({ position: { x: 900, y: 450 } });
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  const calls = () => page.evaluate(() => ((window as any).__omherShellCalls ?? []) as { op: string; id: number }[]);
  await expect.poll(async () => (await calls()).some((c) => c.op === "start")).toBe(true);
  const id = (await calls()).find((c) => c.op === "start")!.id;
  const tab = page.getByTestId("termpanel-tab").first();
  await expect(tab.getByTestId("term-row-mark")).toHaveCount(0);
  await page.evaluate((p) => (window as any).__omherEmitSessionFg({ id: p, agent: "claude" }), id);
  await expect(tab.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
  await expect(tab.locator(".termpanel-tab-name")).toHaveAttribute("title", /^Claude Code running/);
  await page.evaluate((p) => (window as any).__omherEmitSessionFg({ id: p, agent: null }), id);
  await expect(tab.getByTestId("term-row-mark")).toHaveCount(0);
});

test("reduced motion: the live frame, the status arc, the dock ring and the dock's entrance stand still", async ({ page }) => {
  test.setTimeout(60_000);
  const { bots } = await mock("mock.manyBots", { n: 12 });
  await open(page, { reduced: true, roster: ["kami", ...(bots as string[])] });
  await page.setViewportSize({ width: 1280, height: 700 });
  const a = await newTerm(page, "shell", WEB);
  await fg(page, a, "claude");
  await out(page, a, "Reading src/checkout/cart.ts\r\n");
  await expect(page.getByTestId(`session-${a}`)).toHaveAttribute("data-term-status", "busy");
  // Kami answering, then scrolled out of view: its tile has the running ring
  await mock("mock.manual", { bot: "kami" });
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }] });
  await page.getByTestId("side-bots").locator(".bot-list").evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect(page.getByTestId("dock-tile-bot:kami")).toHaveAttribute("data-state", "running");
  const anim = await page.evaluate((id) => {
    const row = document.querySelector(`[data-testid="session-${id}"]`)!;
    const tile = document.querySelector('[data-testid="dock-tile-bot:kami"]')!;
    return {
      arc: getComputedStyle(row.querySelector(".tst svg")!).animationName,
      frame: getComputedStyle(row.querySelector(".trm")!, "::after").animationName,
      ring: getComputedStyle(tile, "::after").animationName,
      ringOn: getComputedStyle(tile, "::after").content,
      dock: getComputedStyle(document.querySelector('[data-testid="dock"]')!).animationName,
    };
  }, a);
  expect(anim).toEqual({ arc: "none", frame: "none", ring: "none", ringOn: '""', dock: "none" });
  // back at the top: gone at once
  await page.getByTestId("side-bots").locator(".bot-list").evaluate((el) => (el.scrollTop = 0));
  await expect(page.getByTestId("dock")).toHaveCount(0);
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", outcome: "done" }] });
});

test("status glyph from the session events: arc while output flows, check on exit 0, x on exit 3", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const a = await newTerm(page, "codex", WEB);
  const row = page.getByTestId(`session-${a}`);
  await out(page, a, "• Ran pnpm test\r\n");
  await expect(row).toHaveAttribute("data-term-status", "busy");
  await expect(row).toHaveAttribute("data-term-status", "idle", { timeout: 6000 });
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type("after 10 exit 3\r");
  await expect(row).toHaveAttribute("data-term-status", "err");
  const b = await newTerm(page, "claude", WEB);
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type("exit\r");
  await expect(page.getByTestId(`session-${b}`)).toHaveAttribute("data-term-status", "ok");
});

test("the open session is always listed and in view, with a short TERMINALS region", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 760 });
  await open(page);
  const ids: string[] = [];
  for (let i = 0; i < 6; i++) ids.push(await newTerm(page, i % 2 ? "codex" : "claude", i % 3 === 0 ? WEB : API));
  // the first one opened, then the window gets shorter under it
  await page.getByTestId(`session-${ids[0]}`).locator(".ss-open").click();
  await page.setViewportSize({ width: 1440, height: 640 });
  await page.mouse.move(900, 600);
  const listed = await page.evaluate(() => [...document.querySelectorAll('[data-testid="session-list"] .ss-row.tr')].map((e) => e.getAttribute("data-testid")));
  for (const id of ids) expect(listed).toContain(`session-${id}`);
  const row = page.getByTestId(`session-${ids[0]}`);
  await expect(row).toHaveClass(/active/);
  // inside the TERMINALS list's own box, not under the dock
  const inside = await row.evaluate((el) => {
    const l = el.closest(".ss-list")!.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return r.top >= l.top - 0.5 && r.bottom <= l.bottom + 0.5;
  });
  expect(inside).toBe(true);
});

test("folders: collapse persists across a reload; collapsed header shows count and live summary; opening a session reveals its folder", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page, { keep: true });
  const a = await newTerm(page, "claude", API);
  const b = await newTerm(page, "shell", API);
  await newTerm(page, "codex", WEB);
  const api = page.locator(`[data-testid=term-group][data-cwd="${API}"]`);
  await expect(api.getByTestId("term-group-toggle")).toHaveAttribute("aria-expanded", "true");
  await out(page, a, "Reading src/routes/orders.ts\r\n");
  await api.getByTestId("term-group-toggle").click();
  await expect(api).toHaveAttribute("data-collapsed", "true");
  await expect(api.locator(".ss-row")).toHaveCount(0);
  // the count says what it counts, and the running part has its own words: "1 running · 2 sessions"
  await expect(api.getByTestId("term-group-count")).toHaveText("2 sessions");
  await expect(api.getByTestId("term-group-running")).toHaveText("1 running");
  await expect(api.getByTestId("term-group-summary")).toContainText("1 running·2 sessions");
  // the folder's name keeps its whole line beside the summary (never "api…")
  expect(await api.locator(".tg-n").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(api.getByTestId("term-group-summary")).toHaveAttribute("data-busy", "true");
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("omher.term.folders") ?? "{}").collapsed)).toEqual([API]);
  await page.waitForTimeout(600);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(page.locator(`[data-testid=term-group][data-cwd="${API}"]`)).toHaveAttribute("data-collapsed", "true");
  // opening a session of the collapsed folder (⌘⇧] steps into it) opens the folder (reveal) and shows the row
  await expect(page.getByTestId(`session-${b}`)).toHaveCount(0);
  const mod = process.platform === "darwin" ? "Meta" : "Control";
  for (let i = 0; i < 4 && !(await page.getByTestId(`session-${b}`).count()); i++) await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(page.locator(`[data-testid=term-group][data-cwd="${API}"]`)).not.toHaveAttribute("data-collapsed", "true");
  await expect(page.getByTestId(`session-${b}`)).toHaveClass(/active/);
  await expect(page.getByTestId(`session-${b}`)).toBeInViewport();
});

test("folders: Collapse all / Expand all, the header menu, drag reorder persists", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page, { keep: true });
  await newTerm(page, "claude", WEB);
  await newTerm(page, "codex", API);
  await newTerm(page, "shell", NOTES);
  const order = () => page.getByTestId("term-group").evaluateAll((els) => els.map((e) => e.getAttribute("data-cwd")));
  const first = await order();
  expect(first).toHaveLength(3);
  // collapse all, expand all
  await page.getByTestId("term-collapse-all").click();
  await expect(page.locator('[data-testid=term-group][data-collapsed="true"]')).toHaveCount(3);
  await expect(page.getByTestId("term-collapse-all")).toHaveAttribute("data-all", "collapsed");
  await page.getByTestId("term-collapse-all").click();
  await expect(page.locator('[data-testid=term-group][data-collapsed="true"]')).toHaveCount(0);
  // right-click a header: Collapse others leaves only that folder open
  const target = page.locator(`[data-testid=term-group][data-cwd="${API}"]`);
  await target.getByTestId("term-group-head").click({ button: "right" });
  await expect(page.getByTestId("term-folder-menu")).toBeVisible();
  await expect(page.getByTestId("term-folder-new")).toBeVisible();
  await expect(page.getByTestId("term-folder-reveal")).toBeVisible();
  await page.getByTestId("term-folder-others").click();
  await expect(page.locator('[data-testid=term-group][data-collapsed="true"]')).toHaveCount(2);
  await expect(target).not.toHaveAttribute("data-collapsed", "true");
  // New terminal here: a Shell in that folder
  await target.getByTestId("term-group-head").click({ button: "right" });
  await page.getByTestId("term-folder-new").click();
  await expect(target.locator(".ss-row.tr")).toHaveCount(2);
  // drag the last folder header to the top
  const last = page.getByTestId("term-group").last();
  const lastCwd = await last.getAttribute("data-cwd");
  const from = (await last.getByTestId("term-group-head").boundingBox())!;
  const to = (await page.getByTestId("term-group").first().getByTestId("term-group-head").boundingBox())!;
  await page.mouse.move(from.x + 40, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + 44, from.y + 6, { steps: 3 });
  await page.mouse.move(to.x + 40, to.y + 4, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await order())[0]).toBe(lastCwd);
  const saved = await order();
  await page.waitForTimeout(600);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(order).toEqual(saved);
});

test("bot click: its chat opens and its row slides to the top of BOTS with its threads below; TERMINALS stays", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const { bots } = await mock("mock.manyBots", { n: 12 });
  for (const b of bots as string[]) await mock("mock.threads", { bot: b, threads: Array.from({ length: 3 }, (_, i) => ({ title: `${b} thread ${i + 1}`, ago: (i + 1) * 600 })) });
  await open(page, { roster: ["kami", ...(bots as string[])] });
  for (let i = 0; i < 8; i++) await newTerm(page, i % 2 ? "codex" : "shell", i % 2 ? WEB : API);
  const botList = page.getByTestId("side-bots").locator(".bot-list");
  const termList = page.getByTestId("side-sessions").locator(".ss-list");
  await botList.evaluate((el) => (el.scrollTop = 0));
  await termList.evaluate((el) => (el.scrollTop = 0));
  const tTop = await termList.evaluate((el) => el.scrollTop);
  await expect(page.getByTestId("dock")).toHaveCount(0);
  // a bot in the middle: it rises to the top, smoothly (several frames between the first and last scrollTop)
  const samples = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="side-bots"] .bot-list') as HTMLElement;
    const seen: number[] = [];
    const watch = () => {
      seen.push(list.scrollTop);
      if (seen.length < 40) requestAnimationFrame(watch);
    };
    requestAnimationFrame(watch);
    (document.querySelector('[data-testid="bot-bot05"]') as HTMLElement).click();
    return new Promise<number[]>((res) => setTimeout(() => res(seen), 700));
  });
  expect(new Set(samples).size).toBeGreaterThan(3);
  await expect(page.getByTestId("bot-bot05")).toHaveAttribute("aria-current", "true");
  await expect(botList).toHaveAttribute("data-revealed", "bot05");
  const gap = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="side-bots"] .bot-list')!.getBoundingClientRect();
    const row = document.querySelector('[data-testid="bot-row-bot05"]')!.getBoundingClientRect();
    return row.top - list.top;
  });
  expect(Math.abs(gap)).toBeLessThanOrEqual(2);
  // its threads are under it, in view
  await expect(page.getByTestId("threads-bot05").locator('[data-testid^="thread-row-"]').first()).toBeInViewport();
  // TERMINALS did not scroll; the bots now above bot05 are the dock's tiles
  expect(await termList.evaluate((el) => el.scrollTop)).toBe(tTop);
  await expect.poll(() => tileNames(page)).toEqual(await namesBefore(page, "bot05"));
  // from a dock tile, too: BOTS at its end, then bot02's tile
  await botList.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect(page.getByTestId("dock-tile-bot:bot02")).toBeVisible();
  await page.getByTestId("dock-tile-bot:bot02").click();
  await expect(botList).toHaveAttribute("data-revealed", "bot02");
  await expect(page.getByTestId("bot-bot02")).toHaveAttribute("aria-current", "true");
  const gap2 = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="side-bots"] .bot-list')!.getBoundingClientRect();
    return document.querySelector('[data-testid="bot-row-bot02"]')!.getBoundingClientRect().top - list.top;
  });
  expect(Math.abs(gap2)).toBeLessThanOrEqual(2);
  await expect.poll(() => tileNames(page)).toEqual(await namesBefore(page, "bot02"));
  await page.getByTestId("bot-bot09").click();
  await expect(botList).toHaveAttribute("data-revealed", "bot09");
  // a thread click does not move BOTS when its row is in view
  const before = await botList.evaluate((el) => el.scrollTop);
  await page.getByTestId("threads-bot09").locator('[data-testid="thread-open"]').first().click();
  await expect(page.getByTestId("thread-chat")).toBeVisible();
  expect(await botList.evaluate((el) => el.scrollTop)).toBe(before);
});

test("bot click under reduced motion jumps to the top at once", async ({ page }) => {
  test.setTimeout(60_000);
  const { bots } = await mock("mock.manyBots", { n: 12 });
  await open(page, { roster: ["kami", ...(bots as string[])], reduced: true });
  await page.setViewportSize({ width: 1440, height: 700 });
  const botList = page.getByTestId("side-bots").locator(".bot-list");
  const samples = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="side-bots"] .bot-list') as HTMLElement;
    list.scrollTop = 0;
    const seen: number[] = [];
    const watch = () => {
      seen.push(list.scrollTop);
      if (seen.length < 30) requestAnimationFrame(watch);
    };
    requestAnimationFrame(watch);
    (document.querySelector('[data-testid="bot-bot06"]') as HTMLElement).click();
    return new Promise<number[]>((res) => setTimeout(() => res(seen), 600));
  });
  // only the start and the end: no frames in between
  expect(new Set(samples).size).toBeLessThanOrEqual(2);
  await expect(botList).toHaveAttribute("data-revealed", "bot06");
});

/** The bot names of the dock's tiles, in order. */
const tileNames = (page: Page) =>
  page.getByTestId("dock").locator(".dk-t").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("dock-tile-bot:", "")));
/** The bots listed above `bot` in BOTS, in list order. */
const namesBefore = (page: Page, bot: string) =>
  page.evaluate((b) => {
    const names = [...document.querySelectorAll('[data-testid="side-bots"] .bot-list > [data-testid^="bot-row-"]')].map((e) => e.getAttribute("data-testid")!.slice("bot-row-".length));
    return names.slice(0, names.indexOf(b));
  }, bot);
/** Scroll BOTS so `bot`'s row is at the list's top: exactly the bots above it are out of view. */
const scrollToRow = (page: Page, bot: string) =>
  page.evaluate((b) => {
    const list = document.querySelector('[data-testid="side-bots"] .bot-list') as HTMLElement;
    const row = document.querySelector(`[data-testid="bot-row-${b}"]`)!;
    list.scrollTop += row.getBoundingClientRect().top - list.getBoundingClientRect().top;
  }, bot);

test("the dock holds bots only, and only the bots scrolled out of view at the top; a tile reveals its bot", async ({ page }) => {
  test.setTimeout(90_000);
  const { bots } = await mock("mock.manyBots", { n: 12 });
  await open(page, { roster: ["kami", ...(bots as string[])] });
  await page.setViewportSize({ width: 1440, height: 760 });
  // terminals running Claude Code and Codex: never a tile
  await newTerm(page, "claude", WEB);
  await newTerm(page, "codex", WEB);
  const botList = page.getByTestId("side-bots").locator(".bot-list");
  // at the top: no dock in the page at all
  await botList.evaluate((el) => (el.scrollTop = 0));
  await page.waitForTimeout(300);
  await expect(page.getByTestId("dock")).toHaveCount(0);
  // three bots leave the top: exactly those three tiles, in list order
  const order = await namesBefore(page, "bot12");
  await scrollToRow(page, order[3]!);
  await expect.poll(() => tileNames(page)).toEqual(order.slice(0, 3));
  await expect(page.locator('[data-testid^="dock-tile-term:"]')).toHaveCount(0);
  // a failed turn and an open ask show on the tiles
  await mock("mock.manual", { bot: order[0] });
  await mock("mock.emit", { events: [{ event: "turn.start", bot: order[0] }, { event: "approval.request", bot: order[0], request_id: "ap-d", title: "Run", command: "ls", choices: ["once", "deny"] }] });
  await expect(page.getByTestId(`dock-tile-bot:${order[0]}`).getByTestId("dock-dot")).toHaveAttribute("data-dot", "needs");
  await mock("mock.emit", { events: [{ event: "turn.end", bot: order[0], outcome: "error", error: "boom" }] });
  await expect(page.getByTestId(`dock-tile-bot:${order[0]}`).getByTestId("dock-dot")).toHaveAttribute("data-dot", "failed");
  await mock("mock.manual", { bot: order[0], on: false });
  // keyboard: one tab stop, arrows move
  await page.getByTestId(`dock-tile-bot:${order[0]}`).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId(`dock-tile-bot:${order[1]}`)).toBeFocused();
  // a tile click is the bot click: its chat opens, its row rises to the top, and the dock follows (one tile fewer)
  await page.getByTestId(`dock-tile-bot:${order[1]}`).click();
  await expect(page.getByTestId(`bot-${order[1]}`)).toHaveAttribute("aria-current", "true");
  await expect(botList).toHaveAttribute("data-revealed", order[1]!);
  await expect.poll(() => tileNames(page)).toEqual(order.slice(0, 1));
  // nothing is stored for the dock
  expect(await page.evaluate(() => localStorage.getItem("omher.dock"))).toBeNull();
  // back at the top: the dock leaves (after its fade)
  await botList.evaluate((el) => (el.scrollTop = 0));
  await expect(page.getByTestId("dock")).toHaveCount(0);
  // the terminal rows' menu has no pin
  await page.locator(".ss-row.tr").first().click({ button: "right" });
  await expect(page.getByTestId("session-row-menu")).toBeVisible();
  await expect(page.getByTestId("session-pin")).toHaveCount(0);
  await page.keyboard.press("Escape");
  // nor the bots' menu
  await page.getByTestId("bot-kami").click({ button: "right" });
  await expect(page.getByTestId("row-menu")).toBeVisible();
  await expect(page.getByTestId("row-menu")).not.toContainText(/dock/i);
});

test("no row is drawn cut at a region's end: a collapsed bot under an expanded one, rows at the TERMINALS edge", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await seedThreads(page);
  for (let i = 0; i < 9; i++) await newTerm(page, i % 3 === 0 ? "claude" : i % 3 === 1 ? "codex" : "shell", [WEB, API, NOTES][i % 3]!);
  await page.mouse.move(900, 600);
  await page.waitForTimeout(300);
  const botList = page.getByTestId("side-bots").locator(".bot-list");
  const termList = page.getByTestId("side-sessions").locator(".ss-list");
  await noCutRows(page);
  // at every scroll step of both lists
  for (const l of [botList, termList]) {
    const max = await l.evaluate((el) => el.scrollHeight - el.clientHeight);
    for (let y = 0; y <= max; y += 23) {
      await l.evaluate((el, v) => (el.scrollTop = v), y);
      await page.waitForTimeout(40);
      await noCutRows(page);
    }
  }
  // a short window, too
  await page.setViewportSize({ width: 1440, height: 640 });
  await botList.evaluate((el) => (el.scrollTop = 0));
  await page.waitForTimeout(200);
  await noCutRows(page);
});

test("one running colour: a working thread's spinner is the running terminals' amber", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const { gw } = await seedThreads(page);
  const a = await newTerm(page, "shell", WEB);
  await fg(page, a, "claude");
  const colours = await page.evaluate(([th, id]) => {
    const glyph = document.querySelector(`[data-testid="thread-row-${th}"] [data-testid="thread-glyph"]`)!;
    const mark = document.querySelector(`[data-testid="session-${id}"] .trm`)!;
    return { thread: getComputedStyle(glyph).color, term: getComputedStyle(mark).getPropertyValue("--term-run").trim(), run: getComputedStyle(glyph).getPropertyValue("--term-run").trim() };
  }, [gw, a] as const);
  expect(colours.run).toBe(colours.term);
  // the theme's running amber (#f2b705 dark, #c48a00 light), never the bots' pink accent
  expect(["rgb(242, 183, 5)", "rgb(196, 138, 0)"]).toContain(colours.thread);
});

test("the usage meter's state is a short bar, never a dot (a red dot means a failed turn only)", async ({ page }) => {
  await open(page);
  const marks = page.locator(".usage-dot");
  await expect(page.getByTestId("usage")).toBeVisible();
  for (const el of await marks.all()) {
    const box = (await el.boundingBox())!;
    expect(box.width).toBeGreaterThan(box.height * 2);
  }
});

test("the dock: 4 tiles fill 2x2 (no lone tile); the running ring is centred inside its tile", async ({ page }) => {
  test.setTimeout(60_000);
  const { bots } = await mock("mock.manyBots", { n: 12 });
  await open(page, { roster: ["kami", ...(bots as string[])] });
  await page.setViewportSize({ width: 1440, height: 760 });
  const order = await namesBefore(page, "bot12");
  // the first bot answering
  await mock("mock.manual", { bot: order[0] });
  await mock("mock.emit", { events: [{ event: "turn.start", bot: order[0] }] });
  await scrollToRow(page, order[4]!);
  await expect.poll(() => tileNames(page)).toEqual(order.slice(0, 4));
  const boxes = await page.getByTestId("dock").locator(".dk-t").evaluateAll((els) => els.map((e) => e.getBoundingClientRect()).map((r) => ({ x: r.x, y: r.y, w: r.width })));
  expect(boxes).toHaveLength(4);
  expect(new Set(boxes.map((r) => r.y)).size).toBe(2);
  expect(Math.abs(boxes[0]!.w - boxes[3]!.w)).toBeLessThanOrEqual(1);
  const ring = await page.getByTestId(`dock-tile-bot:${order[0]}`).evaluate((el) => {
    const t = el.getBoundingClientRect();
    const cs = getComputedStyle(el, "::after");
    const top = parseFloat(cs.top);
    const left = parseFloat(cs.left);
    const w = parseFloat(cs.width);
    const h = parseFloat(cs.height);
    return { on: el.classList.contains("ring"), dx: left + w / 2 - t.width / 2, dy: top + h / 2 - t.height / 2, inTop: top, inLeft: left, inBottom: t.height - (top + h) };
  });
  expect(ring.on).toBe(true);
  expect(Math.abs(ring.dx)).toBeLessThanOrEqual(1);
  expect(Math.abs(ring.dy)).toBeLessThanOrEqual(1);
  expect(ring.inTop).toBeGreaterThanOrEqual(4);
  expect(ring.inBottom).toBeGreaterThanOrEqual(4);
  await mock("mock.emit", { events: [{ event: "turn.end", bot: order[0], outcome: "done" }] });
  await mock("mock.manual", { bot: order[0], on: false });
});
