// spacing (run omher-terminals, 2026-11-16): the sidebar gives its lists more room and the TERMINALS sessions read
// as separate cards (Orca's feel, not its look).
// measure: list area, whole bot / thread rows and whole session cards at 900 and 760pt windows, with the few-rows
// seed and the many-rows seed (12 bots x 6 threads, 15 terminals); OMHER_MEASURE=<file> appends them as JSON lines.
import { expect, test, type Page } from "@playwright/test";
import { appendFileSync } from "node:fs";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const MEASURE = process.env.OMHER_MEASURE || "";

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

const WEB = "/home/you/code/web-app";
const API = "/home/you/code/api-server";
const NOTES = "/home/you/code/notes";

async function open(page: Page, o: { roster?: string[] } = {}) {
  await page.addInitScript(
    ([roster]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders", "omher.side.split"]) localStorage.removeItem(k);
        sessionStorage.setItem("__kept", "1");
      }
      if (roster) localStorage.setItem("omher.roster", JSON.stringify(roster));
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = "/home/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "grok", "opencode", "omh", "pi", "omp", "omo"];
      w.__omherBranches = { "/home/you/code/web-app": "feature/checkout-flow", "/home/you/code/api-server": "main", "/home/you/code/notes": "" };
    },
    [o.roster ?? null] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

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
  await expect.poll(() => page.evaluate((b) => (window as any).__omherSessions.getState().list.find((r: { id: string }) => !b.includes(r.id))?.id ?? null, before)).not.toBeNull();
  const id = await page.evaluate((b) => (window as any).__omherSessions.getState().list.find((r: { id: string }) => !b.includes(r.id)).id as string, before);
  await expect.poll(() => pty(page, id)).not.toBeNull();
  await expect(page.locator(".xterm-rows").last()).toContainText(/\S/);
  await page.waitForTimeout(60);
  return id;
}
const pty = (page: Page, id: string) => page.evaluate((i) => (window as any).__omherSessions.ptyOf(i) as number | null, id);
async function out(page: Page, id: string, text: string) {
  const p = await pty(page, id);
  expect(await page.evaluate(([p, t]) => (window as any).__omherMockOut(p, t), [p, text] as const)).toBe(true);
}

/** The sidebar's regions and what each list shows whole (the bottom clip of edgeFade counted). */
function measure(page: Page) {
  return page.evaluate(() => {
    const r = (el: Element | null) => (el ? el.getBoundingClientRect() : null);
    const bl = document.querySelector<HTMLElement>('[data-testid="side-bots"] > .bot-list');
    const tl = document.querySelector<HTMLElement>('[data-testid="side-sessions"] > .ss-list');
    const whole = (list: HTMLElement | null, sel: string) => {
      if (!list) return 0;
      const box = list.getBoundingClientRect();
      const v = (/inset\(([^)]*)\)/.exec(getComputedStyle(list).clipPath)?.[1] ?? "").trim().split(/\s+/).map(parseFloat).filter((n) => !Number.isNaN(n));
      const bottom = box.bottom - (v.length ? (v[2] ?? v[0] ?? 0) : 0);
      return [...list.querySelectorAll<HTMLElement>(sel)].filter((e) => {
        const b = e.getBoundingClientRect();
        return b.height > 0 && b.top >= box.top - 0.5 && b.bottom <= bottom + 0.5;
      }).length;
    };
    const foot = r(document.querySelector(".side-foot"));
    const dock = r(document.querySelector('[data-testid="dock"]'));
    const bots = bl?.clientHeight ?? 0;
    const terms = tl?.clientHeight ?? 0;
    return {
      win: innerHeight,
      botsList: Math.round(bots),
      termsList: Math.round(terms),
      listArea: Math.round(bots + terms),
      botsNeed: bl?.scrollHeight ?? 0,
      termsNeed: tl?.scrollHeight ?? 0,
      footer: Math.round(foot?.height ?? 0),
      dock: Math.round(dock?.height ?? 0),
      botRows: whole(bl, ".bot-w > .bot"),
      threadRows: whole(bl, ".th-row"),
      sessionCards: whole(tl, ".ss-row"),
      sessionsTotal: tl?.querySelectorAll(".ss-row").length ?? 0,
    };
  });
}

function record(label: string, m: unknown) {
  const line = JSON.stringify({ label, ...(m as object) });
  console.log(line);
  if (MEASURE) appendFileSync(MEASURE, line + "\n");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test.describe("measure", () => {
  test.use({ deviceScaleFactor: 1, viewport: { width: 1440, height: 900 } });
  test("measure: few rows (4 bots, Kami's 5 threads, 5 terminals in 2 folders) at 900 and 760", async ({ page }) => {
    test.setTimeout(120_000);
    await mock("mock.threads", { bot: "kami", threads: ["Release notes", "Nightly build", "Slack alert copy", "Docs dark mode", "Gateway 502s"].map((title, i) => ({ title, ago: (i + 1) * 600 })) });
    await open(page);
    for (const [agent, folder] of [["shell", API], ["pi", WEB], ["codex", WEB], ["claude", WEB], ["shell", API]] as const) await newTerm(page, agent, folder);
    await page.mouse.move(900, 600);
    for (const h of [900, 760]) {
      await page.setViewportSize({ width: 1440, height: h });
      await page.waitForTimeout(300);
      record(`few@${h}`, await measure(page));
    }
  });

  test("measure: many rows (12 bots x 6 threads, 15 terminals) at 900 and 760", async ({ page }) => {
    test.setTimeout(240_000);
    const { bots } = await mock("mock.manyBots", { n: 12 });
    const names = ["Billing fixes", "Flaky e2e on CI", "Onboarding copy", "Search ranking", "Pricing page A/B", "Deploy checklist"];
    for (const b of bots as string[]) await mock("mock.threads", { bot: b, threads: names.map((title, i) => ({ title, ago: (i + 1) * 600 })) });
    await open(page, { roster: ["kami", ...(bots as string[])] });
    const kinds = ["claude", "codex", "shell"];
    const folders = [WEB, API, NOTES];
    for (let i = 0; i < 15; i++) {
      const id = await newTerm(page, kinds[i % 3]!, folders[Math.floor(i / 5)]!);
      if (kinds[i % 3] === "shell") await out(page, id, "you@laptop % ");
    }
    await page.mouse.move(900, 600);
    for (const h of [900, 760]) {
      await page.setViewportSize({ width: 1440, height: h });
      await page.waitForTimeout(300);
      await page.evaluate(() => document.querySelectorAll<HTMLElement>(".side-sec > .bot-list").forEach((l) => (l.scrollTop = 0)));
      await page.waitForTimeout(300);
      record(`many@${h}`, await measure(page));
    }
  });
});

const LONG = "Running the payments integration suite against the staging webhook endpoint with retries enabled… 12s";

test("session cards: 4px apart, 10px+ between folders, rounded, two lines with the last printed line cut by an ellipsis, the amber lane while a CLI runs", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  const a = await newTerm(page, "shell", API);
  await out(page, a, "you@laptop api-server % git status -sb\r\n## main\r\n");
  const b = await newTerm(page, "codex", WEB);
  await out(page, b, `\x1b[2J\x1b[H${LONG}\r\n`);
  const c = await newTerm(page, "claude", WEB);
  await out(page, c, "Read 142 lines\r\n");
  // the second line: the CLI, then the last line it printed (read a moment after output stops)
  await expect(page.getByTestId(`session-${b}`).getByTestId("term-line")).toHaveText(LONG);
  await expect(page.getByTestId(`session-${b}`).getByTestId("term-meta")).toContainText("codex");
  await expect(page.getByTestId(`session-${c}`).getByTestId("term-line")).toHaveText("Read 142 lines");
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-line")).toHaveText("## main");
  // a CLI's own bullet before its line is dropped (the card already has its · after the CLI)
  await out(page, b, "\x1b[2m• Ran\x1b[0m pnpm test payments\r\n");
  await expect(page.getByTestId(`session-${b}`).getByTestId("term-line")).toHaveText("Ran pnpm test payments");
  await out(page, b, `\x1b[2J\x1b[H${LONG}\r\n`);
  await expect(page.getByTestId(`session-${b}`).getByTestId("term-line")).toHaveText(LONG);
  const geo = await page.evaluate(([b]) => {
    const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="side-sessions"] .ss-row')];
    const groups = [...document.querySelectorAll<HTMLElement>('[data-testid="term-group"]')];
    const rect = (e: Element) => e.getBoundingClientRect();
    const inGroup = (g: HTMLElement) => [...g.querySelectorAll<HTMLElement>(".ss-row")].map(rect);
    const gaps = groups.flatMap((g) => inGroup(g).slice(1).map((r, i) => r.top - inGroup(g)[i]!.bottom));
    const groupGap = groups.slice(1).map((g, i) => rect(g.querySelector(".tg-h")!).top - inGroup(groups[i]!).at(-1)!.bottom);
    const card = document.querySelector<HTMLElement>(`[data-testid="session-${b}"]`)!;
    const line = card.querySelector<HTMLElement>('[data-testid="term-line"]')!;
    const name = card.querySelector<HTMLElement>('[data-testid="session-name"]')!;
    const cs = getComputedStyle(card);
    return {
      n: rows.length,
      gaps,
      groupGap,
      radius: cs.borderTopLeftRadius,
      border: cs.borderTopWidth,
      lineBelow: rect(line).top >= rect(name).bottom - 0.5,
      cut: [getComputedStyle(line).textOverflow, line.scrollWidth > line.clientWidth, Math.round(rect(line).height)] as const,
      inCard: rect(line).right <= rect(card).right + 0.5,
      lane: getComputedStyle(card, "::before").backgroundColor,
    };
  }, [b] as const);
  expect(geo.n).toBe(3);
  for (const g of geo.gaps) expect(g).toBeGreaterThanOrEqual(4);
  expect(geo.groupGap.length).toBe(1);
  for (const g of geo.groupGap) expect(g).toBeGreaterThanOrEqual(10);
  expect(geo.radius).toBe("8px");
  expect(geo.border).toBe("1px");
  expect(geo.lineBelow).toBe(true);
  expect(geo.cut).toEqual(["ellipsis", true, 15]);
  expect(geo.inCard).toBe(true);
  // every running card's lane sits inside its card (selected or not), the same distance from its left edge
  const lanes = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('[data-testid="side-sessions"] .ss-row')].map((card) => {
      const r = card.getBoundingClientRect();
      const cs = getComputedStyle(card, "::before");
      const on = card.classList.contains("run");
      const left = r.left + parseFloat(cs.left || "0");
      const top = r.top + parseFloat(cs.top || "0");
      const bottom = r.bottom - parseFloat(cs.bottom || "0");
      return { on, content: cs.content, inside: left >= r.left && left + parseFloat(cs.width) <= r.right && top >= r.top && bottom <= r.bottom, dx: Math.round(left - r.left) };
    }),
  );
  const running = lanes.filter((l) => l.on);
  expect(running.length).toBeGreaterThanOrEqual(2);
  for (const l of running) expect(l.inside).toBe(true);
  expect(new Set(running.map((l) => l.dx)).size).toBe(1);
  for (const l of lanes.filter((l) => !l.on)) expect(l.content === "none" || l.content === "normal").toBe(true);
  // Codex runs: the amber lane; a bare shell prompt has none
  await expect(page.getByTestId(`session-${b}`)).toHaveClass(/\brun\b/);
  expect(geo.lane).not.toBe("rgba(0, 0, 0, 0)");
  await expect(page.getByTestId(`session-${a}`)).not.toHaveClass(/\brun\b/);
  // the selected card: a lighter fill and its edge
  const sel = await page.getByTestId(`session-${c}`).evaluate((e) => [getComputedStyle(e).backgroundColor, getComputedStyle(e).borderTopColor]);
  expect(sel[0]).not.toBe("rgba(0, 0, 0, 0)");
  expect(sel[1]).not.toBe("rgba(0, 0, 0, 0)");
});

test("BOTS | TERMINALS divider: a drag moves the line, keeps 120px each, persists across a reload; double-click goes back to auto", async ({ page }) => {
  test.setTimeout(150_000);
  const { bots } = await mock("mock.manyBots", { n: 8 });
  await open(page, { roster: ["kami", ...(bots as string[])] });
  for (const [agent, folder] of [["shell", API], ["codex", WEB], ["claude", WEB], ["shell", NOTES], ["shell", NOTES]] as const) await newTerm(page, agent, folder);
  await page.mouse.move(900, 600);
  const split = page.getByTestId("side-split");
  await expect(split).toHaveAttribute("data-mode", "auto");
  const h = () => page.evaluate(() => ["side-bots", "side-sessions"].map((id) => document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().height));
  const [b0, t0] = await h();
  const box = (await split.boundingBox())!;
  const drag = async (dy: number) => {
    const s = (await split.boundingBox())!;
    await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
    await page.mouse.down();
    await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2 + dy / 2);
    await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2 + dy);
    await page.mouse.up();
  };
  await drag(-80);
  const [b1, t1] = await h();
  expect(b1).toBeLessThan(b0 - 60);
  expect(t1).toBeGreaterThan(t0 + 60);
  await expect(split).toHaveAttribute("data-mode", "set");
  const saved = await page.evaluate(() => localStorage.getItem("omher.side.split"));
  expect(Number(saved)).toBeGreaterThan(0);
  // past either end: each region keeps 120px
  await drag(-2000);
  expect((await h())[0]).toBeGreaterThanOrEqual(119.5);
  await drag(4000);
  expect((await h())[1]).toBeGreaterThanOrEqual(119.5);
  // the keyboard moves it too (separator, arrow keys)
  await drag(-(box.y - 300));
  const before = (await h())[0];
  await split.focus();
  await page.keyboard.press("ArrowUp");
  expect((await h())[0]).toBeLessThan(before - 10);
  // kept across a reload
  const kept = await page.evaluate(() => localStorage.getItem("omher.side.split"));
  const [bk] = await h();
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(page.getByTestId("side-split")).toHaveAttribute("data-mode", "set");
  expect(await page.evaluate(() => localStorage.getItem("omher.side.split"))).toBe(kept);
  expect(Math.abs((await h())[0] - bk)).toBeLessThanOrEqual(2);
  // double-click: auto again, nothing saved
  await page.getByTestId("side-split").dblclick();
  await expect(page.getByTestId("side-split")).toHaveAttribute("data-mode", "auto");
  expect(await page.evaluate(() => localStorage.getItem("omher.side.split"))).toBeNull();
});

test("footer: Automations, Plugins and Settings in one row of icon buttons, named for a screen reader and in a tooltip, reachable by Tab; the whole footer at most 90px", async ({ page }) => {
  await open(page);
  const row = page.getByTestId("foot-row");
  for (const [id, name] of [["nav-automations", "Automations"], ["nav-plugins", "Plugins"], ["nav-settings", "Settings"]] as const) {
    await expect(row.getByTestId(id)).toBeVisible();
    await expect(row.getByRole("button", { name: new RegExp(`^${name}`) })).toHaveCount(1);
    await expect(row.getByTestId(id)).toHaveAttribute("title", new RegExp(`^${name}`));
  }
  // the Automations count stays on its icon
  await expect(row.getByTestId("nav-automations").locator(".nav-count")).toHaveText("6");
  await expect(row.getByTestId("nav-automations")).toHaveAttribute("title", "Automations · 6");
  // one row: the three share a line, and the usage marks sit on it too
  const ys = await page.evaluate(() => ["nav-automations", "nav-plugins", "nav-settings"].map((id) => Math.round(document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().top)));
  expect(new Set(ys).size).toBe(1);
  await expect(row.getByTestId("usage")).toBeVisible();
  const foot = (await page.locator(".side-foot").boundingBox())!;
  expect(foot.height).toBeLessThanOrEqual(90);
  // Tab reaches each, in order, and Enter opens its page
  await page.getByTestId("nav-automations").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("nav-automations")).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("nav-plugins")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("nav-plugins")).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("nav-settings")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("nav-settings")).toHaveClass(/\bon\b/);
});

/** The sidebar's lists as they show now (fix5: what is painted, not where a clip ends). `band`: while more rows are
 *  below, the empty space from the last thing painted in the list (a whole row, or the part of a cut row the bottom
 *  fade shows) down to the chevron's band (the list's last CUE_PX); `cut`: a row drawn cut at the end (only under the
 *  fade); `fade`: the fade is drawn; `openHeadsAlone`: an open folder whose header shows whole and none of its cards. */
function bands(page: Page) {
  return page.evaluate(() => {
    type Band = { band: number; more: string | null; scrollTop: number; cut: boolean; fade: boolean; openHeadsAlone: number; cardsShown: number; cards: number };
    const out: Record<string, Band> = {};
    for (const [name, sel] of [["bots", '[data-testid="side-bots"] > .bot-list'], ["terms", '[data-testid="side-sessions"] > .ss-list']] as const) {
      const list = document.querySelector<HTMLElement>(sel);
      if (!list) continue;
      const box = list.getBoundingClientRect();
      const v = (/inset\(([^)]*)\)/.exec(getComputedStyle(list).clipPath)?.[1] ?? "").trim().split(/\s+/).map(parseFloat).filter((n) => !Number.isNaN(n));
      const end = box.bottom - (v.length ? (v[2] ?? v[0] ?? 0) : 0);
      const rows = [...list.querySelectorAll<HTMLElement>(".bot-w > .bot, .th-row, .tg-h, .ss-row, .bot-list > :not(.bot-w):not(.tg)")]
        .map((r) => ({ r, b: r.getBoundingClientRect() }))
        .filter(({ b }) => b.height > 0);
      const painted = rows.filter(({ b }) => b.top < end - 0.5 && b.bottom > box.top + 0.5);
      const whole = painted.filter(({ b }) => b.top >= box.top - 0.5 && b.bottom <= end + 0.5);
      const lastPainted = Math.max(box.top, ...painted.map(({ b }) => Math.min(b.bottom, end)));
      const more = list.dataset.more ?? null;
      const below = more === "below" || more === "both";
      const after = getComputedStyle(list.parentElement!, "::after");
      const openHeadsAlone = [...list.querySelectorAll<HTMLElement>(".tg:not(.shut)")].filter((g) => {
        const h = g.querySelector(".tg-h");
        return whole.some(({ r }) => r === h) && !painted.some(({ r }) => r.matches(".ss-row") && g.contains(r));
      }).length;
      out[name] = {
        band: below ? Math.max(0, Math.round((box.bottom - 14 - lastPainted) * 100) / 100) : 0,
        more,
        scrollTop: Math.round(list.scrollTop),
        cut: painted.some(({ b }) => b.bottom > end + 0.5),
        fade: after.content !== "none" && /gradient/.test(after.backgroundImage),
        openHeadsAlone,
        cardsShown: whole.filter(({ r }) => r.matches(".ss-row")).length,
        cards: rows.filter(({ r }) => r.matches(".ss-row")).length,
      };
    }
    return out;
  });
}

/** Scrolls BOTS and TERMINALS each to `f` of the way down and waits for the dock and the split to settle. */
async function scrollBoth(page: Page, f: number) {
  await page.evaluate((f) => document.querySelectorAll<HTMLElement>(".side-sec > .bot-list").forEach((l) => (l.scrollTop = f * (l.scrollHeight - l.clientHeight))), f);
  await page.waitForTimeout(500);
}

const FRACTIONS = [0, 0.25, 0.43, 0.7, 1];

// owner (2026-11-16, "no empty band"), fix5: a region's last visible thing is a whole row at its end, or a row cut
// under the soft bottom fade, never an empty band (over 12px, besides the chevron's 14px). At the top of an auto
// split the regions end on whole rows; scrolled, the cut row shows under the fade, as in any scrolling list.
function expectNoBand(b: Awaited<ReturnType<typeof bands>>, f: number) {
  for (const r of [b.bots!, b.terms!]) {
    const at = JSON.stringify({ f, ...b });
    expect(r.band, at).toBeLessThanOrEqual(12);
    expect(r.openHeadsAlone, at).toBe(0);
    if (r.cut) expect(r.fade, at).toBe(true);
    if (f === 0 && r.scrollTop === 0) expect(r.cut, at).toBe(false);
  }
}

test.describe("auto split: no blank band", () => {
  test.use({ deviceScaleFactor: 1, viewport: { width: 1440, height: 900 } });
  test("few rows at 900: every card shows, TERMINALS without a chevron, BOTS ends on a whole row; at 760 each region ends on a whole row; no band at any scroll", async ({ page }) => {
    test.setTimeout(120_000);
    await mock("mock.threads", { bot: "kami", threads: ["Release notes", "Nightly build", "Slack alert copy", "Docs dark mode", "Gateway 502s"].map((title, i) => ({ title, ago: (i + 1) * 600 })) });
    await open(page);
    for (const [agent, folder] of [["shell", API], ["pi", WEB], ["codex", WEB], ["claude", WEB]] as const) await newTerm(page, agent, folder);
    await page.mouse.move(900, 600);
    await page.waitForTimeout(400);
    const b900 = await bands(page);
    record("tidy-few@900", { ...b900, ...(await measure(page)) });
    expect(b900.terms!.cardsShown).toBe(4);
    expect(b900.terms!.more).toBeNull();
    for (const h of [900, 760]) {
      await page.setViewportSize({ width: 1440, height: h });
      await page.waitForTimeout(400);
      for (const f of FRACTIONS) {
        await scrollBoth(page, f);
        const b = await bands(page);
        record(`fix5-few@${h}@${f}`, b);
        expectNoBand(b, f);
      }
      await scrollBoth(page, 0);
    }
  });

  test("many rows at 900 and 760: no band at any scroll; an open folder never shows without a card", async ({ page }) => {
    test.setTimeout(240_000);
    const { bots } = await mock("mock.manyBots", { n: 12 });
    const names = ["Billing fixes", "Flaky e2e on CI", "Onboarding copy", "Search ranking", "Pricing page A/B", "Deploy checklist"];
    for (const b of bots as string[]) await mock("mock.threads", { bot: b, threads: names.map((title, i) => ({ title, ago: (i + 1) * 600 })) });
    await open(page, { roster: ["kami", ...(bots as string[])] });
    const kinds = ["claude", "codex", "shell"];
    const folders = [WEB, API, NOTES];
    for (let i = 0; i < 15; i++) await newTerm(page, kinds[i % 3]!, folders[Math.floor(i / 5)]!);
    await page.mouse.move(900, 600);
    for (const h of [900, 760]) {
      await page.setViewportSize({ width: 1440, height: h });
      await page.waitForTimeout(400);
      for (const f of FRACTIONS) {
        await scrollBoth(page, f);
        const b = await bands(page);
        if (f === 0) record(`tidy-many@${h}`, { ...b, ...(await measure(page)) });
        record(`fix5-many@${h}@${f}`, b);
        expectNoBand(b, f);
      }
      // TERMINALS alone at a few offsets, BOTS at its top
      await scrollBoth(page, 0);
      for (const top of [37, 120]) {
        await page.evaluate((t) => document.querySelectorAll<HTMLElement>(".side-sec > .ss-list").forEach((l) => (l.scrollTop = t)), top);
        await page.waitForTimeout(150);
        expectNoBand(await bands(page), -1);
      }
    }
  });
});
