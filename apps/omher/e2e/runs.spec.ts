// Plans tab (runs in the code): the bot's plans as a list of plain text rows, and the selected one as a graph in
// the app's own font: a plain header (title, one muted line), one frontier of outlined boxes to a row (title, the
// model's mark with what ran the node, a status icon and word), every edge a 1.25px line with rounded turns and a
// small arrowhead, in the side panel and at full size over the chat column (⌘⇧G). Real (redacted) dag runs, real
// delegation logs for the models and routes, and a synthetic 40-node run for the layout.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const FAN = "dag:20261102_235818_fcfb1bdd/codex-coexist";
const LIVE = "dag:20261102_235818_fcfb1bdd/codex-coexist-live";
const CANCELLED = "dag:20261026_134438_3ae70257/omh-dap";
const BIG = "dag:synthetic/big-run";
const CLI_CLAUDE = "claude:ec38bc0b-8eb7-936b-b856-daaee28015c4";
const CLI_CODEX = "codex:c5e14c89-54b2-c703-769f-a6207ed501ea";
const CLI_LIVE = "claude:live-session";
const WRITES = ["chat.send", "chat.interrupt", "approval.respond", "clarify.respond", "chat.set_model", "bots.rename", "bots.set_avatar"];

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  return reply.result;
}
/** The error code of a mock op that fails. */
async function mockError(op: string, params: Record<string, unknown>): Promise<string> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => res(JSON.parse(String(m.data)));
    ws.send(JSON.stringify({ id: "e1", op, ...params }));
  });
  ws.close();
  return reply.error?.code;
}

async function openRuns(page: Page, bot = "kami") {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  if (bot !== "kami") {
    await page.getByTestId(`bot-${bot}`).click();
    await page.keyboard.press(`${await mod(page)}+Period`);
  } else await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  await expect(page.getByTestId("panel-runs")).toBeVisible();
}
/** The keyboard modifier the app uses here (⌘ on macOS, Ctrl elsewhere), read from the page. */
async function mod(page: Page) {
  return (await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform))) ? "Meta" : "Control";
}
/** Unfolds the list when it sits folded into the selected plan's header ("All 7 plans ▾"). */
async function showList(page: Page) {
  const t = page.getByTestId("run-list-toggle");
  await expect(t).toBeVisible();
  if ((await t.getAttribute("aria-expanded")) === "false") await t.click();
  await expect(page.getByTestId("run-list")).toBeVisible();
}
/** A row of the list: by its plan's title (a row shows the goal; the title is in its tooltip), or by its text. */
const rowOf = (page: Page, text: string | RegExp, testId = "run-row") =>
  typeof text === "string" ? page.locator(`[data-testid="${testId}"][title*="${text}"]`) : page.getByTestId(testId).filter({ hasText: text });
/** Opens a plan from the list (which then folds away again). */
async function pickRow(page: Page, text: string | RegExp, testId = "run-row") {
  await showList(page);
  await rowOf(page, text, testId).click();
}
const panel = (page: Page) => page.getByTestId("run-graph-box");
const full = (page: Page) => page.getByTestId("runs-full");
/** A node's box, by its id (a "Node details" card carries the id too). */
const nodeOf = (root: ReturnType<typeof panel>, id: string) => root.locator(`[data-testid="run-node"][data-node="${id}"]`);
/** The glyphs of the terminal's box view: none of them is drawn here. */
const GLYPHS = /[✓✗●○◌↻←▽╎¦▪▼↓]/;
/** Rewrites what the page hears from the bridge: `fix(op, result)` may change a reply's result in place. */
async function rewrite(page: Page, fix: (op: string, result: any) => void) {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      const op = ops.get(msg.id);
      if (msg.ok && op) fix(op, msg.result);
      ws.send(JSON.stringify(msg));
    });
  });
}
/** The entrance (boxes one by one, then the lines) is over. */
const settled = (page: Page) => page.waitForTimeout(1500);
/** Every CSS transition that is running has finished (the 120ms ease of a box, a line's colour): what is read next
 *  is the end style. The dash on a running edge is an animation, not a transition, and goes on. */
const eased = (page: Page) => page.evaluate(() => Promise.all(document.getAnimations().filter((a) => a instanceof CSSTransition).map((a) => a.finished.catch(() => null))).then(() => undefined));

/** Grows the Codex session to 88 sub-runs, as a real one did: 3 still running, 1 failed, 84 done. */
async function grow88(page: Page) {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      const op = ops.get(msg.id);
      if (msg.ok && op === "runs.get" && msg.result.run?.id === CLI_CODEX) {
        const base = msg.result.run.nodes[0];
        msg.result.run.nodes = Array.from({ length: 88 }, (_, i) => ({
          ...base,
          id: `sub-${i}`,
          label: i % 7 === 0 ? `Sub-run ${i}: a longer title that has to be cut somewhere in the middle` : `Sub-run ${i}`,
          state: i >= 85 ? "running" : i === 40 ? "failed" : "done",
          ...(i >= 85 ? { ended: undefined } : {}),
        }));
        ws.send(JSON.stringify(msg));
        return;
      }
      if (msg.ok && op === "runs.cli") for (const r of msg.result.runs) if (r.id === CLI_CODEX) r.counts = { nodes: 88, done: 84, running: 3, failed: 1 };
      ws.send(op === "runs.cli" ? JSON.stringify(msg) : raw);
    });
  });
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

// ---- the tab and the list ----

test("Plans is the sixth tab; the header still holds one control; the panel is 460px, up to 560px beyond a 480px chat", async ({ page }) => {
  await openRuns(page);
  const tabs = page.getByRole("tablist", { name: "Panel" }).getByRole("tab");
  expect(await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("title")))).toEqual(["Details", "Terminal", "Schedule", "Worktrees", "Diff", "Plans"]);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);
  // what the window has beyond the 248px sidebar and a 480px chat, between 460 and 560
  const width = async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0);
  await expect.poll(width).toBe(552);
  await page.setViewportSize({ width: 1100, height: 760 });
  await expect.poll(width).toBe(460);
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect.poll(width).toBe(560);
  await page.setViewportSize({ width: 1280, height: 820 });
  // the selected tab and the selected run are gray, never the brand gradient
  expect(await page.getByTestId("panel-tab-runs").evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
  await showList(page);
  const sel = page.locator('[data-testid="run-row"][aria-current="true"]');
  expect(await sel.evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
});

test("the list: running first with a live dot, then newest; dots differ by state", async ({ page }) => {
  await openRuns(page);
  await showList(page);
  const rows = page.getByTestId("run-row");
  await expect(rows).toHaveCount(4);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).toEqual(["running", "done", "cancelled", "done"]);
  const upd = (await mock("runs.list", { bot: "kami" })).runs.map((r: any) => r.updated).slice(1);
  expect(upd).toEqual([...upd].sort((a: number, b: number) => b - a));
  await expect(rows.nth(0).locator(".rn-live")).toHaveCount(1);
  await expect(rows.nth(1).locator(".rn-live")).toHaveCount(0);
  await expect(rows.nth(0).locator(".rn-n")).toHaveText(/^3\/6 · \d+(s|m)$/);
  await expect(rows.nth(1).locator(".rn-n")).toHaveText(/^5\/6 · /);
  const dot = (i: number) => rows.nth(i).locator("i").first().evaluate((e) => getComputedStyle(e).backgroundColor);
  expect(await dot(1)).not.toBe(await dot(2));
  await expect(rows.nth(2).locator("i").first()).toHaveAttribute("aria-label", "cancelled");
});

test("the list is plans: \"Kami's plans\"; a row is plain text: the goal, then 3/6 · 14m, and a small state dot", async ({ page }) => {
  await openRuns(page);
  await expect(page.getByTestId("panel-tab-runs")).toHaveText("Plans");
  await expect(page.getByTestId("panel-runs").locator(".pn-sec").first()).toContainText("Kami's plans");
  await expect(page.getByTestId("run-list-toggle")).toHaveText("All 7 plans");
  await showList(page);
  const rows = page.getByTestId("run-row");
  // the goal is the row's text; a plan without one shows its title
  await expect(rows.nth(0).getByTestId("run-row-text")).toHaveText(/^OMH suggests its own skills to Codex fanouts/);
  await expect(rowOf(page, "omh-dap").getByTestId("run-row-text")).not.toHaveText("");
  await expect(rows.nth(0)).toHaveAttribute("title", /^Codex coexistence \(live\) · OMH suggests/);
  // a dot, the text, the numbers: nothing else, and nothing drawn as a pill
  const parts = await rows.evaluateAll((els) =>
    els.map((e) => ({
      kids: [...e.children].map((c) => c.className.split(" ")[0]),
      pills: [...e.querySelectorAll("span")].filter((c) => {
        const s = getComputedStyle(c);
        return s.backgroundImage !== "none" || !/rgba\(0, 0, 0, 0\)|transparent/.test(s.backgroundColor) || parseFloat(s.borderTopWidth) > 0;
      }).length,
      dot: Math.round(e.querySelector("i")!.getBoundingClientRect().width),
    })),
  );
  for (const r of parts) {
    expect(r.kids.slice(1)).toEqual(["rn-title", "rn-n"]);
    expect(["rn-live", "rn-dot"]).toContain(r.kids[0]);
    expect(r.pills).toBe(0);
    expect(r.dot).toBe(7);
  }
  await expect(page.locator(".rn-tag")).toHaveCount(0);
  // a CLI agent's row names the agent as text before the plan, with no badge behind it
  const cli = page.getByTestId("cli-run-row").first().getByTestId("run-agent");
  await expect(cli).toHaveText("Claude");
  expect(await cli.evaluate((e) => [getComputedStyle(e).backgroundColor, getComputedStyle(e).borderTopWidth])).toEqual([expect.stringMatching(/rgba\(0, 0, 0, 0\)|transparent/), "0px"]);
});

test("the words are in the string table: Korean, Japanese and Chinese name the tab 계획, 計画, 计划", async ({ browser }) => {
  for (const [lang, tab, list] of [
    ["ko", "계획", "Kami의 계획"],
    ["ja", "計画", "Kamiの計画"],
    ["zh", "计划", "Kami的计划"],
  ]) {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.addInitScript((l) => localStorage.setItem("omher.lang", l), lang);
    await openRuns(page);
    await expect(page.getByTestId("panel-tab-runs")).toHaveText(tab);
    await expect(page.getByTestId("panel-runs").locator(".pn-sec").first()).toContainText(list);
    await ctx.close();
  }
});

test("the run list shows the 12 newest, running first, with 'Show all (N)'", async ({ page }) => {
  // 44 runs, as on a real profile: the mock's own four plus 40 finished copies
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "runs.list" && msg.ok && msg.result.runs.length) {
        const base = msg.result.runs.find((r: any) => r.state !== "running") ?? msg.result.runs[0];
        for (let i = 0; i < 40; i++)
          msg.result.runs.push({ ...base, id: `${base.id}-old${i}`, title: `Old run ${i}`, state: "done", updated: base.updated - 3600 * (i + 1) });
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await openRuns(page);
  const rows = page.getByTestId("run-row");
  await showList(page);
  await expect(rows).toHaveCount(12);
  const states = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")));
  const firstIdle = states.findIndex((x) => x !== "running");
  expect(states.slice(firstIdle).includes("running")).toBe(false); // running ones first
  expect(firstIdle).toBeGreaterThan(0);
  const more = page.getByTestId("run-list-more");
  await expect(more).toHaveText("Show all (44)");
  await more.click();
  await expect(rows).toHaveCount(44);
  await expect(more).toHaveText("Show fewer");
  await more.click();
  await expect(rows).toHaveCount(12);
});

test("a selected run folds the list into its header; 'All runs' unfolds it; picking a run folds it again", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openRuns(page);
  const toggle = page.getByTestId("run-list-toggle");
  await expect(page.getByTestId("panel-runs")).toHaveAttribute("data-list", "closed");
  await expect(toggle).toHaveText("All 7 plans"); // the bot's 4 and the CLI agents' 3
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(page.getByTestId("cli-run-row")).toHaveCount(0);
  await expect(page.getByTestId("run-list-more")).toHaveCount(0);
  await expect(panel(page).getByTestId("run-state")).toHaveText("Running");
  // the run's text starts right under the section title, and its first boxes are on screen with no scrolling
  const head = (await panel(page).getByTestId("run-plan").boundingBox())!;
  expect(head.y).toBeLessThanOrEqual(120);
  const first = (await panel(page).getByTestId("run-node").first().boundingBox())!;
  expect(first.y).toBeLessThanOrEqual(240); // under the title, the status, who runs it and the goal
  expect(await page.locator(".details .pn-scroll").evaluate((e) => e.scrollTop)).toBe(0);
  // the toggle unfolds both lists; picking a run folds them away and opens it
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  await expect(page.getByTestId("cli-run-row")).toHaveCount(3);
  await rowOf(page, "Codex coexistence fixes").click();
  await expect(panel(page)).toHaveAttribute("data-run", FAN);
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  await toggle.click();
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(panel(page)).toHaveAttribute("data-run", FAN);
});

test("a bot with no runs says so", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("panel-runs")).toContainText("No plans yet.");
});

// ---- the header: plain text ----

test("the run's header is plain text in the app's font: the title leads, a status line with a state dot, who runs it, the goal; no card or prefix", async ({ page }) => {
  await openRuns(page);
  const head = panel(page).getByTestId("run-plan");
  await expect(head.getByTestId("run-plan-title")).toHaveText("Codex coexistence (live)");
  // the status line: the state, how far it is and how long it has run; who runs it is the line under it
  await expect(head.getByTestId("run-plan-counts")).toHaveText(/^Running · 3 of 6 done · 1 repaired · 1 waiting · \d+(s|m)$/);
  await expect(head.getByTestId("run-plan-where")).toHaveText("Opus 5.5 · high effort · main");
  await expect(head.getByTestId("run-plan-where").locator("[data-mark=claude], .model-ic")).toHaveCount(1);
  await expect(head.getByTestId("run-dot")).toHaveClass(/running/);
  await expect(head.getByTestId("run-plan-goal")).toContainText("OMH suggests its own skills to Codex fanouts");
  // the "OMH / DAG · 6 tasks" line is gone, and nothing names Hermes
  await expect(head.getByTestId("run-plan-source")).toHaveCount(0);
  await expect(head).not.toContainText("OMH / DAG");
  await expect(head).not.toContainText("Hermes");
  const look = await head.evaluate((e) => {
    const s = getComputedStyle(e);
    const css = (sel: string) => getComputedStyle(e.querySelector(sel)!);
    const title = css("[data-testid=run-plan-title]");
    const meta = css("[data-testid=run-plan-counts]");
    const who = css("[data-testid=run-plan-where]");
    const goal = css("[data-testid=run-plan-goal]");
    const box = (sel: string) => e.querySelector(sel)!.getBoundingClientRect();
    const boxed = [e, ...e.querySelectorAll("*")].filter((x) => {
      if (x.closest("[data-testid=graph-expand]")) return false; // the full view's button has a hover fill only
      const c = getComputedStyle(x);
      if (x.matches("[data-testid=run-dot]")) return false; // the state dot
      return c.backgroundImage !== "none" || c.boxShadow !== "none" || parseFloat(c.borderTopWidth) > 0 || !/rgba\(0, 0, 0, 0\)|transparent/.test(c.backgroundColor);
    }).length;
    return {
      font: s.fontFamily,
      body: getComputedStyle(document.body).fontFamily,
      title: [title.fontSize, title.fontWeight, title.fontFamily],
      meta: [meta.fontSize, meta.fontWeight],
      who: who.fontSize,
      goal: [goal.fontSize, goal.webkitLineClamp],
      // title, status and who run close together; the goal stands 10px apart
      gaps: [box("[data-testid=run-plan-counts]").top - box(".ph-top").bottom, box("[data-testid=run-plan-goal]").top - box("[data-testid=run-plan-where]").bottom],
      dot: [box("[data-testid=run-dot]").width, box("[data-testid=run-dot]").height],
      boxed,
    };
  });
  // the app's own sans font, never monospace: the title 14px semibold, the lines under it 12px
  expect(look.font).toBe(look.body);
  expect(look.font).not.toMatch(/mono|Menlo/i);
  expect(look.title).toEqual(["14px", "600", look.body]);
  expect(look.meta).toEqual(["12px", "400"]);
  expect(look.who).toBe("12px");
  expect(look.goal).toEqual(["12.5px", "2"]);
  expect(look.gaps[0]).toBeGreaterThanOrEqual(0);
  expect(look.gaps[0]).toBeLessThanOrEqual(4);
  expect(look.gaps[1]).toBe(10);
  expect(look.dot).toEqual([6, 6]);
  expect(look.boxed).toBe(0);
  // what the card held is gone
  for (const gone of [".rn-badge", ".rn-bar", ".rn-head", ".rp", ".rp-chip", "[data-testid=run-plan-layer]", "[data-testid=run-legend]", "[data-testid=run-zoom]"])
    await expect(page.locator(gone)).toHaveCount(0);
  // the full view opens from a 24px icon button on the title's row, named in its tooltip, inside the panel
  const expand = head.getByTestId("graph-expand");
  await expect(expand).toHaveAttribute("title", /^Full view (⌘⇧G|Ctrl\+Shift\+G)$/);
  await expect(expand).toHaveText("");
  const [eb, tb, pb] = await Promise.all([expand.boundingBox(), head.getByTestId("run-plan-title").boundingBox(), page.getByTestId("panel-runs").boundingBox()]);
  expect([eb!.width, eb!.height]).toEqual([24, 24]);
  expect(Math.abs(eb!.y + eb!.height / 2 - (tb!.y + tb!.height / 2))).toBeLessThanOrEqual(1);
  expect(eb!.x + eb!.width).toBeLessThanOrEqual(pb!.x + pb!.width);
});

test("the header's muted lines keep 4.5:1 on the panel, dark and light", async ({ page }) => {
  for (const theme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await openRuns(page);
    const ratios = await page.getByTestId("panel-runs").evaluate((root) => {
      // "rgb(…)", or "color(srgb r g b)" in 0-1 from color-mix()
      const rgb = (c: string) => {
        const n = (c.replace(/^color\(srgb/, "").match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
        return c.startsWith("color(") ? n.map((v) => v * 255) : n;
      };
      const lum = ([r, g, b]: number[]) => {
        const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
      };
      const bgOf = (el: Element | null) => {
        for (; el; el = el.parentElement) {
          const c = getComputedStyle(el).backgroundColor;
          if (!/rgba\(\d+, \d+, \d+, 0\)|transparent/.test(c) && !/rgba\(.*, 0\.0\d+\)/.test(c)) return c;
        }
        return "rgb(0, 0, 0)";
      };
      const ratio = (sel: string) => {
        const el = root.querySelector(sel)!;
        const a = lum(rgb(getComputedStyle(el).color));
        const b = lum(rgb(bgOf(el)));
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };
      return [".pn-sec", ".rn-toggle", "[data-testid=run-plan-where]", "[data-testid=run-plan-goal]", "[data-testid=run-progress]"].map((sel) => {
        const el = root.querySelector(sel)!;
        return { sel, color: getComputedStyle(el).color, bg: bgOf(el), r: ratio(sel) };
      });
    });
    for (const r of ratios) expect(r.r, `${theme} ${r.sel} ${r.color} on ${r.bg}`).toBeGreaterThanOrEqual(4.5);
  }
});

test("the header says what waits on the person, in the needs colour, and opens it", async ({ page }) => {
  await openRuns(page);
  await mock("mock.ask", { bot: "kami", kind: "approval" });
  const needs = panel(page).getByTestId("run-plan-needs");
  await expect(needs).toHaveText("1 needs you");
  const [needsColour, sidebarNeeds] = await Promise.all([
    needs.evaluate((e) => getComputedStyle(e).color),
    page.locator(".side").evaluate((e) => {
      const probe = document.createElement("i");
      probe.style.color = document.documentElement.dataset.theme === "light" ? "var(--needs-text)" : "var(--needs)";
      e.appendChild(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return c;
    }),
  ]);
  expect(needsColour).toBe(sidebarNeeds);
  await needs.click();
  await expect(page.getByTestId("timeline").getByTestId("card-approval")).toBeFocused();
});

test("a run that has not started: 'Starts in 0:..' with Start now / Edit as text, which only prefill the composer", async ({ page }) => {
  await openRuns(page, "default");
  await pickRow(page, "Codex coexistence (next)");
  const plan = panel(page).getByTestId("run-plan");
  await expect(plan.getByTestId("run-state")).toHaveText(/^Starts in 0:(0\d|10)$/);
  await expect(plan.getByTestId("run-plan-counts")).toContainText("0 of 6 done");
  await plan.getByTestId("run-plan-start").click();
  const composer = page.getByTestId("composer");
  await expect(composer).toHaveValue("Start run `codex-coexist-next` now");
  await plan.getByTestId("run-plan-edit").click();
  await expect(composer).toHaveValue("Edit the plan of run `codex-coexist-next`: ");
  // every part waits; none is handed out
  await expect(panel(page).locator('[data-testid="run-node"][data-tone="waiting"]')).toHaveCount(6);
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

// ---- the boxes ----

test("a node is its title, one mark with what ran it, and a status icon with a word, in the app's font: a thin neutral outline, one 2px state line, no fill", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  await settled(page);
  await page.mouse.move(400, 28); // off the graph: a box under the pointer answers it
  const nodes = box.getByTestId("run-node");
  await expect(nodes).toHaveCount(6);
  const by: Record<string, { title: string; lines: number; clamp: string; tall: number; cut: boolean; repair: boolean; marks: [string, string][]; facts: string[]; whole: string; status: string; icon: string; children: string[] }> = Object.fromEntries(
    await nodes.evaluateAll((els) =>
      els.map((e) => {
        const texts = (sel: string) => [...e.querySelectorAll(sel)].map((l) => (l.textContent ?? "").trim());
        const title = e.querySelector<HTMLElement>("[data-testid=node-title]")!;
        return [
          e.getAttribute("data-node"),
          {
            title: (title.textContent ?? "").trim(),
            lines: Number(title.getAttribute("data-lines")),
            clamp: getComputedStyle(title).webkitLineClamp,
            tall: Math.round(title.getBoundingClientRect().height),
            cut: title.scrollHeight > title.clientHeight + 1,
            repair: !!title.querySelector("svg[data-icon=repair]"),
            marks: [...e.querySelectorAll("[data-testid=node-mark]")].map((m) => [m.getAttribute("data-kind"), m.getAttribute("data-mark")]),
            facts: texts("[data-testid=node-facts] .bx-fl"),
            whole: e.querySelector("[data-testid=node-facts]")?.getAttribute("title") ?? "",
            status: texts("[data-testid=node-status]")[0],
            icon: e.querySelector("[data-testid=node-status] svg")?.getAttribute("data-icon") ?? "",
            children: [...e.children].map((c) => c.getAttribute("data-testid") ?? ""),
          },
        ];
      }),
    ),
  );
  // line 1: the title, on one line or two of 18px; one longer than that ends in "…" at the end of the second
  expect(by["t3-doctor"]).toMatchObject({ title: "Doctor check for the Codex pack", lines: 2, clamp: "2", tall: 36, cut: false });
  expect(by["t1-hermes"]).toMatchObject({ title: "Codex skill discovery reads .agents/skills (Hermes)", lines: 2, clamp: "2", tall: 36, cut: true });
  for (const n of Object.values(by)) {
    expect([1, 2]).toContain(n.lines);
    expect(n.tall).toBe(n.lines * 18);
  }
  // a node added to repair another carries a small icon before its title, not a glyph
  expect(Object.entries(by).filter(([, n]) => n.repair).map(([id]) => id).sort()).toEqual(["t1-hermes", "t4-fence"]);
  // line 2: ONE mark, then model · effort · category. A lane handed to Codex whose model nobody reported carries
  // Codex's mark and name; its category is "unspecified-high", which is not shown but still says the effort
  expect(by["t2-status-update"]).toMatchObject({ marks: [["agent", "codex"]], facts: ["Codex · high"], whole: "Codex · high" });
  expect(by["t3-doctor"]).toMatchObject({ marks: [["agent", "codex"]], facts: ["Codex · low"] });
  // a Hermes helper with a known model carries that model's maker's mark; the facts stay on one line, and a
  // category the box has no room for is left to the tooltip and the node's detail
  expect(by["t5-verify"]).toMatchObject({ marks: [["model", "claude"]], facts: ["Opus 5.5 · high"], whole: "Opus 5.5 · high · review" });
  for (const n of Object.values(by)) {
    expect(n.marks.length, "one mark, never two in a row").toBe(1);
    expect(n.marks[0][1]).not.toBe("hermes");
  }
  await expect(box.locator(".hermes-ic, [data-agent=hermes]")).toHaveCount(0);
  // a category OMH left unnamed is not shown, and no model is named by its id
  await expect(box.getByTestId("run-canvas")).not.toContainText("unspecified");
  await expect(box.getByTestId("run-canvas")).not.toContainText("opus-5-5");
  // line 3: an icon and a word, then the time
  expect(by["t2-status-update"]).toMatchObject({ status: expect.stringMatching(/^Done \d+m$/), icon: "check" });
  // (a failure its repairs fixed says so before it says how long it took, where the box holds only one of the two)
  expect(by["t1-discovery"]).toMatchObject({ status: expect.stringMatching(/^Failed( \d+m)? · repaired$/), icon: "x" });
  expect(by["t3-doctor"]).toMatchObject({ status: expect.stringMatching(/^Running \d+m$/), icon: "dot" });
  expect(by["t5-verify"]).toMatchObject({ status: "Waiting on 1", icon: "ring" });
  // no glyph of the terminal's box view anywhere in the drawing
  expect(await box.getByTestId("run-canvas").innerText()).not.toMatch(GLYPHS);
  // a box is those three and no more. It names no parent ("← parent +N" is gone, with no "after …" line in its
  // place): every edge is a line, and the node's detail lists what it comes after
  for (const n of Object.values(by)) expect(n.children).toEqual(["node-title", "node-facts", "node-status"]);
  await expect(box.getByTestId("node-parents")).toHaveCount(0);
  await expect(box.getByTestId("run-canvas")).not.toContainText(/\bafter\b/);
  // every line of facts and every status fits its line: the layout measured them in the font they are drawn in,
  // so nothing is left to the browser to cut (in the 460px panel too)
  const cut = () => box.locator("[data-testid=run-node] .bx-ft, [data-testid=run-node] [data-testid=node-status], [data-testid=run-node] .bx-fl").evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent));
  expect(await cut()).toEqual([]);
  await page.setViewportSize({ width: 1100, height: 760 });
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBe(460);
  await expect(nodes).toHaveCount(6);
  expect(await cut()).toEqual([]);
  expect(await nodes.evaluateAll((els) => els.map((e) => (e as HTMLElement).scrollHeight <= (e as HTMLElement).clientHeight))).toEqual(Array(6).fill(true)); // nor is a box too short for its lines
  await page.setViewportSize({ width: 1280, height: 820 });
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBe(552);
  await expect(box.getByTestId("run-canvas")).not.toContainText("Start node");
  // every box: one width, a thin outline, the panel's own surface behind it, nothing else painted at rest
  const surface = await page.getByTestId("details").evaluate((e) => getComputedStyle(e).backgroundColor);
  const probe = (css: string) =>
    box.evaluate((e, value) => {
      const i = document.createElement("i");
      i.style.color = value;
      e.appendChild(i);
      const c = getComputedStyle(i).color;
      i.remove();
      return c;
    }, css);
  const outline = await probe("color-mix(in srgb, var(--line) 60%, var(--bv-surface))");
  const line = await probe("var(--line)");
  const bodyFont = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  const looks = await nodes.evaluateAll((els) =>
    els.map((e) => {
      const s = getComputedStyle(e);
      const rail = getComputedStyle(e, "::before");
      const title = getComputedStyle(e.querySelector("[data-testid=node-title]")!);
      const status = e.querySelector("[data-testid=node-status]")!;
      return {
        tone: e.getAttribute("data-tone"),
        row: e.getAttribute("data-row"),
        w: Math.round(e.getBoundingClientRect().width),
        h: Math.round(e.getBoundingClientRect().height),
        bg: s.backgroundColor,
        image: s.backgroundImage,
        shadow: s.boxShadow,
        filter: s.filter,
        border: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth].join(" "),
        style: [s.borderTopStyle, s.borderRightStyle, s.borderBottomStyle, s.borderLeftStyle].join(" "),
        colors: [s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor],
        radius: s.borderTopLeftRadius,
        padding: s.padding,
        cursor: s.cursor,
        transition: [s.transitionProperty, s.transitionDuration],
        anim: s.animationName,
        after: getComputedStyle(e, "::after").content,
        rail: [rail.width, rail.backgroundImage, rail.backgroundColor, rail.animationName],
        icon: getComputedStyle(status.querySelector("svg")!).color,
        word: getComputedStyle(status.querySelector(".bx-w")!).color,
        font: s.fontFamily,
        size: s.fontSize,
        title: [title.fontSize, title.fontWeight, title.fontFamily],
      };
    }),
  );
  expect(new Set(looks.map((l) => l.w)).size).toBe(1);
  // every box of a row is as tall as the row's longest
  for (const row of new Set(looks.map((l) => l.row))) expect(new Set(looks.filter((l) => l.row === row).map((l) => l.h)).size, `row ${row}`).toBe(1);
  expect(outline).not.toBe(line); // 60% of the line colour is not the line colour
  for (const l of looks) {
    expect(l.bg, "a box has no colour of its own").toBe(surface);
    expect(l.image).toBe("none");
    expect(l.shadow, "no shadow at rest").toBe("none");
    expect(l.filter).toBe("none");
    expect(l.border).toBe("1px 1px 1px 1px");
    expect(l.style, "never dashed, whatever the state").toBe("solid solid solid solid");
    expect(l.colors, "the outline is neutral, at 60% of the line colour: no state tints it").toEqual([outline, outline, outline, outline]);
    expect(l.radius).toBe("6px");
    expect(l.padding).toBe("10px 12px");
    expect(l.cursor).toBe("pointer");
    expect(l.transition[0]).toBe("border-color, box-shadow, transform");
    expect(l.transition[1]).toBe("0.12s, 0.12s, 0.12s");
    expect(l.anim).toBe("none");
    expect(l.after).toBe("none");
    expect(l.rail[0]).toBe("2px");
    expect(l.rail[1]).toBe("none");
    expect(l.rail[3]).toBe("none");
    // the app's own font, 12px (a title 13px medium); monospace is for code and paths only
    expect(l.font).toBe(bodyFont);
    expect(l.font).not.toMatch(/mono|Menlo/i);
    expect(l.size).toBe("12px");
    expect(l.title).toEqual(["13px", "500", bodyFont]);
  }
  // the state is the 2px line and the status icon: a colour per state, none on a node not handed out; the word
  // beside the icon is the text's own colour, whatever the state
  const rail = (tone: string) => looks.find((l) => l.tone === tone)!.rail[2];
  expect(new Set([rail("done"), rail("running"), rail("repaired")]).size).toBe(3);
  expect(rail("waiting")).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  for (const tone of ["done", "running", "repaired"]) expect(looks.find((l) => l.tone === tone)!.icon).toBe(rail(tone));
  expect(new Set(["done", "running", "repaired"].map((tone) => looks.find((l) => l.tone === tone)!.word)).size).toBe(1);
  // the marks are 14px, large enough to tell one maker's from another's
  const marks = await box.getByTestId("run-canvas").getByTestId("node-mark").evaluateAll((els) => els.map((e) => [e.getAttribute("data-mark"), Math.round(e.getBoundingClientRect().width), Math.round(e.querySelector("svg, img")!.getBoundingClientRect().width)]));
  expect(marks).toHaveLength(6); // one a node
  for (const [, size, drawn] of marks) expect([size, drawn]).toEqual([14, 14]);
  await expect(box).not.toContainText("model not logged");
});

test("a node shows the logo of the model that ran it: Claude, OpenAI, Gemini; the agent CLI is 'via Codex' after the facts, never a second logo", async ({ page }) => {
  // the finished fan-out reports models: three lanes went to Codex and ran on Opus 5.5, one never reported a model
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", FAN);
  await settled(page);
  const read = (root: ReturnType<typeof panel>) =>
    root.getByTestId("run-node").evaluateAll((els) =>
      Object.fromEntries(
        els.map((e) => [
          e.getAttribute("data-node"),
          {
            marks: [...e.querySelectorAll("[data-testid=node-mark]")].map((m) => `${m.getAttribute("data-kind")}:${m.getAttribute("data-mark")}`),
            // the mark is the model's own drawing (the header's model pill uses the same)
            logo: e.querySelector("[data-testid=node-mark] svg")?.getAttribute("data-mark") ?? e.querySelector("[data-testid=node-mark] svg")?.getAttribute("data-agent") ?? null,
            whole: e.querySelector("[data-testid=node-facts]")?.getAttribute("title"),
            via: e.querySelector("[data-testid=node-via]")?.textContent ?? null,
          },
        ]),
      ),
    );
  const inPanel = await read(box);
  // a model is known: its maker's mark, and the CLI the lane went to only as words
  expect(inPanel["t3-doctor"]).toMatchObject({ marks: ["model:claude"], logo: "claude", whole: "Opus 5.5 · low · via Codex" });
  expect(inPanel["t1-hermes"]).toMatchObject({ marks: ["model:claude"], whole: "Opus 5.5 · high · via Codex" });
  // no model is known: the CLI's own mark, with its name where the model's would be
  expect(inPanel["t1-discovery"]).toMatchObject({ marks: ["agent:codex"], logo: "codex", whole: "Codex · high", via: null });
  // a Hermes helper: its model's mark alone
  expect(inPanel["t5-verify"]).toMatchObject({ marks: ["model:claude"], whole: "Opus 5.5 · review", via: null });
  for (const n of Object.values(inPanel)) expect(n.marks).toHaveLength(1);
  await expect(box.locator(".hermes-ic, [data-agent=hermes]")).toHaveCount(0);
  // the full view has the room: "via Codex" stands after the facts, quieter than they are
  await box.getByTestId("graph-expand").click();
  const f = full(page);
  await settled(page);
  const wide = await read(f);
  expect(wide["t3-doctor"]).toMatchObject({ marks: ["model:claude"], via: " · via Codex" });
  expect(wide["t1-discovery"].via).toBeNull();
  const via = nodeOf(f, "t3-doctor").getByTestId("node-via");
  const facts = nodeOf(f, "t3-doctor").locator(".bx-ft");
  await expect(facts).toHaveText("Opus 5.5 · low");
  expect(await via.evaluate((e) => getComputedStyle(e).color)).not.toBe(await facts.evaluate((e) => getComputedStyle(e).color));
  // it follows the facts on their line, and nothing but text stands between the mark and it
  const order = await nodeOf(f, "t3-doctor").getByTestId("node-facts").evaluate((e) => [...e.querySelectorAll("svg, img, .bx-ft, [data-testid=node-via]")].map((x) => (x.matches("svg, img") ? "logo" : x.textContent)));
  expect(order).toEqual(["logo", "Opus 5.5 · low", " · via Codex"]); // the same " · " as between the facts
  await page.keyboard.press("Escape");
});

test("the makers' marks: GPT carries OpenAI's, Gemini Google's, Opus and Sonnet Anthropic's, and a model nobody knows carries none", async ({ page }) => {
  await rewrite(page, (op, r) => {
    if (op !== "runs.get" || r.run?.id !== LIVE) return;
    const set = (id: string, fields: Record<string, unknown>) => Object.assign(r.run.nodes.find((n: any) => n.id === id), fields);
    set("t1-discovery", { model: "gpt-6.1", effort: "high" });
    set("t2-status-update", { model: "claude-sonnet-5-5", effort: "medium", executor: undefined, route: "quick" });
    set("t1-hermes", { model: "gemini-3-pro", effort: "high", executor: undefined, route: "deep" });
    set("t4-fence", { model: "mystery-7b", provider: "og", executor: undefined });
  });
  await openRuns(page);
  const box = panel(page);
  await settled(page);
  const facts = async (id: string) => [
    await nodeOf(box, id).getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark"))),
    await nodeOf(box, id).getByTestId("node-facts").getAttribute("title"),
  ];
  expect(await facts("t1-discovery")).toEqual([["openai"], "GPT-6.1 · high · via Codex"]);
  expect(await facts("t2-status-update")).toEqual([["claude"], "Sonnet 5.5 · medium · quick"]);
  expect(await facts("t1-hermes")).toEqual([["gemini"], "Gemini 3 Pro · high · deep"]);
  expect(await facts("t5-verify")).toEqual([["claude"], "Opus 5.5 · high · review"]);
  // its maker has no mark: the name alone, no stand-in dot or letter; its unnamed category still says the effort
  expect(await facts("t4-fence")).toEqual([[], "mystery-7b · high"]);
  // each mark is drawn at its size (14px), readable: it has paint (a path), not an empty box
  for (const id of ["t1-discovery", "t2-status-update", "t1-hermes"]) {
    const svg = nodeOf(box, id).getByTestId("node-mark").locator("svg");
    expect(await svg.evaluate((e) => [Math.round(e.getBoundingClientRect().width), e.querySelectorAll("path").length > 0])).toEqual([14, true]);
  }
});

test("the panel keeps a frontier on one row and draws every edge: a 1.25px line with rounded turns from a parent's bottom to an arrowhead on a child's top", async ({ page }) => {
  for (const size of [
    { width: 1100, height: 760 }, // the 460px panel: the narrowest boxes
    { width: 1280, height: 820 },
  ]) {
    await page.setViewportSize(size);
    await openRuns(page);
    await settled(page);
    const graph = panel(page).getByTestId("run-graph");
    await expect(graph).toHaveAttribute("data-frontiers", "3");
    await expect(graph).toHaveAttribute("data-per-row", "3");
    // seven edges, seven lines: nothing is left to a connector between groups or to a caption
    await expect(graph).toHaveAttribute("data-edges", "7");
    await expect(graph).toHaveAttribute("data-drawn", "7");
    await expect(graph).toHaveAttribute("data-crowded", "0");
    await expect(graph).toHaveAttribute("data-tight", "0");
    await expect(panel(page).getByTestId("run-edge")).toHaveCount(7);
    await expect(panel(page).getByTestId("run-canvas")).not.toContainText("Same frontier");
    const geo = await graph.evaluate((g) => {
      const els = [...g.querySelectorAll<HTMLElement>("[data-testid=run-node]")];
      const rs = els.map((e) => e.getBoundingClientRect());
      const b = g.getBoundingClientRect();
      const boxes = Object.fromEntries(els.map((e) => [e.getAttribute("data-node")!, { x: e.offsetLeft, y: e.offsetTop, w: e.offsetWidth, h: e.offsetHeight }]));
      const lines = [...g.querySelectorAll<SVGPathElement>("[data-testid=run-edge]")].map((p) => {
        const a = p.getPointAtLength(0);
        const s = getComputedStyle(p);
        // the nearest it comes to the side of a box it passes (it runs level with the box, beside it)
        let near = Infinity;
        let through = 0;
        for (let at = 0; at <= p.getTotalLength(); at += 2) {
          const pt = p.getPointAtLength(at);
          for (const r of Object.values(boxes)) {
            if (pt.y <= r.y + 1 || pt.y >= r.y + r.h - 1) continue;
            if (pt.x > r.x && pt.x < r.x + r.w) through++;
            else near = Math.min(near, pt.x <= r.x ? r.x - pt.x : pt.x - (r.x + r.w));
          }
        }
        return { from: p.getAttribute("data-from")!, to: p.getAttribute("data-to")!, d: p.getAttribute("d")!, a: [a.x, a.y], width: s.strokeWidth, dash: s.strokeDasharray, join: s.strokeLinejoin, near, through };
      });
      return {
        boxes,
        lines,
        heads: [...g.querySelectorAll("[data-testid=run-arrow]")].map((p) => ({ to: p.getAttribute("data-to")!, tip: p.getAttribute("data-tip")!.split(",").map(Number), box: [(p as SVGPathElement).getBBox().y, (p as SVGPathElement).getBBox().width, (p as SVGPathElement).getBBox().height] })),
        minW: Math.min(...rs.map((r) => r.width)),
        gap: Number(g.getAttribute("data-gap")),
        left: Math.min(...rs.map((r) => r.left)) - b.left,
        right: b.right - Math.max(...rs.map((r) => r.right)),
        scroll: g.scrollWidth - g.clientWidth,
      };
    });
    // the frontier of three stands on one row; no box is narrower than 120px, and the drawing stays in the panel
    expect(new Set(["t1-hermes", "t4-fence", "t3-doctor"].map((id) => geo.boxes[id].y)).size).toBe(1);
    expect(geo.minW).toBeGreaterThanOrEqual(120);
    expect(geo.left).toBeGreaterThanOrEqual(-0.5);
    expect(geo.right).toBeGreaterThanOrEqual(-0.5);
    expect(geo.scroll).toBeLessThanOrEqual(0);
    // one style of line everywhere: solid, 1.25px, round joins
    for (const l of geo.lines) expect([l.width, l.dash, l.join]).toEqual(["1.25px", "none", "round"]);
    // one line an edge, each from the bottom middle of its parent
    const edges = geo.lines.map((l) => `${l.from}>${l.to}`).sort();
    expect(edges).toEqual(["t1-discovery>t1-hermes", "t1-discovery>t4-fence", "t1-hermes>t5-verify", "t2-status-update>t3-doctor", "t2-status-update>t5-verify", "t3-doctor>t5-verify", "t4-fence>t5-verify"]);
    for (const l of geo.lines) {
      const p = geo.boxes[l.from];
      expect(Math.abs(l.a[1] - (p.y + p.h)), `${l.from}>${l.to} leaves the bottom`).toBeLessThan(1);
      expect(Math.abs(l.a[0] - (p.x + p.w / 2)), `${l.from}>${l.to} leaves the middle`).toBeLessThanOrEqual(1);
      // it turns with a rounded corner (a curve in the path), never a square elbow; straight where it need not turn
      const turns = (l.d.match(/Q/g) ?? []).length;
      expect(l.d).not.toMatch(/[Ll]/);
      if (!/^M[\d.]+,[\d.]+ V[\d.]+$/.test(l.d)) expect(turns, `${l.from}>${l.to}`).toBeGreaterThanOrEqual(2);
      // it runs through no box, and passes none nearer than 7px
      expect(l.through, `${l.from}>${l.to} through a box`).toBe(0);
      expect(l.near, `${l.from}>${l.to} beside a box`).toBeGreaterThanOrEqual(7);
    }
    // the long edge (Honest pack status → Independent verify) passes the row of three. Every row stands on one
    // grid, so its parent stands right over a space between two of the three: the line comes straight down it,
    // never round the row. The 460px panel stands its narrowest boxes as far apart as three to a row allow
    // (24px and what the rounding leaves), a wider one a lane's width (28px)
    const skip = geo.lines.find((l) => l.from === "t2-status-update" && l.to === "t5-verify")!;
    const row = ["t1-hermes", "t4-fence", "t3-doctor"].map((id) => geo.boxes[id]);
    const lane = Number(/^M([\d.]+),/.exec(skip.d)?.[1] ?? NaN);
    expect(Number.isFinite(lane)).toBe(true);
    expect(lane > Math.min(...row.map((r) => r.x + r.w)) && lane < Math.max(...row.map((r) => r.x)), `the lane at ${lane} runs between two boxes`).toBe(true);
    expect(geo.gap).toBeGreaterThanOrEqual(size.width === 1100 ? 24 : 28);
    // in the middle of that space: 12px (14px) from the box on either side
    expect(skip.near).toBeGreaterThanOrEqual(size.width === 1100 ? 12 : 13);
    // straight down from the parent, one turn into the line the three boxes of that row send down, and with it
    // into the last node
    expect(skip.d).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+ Q[\d.]+,[\d.]+ [\d.]+,[\d.]+ H[\d.]+ Q[\d.]+,[\d.]+ [\d.]+,[\d.]+ V[\d.]+$/);
    // it joins that line, it does not cross it: no line is broken anywhere
    for (const l of geo.lines) expect(l.d, `${l.from}>${l.to}`).not.toMatch(/ M/);
    // every arrowhead is small and filled, and touches the top edge of the box it points into, off its corners
    expect(geo.heads.map((h) => h.to).sort()).toEqual(["t1-hermes", "t3-doctor", "t4-fence", "t5-verify"]);
    for (const h of geo.heads) {
      const c = geo.boxes[h.to];
      expect(h.tip[1]).toBe(c.y);
      expect(h.tip[0]).toBeGreaterThanOrEqual(c.x + 13);
      expect(h.tip[0]).toBeLessThanOrEqual(c.x + c.w - 13);
      // 7px wide, 5px tall, standing on the box's top edge and pointing down into it
      expect(h.box.map(Math.round)).toEqual([c.y - 5, 7, 5]);
    }
    // the four lines into the last node (three from right above it, one from further up) come into it as one:
    // a single arrowhead, on the middle of its top
    const into = geo.heads.filter((h) => h.to === "t5-verify");
    expect(into).toHaveLength(1);
    expect(Math.abs(into[0].tip[0] - (geo.boxes["t5-verify"].x + geo.boxes["t5-verify"].w / 2))).toBeLessThanOrEqual(1);
    expect(geo.lines.filter((l) => l.to === "t5-verify")).toHaveLength(4);
  }
});

test("full view: every line leaves a parent's bottom and ends with an arrowhead on a child's top, all in one muted colour", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  const graph = f.getByTestId("run-graph");
  // every edge is a line here too
  await expect(graph).toHaveAttribute("data-edges", "7");
  await expect(graph).toHaveAttribute("data-drawn", "7");
  await expect(f.getByTestId("run-canvas")).not.toContainText("Same frontier");
  await settled(page);
  await page.mouse.move(262, 880);
  // no box names a parent: no "Start node", no "←", no line in their place. The lines say it
  await expect(f.getByTestId("node-parents")).toHaveCount(0);
  await expect(f.getByTestId("run-canvas")).not.toContainText("Start node");
  expect(await f.getByTestId("run-canvas").innerText()).not.toMatch(GLYPHS);
  const geo = await graph.evaluate((g) => {
    const box = (id: string) => {
      const e = g.querySelector(`[data-testid="run-node"][data-node="${id}"]`) as HTMLElement;
      return { x: e.offsetLeft, y: e.offsetTop, w: e.offsetWidth, h: e.offsetHeight, rail: getComputedStyle(e, "::before").backgroundColor };
    };
    const lines = [...g.querySelectorAll<SVGPathElement>("[data-testid=run-edge]")].map((p) => {
      const a = p.getPointAtLength(0);
      const b = p.getPointAtLength(p.getTotalLength());
      const s = getComputedStyle(p);
      return { from: p.getAttribute("data-from")!, to: p.getAttribute("data-to")!, a: [a.x, a.y], b: [b.x, b.y], stroke: s.stroke, width: s.strokeWidth, dash: s.strokeDasharray, anim: s.animationName };
    });
    const heads = [...g.querySelectorAll("[data-testid=run-arrow]")].map((p) => ({ to: p.getAttribute("data-to")!, tip: p.getAttribute("data-tip")!.split(",").map(Number), fill: getComputedStyle(p).fill }));
    const ids = [...g.querySelectorAll("[data-testid=run-node]")].map((e) => e.getAttribute("data-node")!);
    return { boxes: Object.fromEntries(ids.map((id) => [id, box(id)])), lines, heads };
  });
  expect(geo.lines).toHaveLength(7);
  for (const l of geo.lines) expect(l.width).toBe("1.25px");
  // a line starts on its parent's bottom edge, at its middle, and ends an arrowhead short of its child's top
  for (const l of geo.lines) {
    const [p, c] = [geo.boxes[l.from], geo.boxes[l.to]];
    expect(Math.abs(l.a[1] - (p.y + p.h))).toBeLessThan(1);
    expect(Math.abs(l.a[0] - (p.x + p.w / 2))).toBeLessThanOrEqual(1);
    expect(Math.abs(l.b[1] - (c.y - 5))).toBeLessThan(1);
    expect(l.b[0]).toBeGreaterThan(c.x);
    expect(l.b[0]).toBeLessThan(c.x + c.w);
  }
  expect([...new Set(geo.lines.map((l) => l.from))].sort()).toEqual(["t1-discovery", "t1-hermes", "t2-status-update", "t3-doctor", "t4-fence"]);
  // one muted colour for every line and arrowhead, whatever the state of its parent: no state colours a line
  expect(new Set(geo.lines.map((l) => l.stroke)).size).toBe(1);
  expect(new Set(geo.heads.map((h) => h.fill))).toEqual(new Set([geo.lines[0].stroke]));
  const rails = new Set(Object.values(geo.boxes).map((b) => b.rail));
  expect(rails.has(geo.lines[0].stroke)).toBe(false);
  const [r, g2, b2] = geo.lines[0].stroke.match(/\d+/g)!.map(Number);
  expect(Math.max(r, g2, b2) - Math.min(r, g2, b2), "the line colour is a gray").toBeLessThanOrEqual(24);
  // every arrowhead touches the top edge of the box it points into, inside its width
  expect(geo.heads.map((h) => h.to).sort()).toEqual(["t1-hermes", "t3-doctor", "t4-fence", "t5-verify"]);
  for (const h of geo.heads) {
    const c = geo.boxes[h.to];
    expect(h.tip[1]).toBe(c.y);
    expect(h.tip[0]).toBeGreaterThan(c.x);
    expect(h.tip[0]).toBeLessThan(c.x + c.w);
  }
  // one style of line: solid, and none of them moves
  for (const l of geo.lines) expect([l.dash, l.anim]).toEqual(["none", "none"]);
  // the only motion: a dash that rides the edge into the running node, the whole of it (not a tick above the
  // arrowhead), from its parent's bottom into its top
  const flows = await f.getByTestId("run-flow").evaluateAll((els) =>
    els.map((e) => {
      const p = e as SVGPathElement;
      const [a, b] = [p.getPointAtLength(0), p.getPointAtLength(p.getTotalLength())];
      return { from: p.getAttribute("data-from"), to: p.getAttribute("data-to"), anim: getComputedStyle(p).animationName, dash: getComputedStyle(p).strokeDasharray, len: p.getTotalLength(), a: [a.x, a.y], b: [b.x, b.y] };
    }),
  );
  expect(flows).toHaveLength(1);
  expect(flows[0]).toMatchObject({ from: "t2-status-update", to: "t3-doctor", anim: "bv-flow", dash: "4px, 10px" });
  const edge = geo.lines.find((l) => l.from === "t2-status-update" && l.to === "t3-doctor")!;
  // drawn from the child back to its parent: it starts where the edge ends
  expect(flows[0].a.map(Math.round)).toEqual(edge.b.map(Math.round));
  expect(flows[0].b.map(Math.round)).toEqual(edge.a.map(Math.round));
  expect(flows[0].len).toBeGreaterThan(60);
});

test("hovering a box lights its own lines and steps the rest back; the box answers the pointer: full outline, a highlight, a soft shadow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await settled(page);
  await page.mouse.move(262, 880);
  const strokes = () => f.getByTestId("run-edge").evaluateAll((els) => els.map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), e.classList.contains("lit"), getComputedStyle(e).stroke, getComputedStyle(e).opacity]));
  const rest = new Set((await strokes()).map((l) => l[3]));
  expect(rest.size).toBe(1);
  const node = nodeOf(f, "t2-status-update");
  const calm = await node.evaluate((e) => [getComputedStyle(e).borderTopColor, getComputedStyle(e).boxShadow]);
  await node.hover();
  await eased(page); // the 120ms ease
  const lit = await strokes();
  const own = lit.filter(([from, to]) => from === "t2-status-update" || to === "t2-status-update");
  expect(own).toHaveLength(2);
  // its own lines step forward, the others back: by colour, never by opacity (the edges of a net lie on each other)
  const [resting] = [...rest];
  for (const [, , on, stroke, opacity] of own) {
    expect([on, opacity]).toEqual([true, "1"]);
    expect(stroke).not.toBe(resting);
  }
  const others = lit.filter(([from, to]) => from !== "t2-status-update" && to !== "t2-status-update");
  expect(others).toHaveLength(5);
  for (const [, , on, stroke, opacity] of others) {
    expect([on, opacity]).toEqual([false, "1"]);
    expect(stroke).not.toBe(resting);
    expect(stroke).not.toBe(own[0][3]);
  }
  // lit lines are drawn last, on top of the ones they share a stretch with
  expect(lit.slice(-2).every((l) => l[2])).toBe(true);
  // the box under the pointer: the outline at the line colour's full strength, a 1px highlight inside its top
  // edge, and a soft shadow (0 4px 12px) that it does not have at rest
  const line = await f.evaluate((e) => {
    const i = document.createElement("i");
    i.style.color = "var(--line)";
    e.appendChild(i);
    const c = getComputedStyle(i).color;
    i.remove();
    return c;
  });
  const hot = await node.evaluate((e) => [getComputedStyle(e).borderTopColor, getComputedStyle(e).boxShadow, getComputedStyle(e).cursor, getComputedStyle(e).backgroundImage]);
  expect(calm[1]).toBe("none");
  expect(hot[0]).toBe(line);
  expect(hot[0]).not.toBe(calm[0]);
  expect(hot[1]).toMatch(/0px 1px 0px 0px inset/);
  expect(hot[1]).toMatch(/rgba\(0, 0, 0, 0\.08\) 0px 4px 12px 0px/); // the light theme's (a test's default); dark is below
  expect(hot[2]).toBe("pointer");
  expect(hot[3]).toBe("none"); // still no fill
  // the boxes it has no edge with step back too: their text, not the box (a line behind it must not show through)
  await expect(nodeOf(f, "t3-doctor")).not.toHaveClass(/\bdim\b/);
  const far = nodeOf(f, "t1-discovery");
  await expect(far).toHaveClass(/\bdim\b/);
  expect(await far.evaluate((e) => [getComputedStyle(e).opacity, getComputedStyle(e.querySelector("[data-testid=node-title]")!).opacity])).toEqual(["1", "0.45"]);
  await page.mouse.move(5, 5);
  await expect(f.locator(".bx.dim")).toHaveCount(0);
  await expect.poll(async () => new Set((await strokes()).map((l) => l[3])).size).toBe(1);
});

test("dark theme: the shadow under the pointer is a quarter black, and a box still has no fill", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await settled(page);
  const node = nodeOf(f, "t2-status-update");
  await node.hover();
  await eased(page);
  const [shadow, bg, surface] = await node.evaluate((e) => [getComputedStyle(e).boxShadow, getComputedStyle(e).backgroundColor, getComputedStyle(e.closest(".rf")!).backgroundColor]);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
  expect(shadow).toMatch(/rgba\(0, 0, 0, 0\.25\) 0px 4px 12px 0px/);
  expect(bg).toBe(surface);
  await ctx.close();
});

test("Dependencies and Node details are plain text under the boxes", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  const deps = box.getByTestId("run-deps");
  await expect(deps.locator("h4")).toHaveText("Dependencies");
  await expect(deps.getByTestId("run-dep")).toHaveCount(7);
  // a row is the two titles with an arrow drawn between them (an icon, which says "→" to a screen reader)
  const third = deps.getByTestId("run-dep").nth(2);
  expect(await third.locator(".bv-dep-n").allTextContents()).toEqual(["Honest pack status + omh update refresh", "Doctor check for the Codex pack"]);
  await expect(third).toHaveAttribute("title", "Honest pack status + omh update refresh → Doctor check for the Codex pack");
  await expect(third.locator("svg.bv-arrow")).toHaveAttribute("aria-label", "→");
  expect([await third.getAttribute("data-from"), await third.getAttribute("data-to")]).toEqual(["t2-status-update", "t3-doctor"]);
  await expect(deps.getByTestId("run-dep").filter({ hasText: "(repair)" })).toHaveCount(2);
  // a card of text for the running node: its whole title, what ran it (marks, model · effort · category), status, layer
  const details = box.getByTestId("run-details");
  await expect(details.locator("h4")).toHaveText("Node details");
  const card = details.getByTestId("run-detail");
  await expect(card).toHaveCount(1);
  await expect(card).toHaveAttribute("data-node", "t3-doctor");
  expect((await card.innerText()).split("\n").map((s) => s.trim()).filter(Boolean)).toEqual(["Doctor check for the Codex pack", "Codex · low", expect.stringMatching(/^Running \d+m · layer 2 · /)]);
  // its status is the running dot, as on its box; one mark
  await expect(card.locator("svg[data-icon]")).toHaveAttribute("data-icon", "dot");
  expect(await card.getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(["codex"]);
  // all of it in the app's own font: monospace is for code and paths only
  const fonts = await box.locator(".bv-sec, .bv-sec *").evaluateAll((els) => [...new Set(els.map((e) => getComputedStyle(e).fontFamily))]);
  expect(fonts).toEqual([await page.evaluate(() => getComputedStyle(document.body).fontFamily)]);
  expect(await box.locator(".bv-sec").first().innerText()).not.toMatch(GLYPHS);
  const plain = await box.locator(".bv-sec, .bv-sec *").evaluateAll((els) =>
    els.filter((e) => {
      const s = getComputedStyle(e);
      return s.backgroundImage !== "none" || s.boxShadow !== "none" || parseFloat(s.borderTopWidth) > 0;
    }).length,
  );
  expect(plain).toBe(0);
  // the card opens the node
  await card.click();
  await expect(page.getByTestId("run-drawer")).toHaveAttribute("data-node", "t3-doctor");
});

test("full view: the text under the boxes keeps its own clicks and keys while the canvas pans", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await expect(f.getByTestId("run-node")).toHaveCount(40);
  await f.getByTestId("run-fit").click();
  // "Show all" on the Dependencies list is a button inside the canvas the pointer pans
  const more = f.getByTestId("run-deps-more");
  await expect(f.getByTestId("run-dep")).toHaveCount(12);
  await more.click();
  await expect(f.getByTestId("run-dep")).not.toHaveCount(12);
  await expect(more).toHaveText("Show fewer");
  await more.click();
  await expect(f.getByTestId("run-dep")).toHaveCount(12);
  // a Node details card opens its node
  const card = f.getByTestId("run-detail").first();
  const id = await card.getAttribute("data-node");
  await card.click();
  await expect(f.getByTestId("run-drawer")).toHaveAttribute("data-node", id!);
  // and it stays open: the click did not also land on the canvas, which closes the drawer
  await page.waitForTimeout(200);
  await expect(f.getByTestId("run-drawer")).toHaveCount(1);
  await f.getByRole("button", { name: "Close node" }).click();
  await expect(f.getByTestId("run-drawer")).toHaveCount(0);
  // the keyboard opens a box too: focus it, Enter
  const node = f.getByTestId("run-node").first();
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(f.getByTestId("run-drawer")).toHaveAttribute("data-node", (await node.getAttribute("data-node"))!);
});

test("a plan cancelled before anything started says Cancelled, not 'Not started', and offers nothing to start", async ({ page }) => {
  // the mock's plan nobody has started, cancelled
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      const op = ops.get(msg.id);
      if (msg.ok && op === "runs.list") for (const r of msg.result.runs) if (r.id.endsWith("/codex-coexist-next")) r.state = "cancelled";
      if (msg.ok && op === "runs.get" && msg.result.run?.id.endsWith("/codex-coexist-next")) {
        msg.result.run.state = "cancelled";
        for (const n of msg.result.run.nodes) n.state = "cancelled";
      }
      ws.send(op === "runs.list" || op === "runs.get" ? JSON.stringify(msg) : raw);
    });
  });
  await openRuns(page, "default");
  await pickRow(page, "Codex coexistence (next)");
  const plan = panel(page).getByTestId("run-plan");
  await expect(panel(page).locator('[data-testid="run-node"][data-state="cancelled"]')).toHaveCount(6);
  await expect(plan.getByTestId("run-state")).toHaveText("Cancelled");
  await expect(plan).not.toContainText("Not started");
  await expect(plan.getByTestId("run-plan-start")).toHaveCount(0);
  await expect(plan.getByTestId("run-plan-edit")).toHaveCount(0);
});

test("clicking a node opens its detail under 'Node details'; a failed node offers 'Ask in chat', which only prefills the composer", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  const box = panel(page);
  await box.locator('[data-testid="run-node"][data-node="t5-verify"]').click();
  const drawer = page.getByTestId("run-drawer");
  await expect(drawer).toContainText("Independent verify vs base + live probes");
  // it sits under the Node details heading, as text: no card around it in the panel
  await expect(box.getByTestId("run-details").getByTestId("run-drawer")).toHaveCount(1);
  expect(await drawer.evaluate((e) => [getComputedStyle(e).borderTopWidth, getComputedStyle(e).backgroundImage, getComputedStyle(e).boxShadow])).toEqual(["0px", "none", "none"]);
  await expect(box.locator('[data-testid="run-node"][data-node="t5-verify"]')).toHaveAttribute("aria-pressed", "true");
  await expect(drawer.getByTestId("run-attempt")).toHaveText("attempt 2 of 2");
  // the nodes it comes after, as the graph draws its lines (the failed node's repairs stand in for it)
  await expect(drawer.getByTestId("run-after")).toHaveText("after Honest pack status + omh update refresh, Codex skill discovery reads .agents/skills (Hermes), Fence allows zsh heredocs and uv cache, Doctor check for the Codex pack");
  expect(await drawer.evaluate((e) => getComputedStyle(e).fontFamily)).not.toMatch(/mono|Menlo/i);
  // what ran it, as its box says it: the model's mark, then model · effort · category; no raw "unspecified-*" route
  const boxFacts = await box.locator('[data-testid="run-node"][data-node="t5-verify"]').getByTestId("node-facts").getAttribute("title");
  expect(boxFacts).toBe("Opus 5.5 · review");
  await expect(drawer.getByTestId("run-facts")).toHaveText(boxFacts!);
  expect(await drawer.getByTestId("run-facts").getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(
    await box.locator('[data-testid="run-node"][data-node="t5-verify"]').getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark"))),
  );
  await expect(drawer).not.toContainText("unspecified");
  await expect(drawer.getByTestId("run-reason")).toContainText("2nd verifier HOLD");
  await expect(drawer.getByTestId("run-handoff")).toBeVisible();
  const before = (await drawer.getByTestId("run-handoff").innerText()).length;
  await drawer.getByTestId("run-handoff-more").click();
  await expect.poll(async () => (await drawer.getByTestId("run-handoff").innerText()).length).toBeGreaterThan(before);
  // selection is a 1.5px gray ring, on top of any state: the 1px outline and half a pixel around it, one gray
  await page.mouse.move(400, 28);
  await eased(page);
  const ring = await box.locator('[data-testid="run-node"][data-node="t5-verify"]').evaluate((e) => [getComputedStyle(e).borderTopColor, getComputedStyle(e).backgroundImage, getComputedStyle(e).boxShadow, getComputedStyle(e).borderTopWidth]);
  const [r, g, b] = ring[0].match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThanOrEqual(24);
  expect(ring[1]).toBe("none");
  expect(ring[2]).toBe(`${ring[0]} 0px 0px 0px 0.5px`);
  expect(ring[3]).toBe("1px");
  // the keyboard's focus is a ring of its own, outside the box
  await box.locator('[data-testid="run-node"][data-node="t4-fence"]').focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  expect(await box.locator('[data-testid="run-node"][data-node="t4-fence"]').evaluate((e) => [getComputedStyle(e).outlineStyle, getComputedStyle(e).outlineWidth, getComputedStyle(e).outlineOffset])).toEqual(["solid", "2px", "2px"]);
  // the failed node: a red "failed", the reason, a quiet prefill button
  await box.locator('[data-testid="run-node"][data-node="t1-discovery"]').click();
  await expect(drawer).toHaveClass(/\bbad\b/);
  const word = drawer.getByTestId("run-state-word");
  await expect(word).toHaveText("failed");
  // its lane went to Codex and no model was reported: Codex, and the effort its unnamed category says
  await expect(drawer.getByTestId("run-facts")).toHaveText("Codex · high");
  expect(await drawer.getByTestId("run-facts").getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(["codex"]);
  await expect(drawer).not.toContainText("unspecified");
  expect(await word.evaluate((e) => getComputedStyle(e).color)).not.toBe(await drawer.evaluate((e) => getComputedStyle(e).color));
  await expect(drawer).toContainText("No handoff written.");
  await drawer.getByTestId("run-ask").click();
  const composer = page.getByTestId("composer");
  await expect(composer).toHaveValue("Retry `t1-discovery` in run `codex-coexist`");
  await expect(composer).toBeFocused();
  // nothing was sent, and nothing in the graph writes
  expect(await panel(page).getByRole("button", { name: /^(retry|cancel|settle|stop)$/i }).count()).toBe(0);
  expect(await page.getByTestId("details-panel").locator("textarea, input, [contenteditable=true]").count()).toBe(0);
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
  expect(calls).toEqual(expect.arrayContaining(["runs.list", "runs.get"]));
});

test("a cancelled run says so in its header and on its unfinished nodes", async ({ page }) => {
  await openRuns(page);
  await showList(page);
  const r = rowOf(page, "omh-dap");
  await expect(r.locator("i").first()).toHaveAttribute("aria-label", "cancelled");
  await r.click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CANCELLED);
  await expect(box.getByTestId("run-state")).toHaveText("Cancelled");
  const off = box.locator('[data-testid="run-node"][data-state="cancelled"]');
  await expect(off).toHaveCount(2);
  await expect(off.first().getByTestId("node-status")).toHaveText("Cancelled");
  await expect(off.first().getByTestId("node-status").locator("svg")).toHaveAttribute("data-icon", "off");
  // it has no state line, and its outline is the one every box has
  expect(await off.first().evaluate((e) => [getComputedStyle(e).borderTopStyle, getComputedStyle(e, "::before").backgroundColor])).toEqual(["solid", "rgba(0, 0, 0, 0)"]);
});

// ---- big runs ----

test("88 sub-runs: the first 8 rows, running then failed first; 'Show all 88' opens the rest", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await grow88(page);
  await openRuns(page);
  await pickRow(page, /\/88 · /, "cli-run-row");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CLI_CODEX);
  // a CLI session's header names the CLI and the folder it ran in
  await expect(box.getByTestId("run-plan-counts")).toHaveText(/^Completed · 84 of 88 done · 1 failed · \d+s$/);
  await expect(box.getByTestId("run-plan-where")).toHaveText("Codex · api-server");
  const graph = box.getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-frontiers", "1");
  const cards = box.getByTestId("run-node");
  await expect(cards).toHaveCount(24);
  expect((await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).slice(0, 5)).toEqual(["running", "running", "running", "failed", "done"]);
  // one frontier: no line, no caption
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
  await expect(box.getByTestId("run-canvas")).not.toContainText("Same frontier");
  await expect(cards.nth(4).getByTestId("node-status")).toHaveText(/^Done \d+s$/);
  // a Codex session's sub-runs carry the mark of the model each ran on (GPT-6 Astra: OpenAI's), one a node
  expect(new Set(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")}:${e.getAttribute("data-mark")}`)))).toEqual(new Set(["model:openai"]));
  await expect(box.getByTestId("run-canvas").getByTestId("node-mark")).toHaveCount(24);
  // three to a row, one width, inside the panel
  const geo = await graph.evaluate((g) => {
    const b = g.getBoundingClientRect();
    const rs = [...g.querySelectorAll("[data-testid=run-node]")].map((c) => c.getBoundingClientRect());
    return { cols: new Set(rs.map((r) => Math.round(r.left))).size, widths: new Set(rs.map((r) => Math.round(r.width))).size, inside: rs.every((r) => r.left >= b.left - 0.5 && r.right <= b.right + 0.5) };
  });
  expect(geo).toEqual({ cols: 3, widths: 1, inside: true });
  // a long title takes two lines and is cut at the end of the second with "…"; a short one takes one. The boxes
  // of a row are one height whichever they hold
  const long = await box.locator('[data-testid="run-node"][data-node="sub-0"] [data-testid="node-title"]').evaluate((e) => [e.getAttribute("data-lines"), getComputedStyle(e).webkitLineClamp, getComputedStyle(e).overflow, e.scrollHeight > e.clientHeight + 1, Math.round(e.getBoundingClientRect().height)]);
  expect(long).toEqual(["2", "2", "hidden", true, 36]);
  expect(await box.locator('[data-testid="run-node"][data-node="sub-1"] [data-testid="node-title"]').evaluate((e) => [e.getAttribute("data-lines"), Math.round(e.getBoundingClientRect().height)])).toEqual(["1", 18]);
  const rows = await cards.evaluateAll((els) => els.map((e) => [e.getAttribute("data-row"), Math.round(e.getBoundingClientRect().height), Math.round(e.getBoundingClientRect().top)]));
  for (const row of new Set(rows.map((r) => r[0]))) {
    expect(new Set(rows.filter((r) => r[0] === row).map((r) => r[1])).size, `row ${row}: one height`).toBe(1);
    expect(new Set(rows.filter((r) => r[0] === row).map((r) => r[2])).size, `row ${row}: one top`).toBe(1);
  }
  // "Show all 88" is a line of text under the rows; it shows them all, and back
  const more = box.getByTestId("run-more");
  await expect(more).toHaveText("+64 more · Show all 88");
  // it stands over the space the row's lines leave through: opaque, so a line passes behind it, not through its text
  expect(await more.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(await page.getByTestId("details").evaluate((e) => getComputedStyle(e).backgroundColor));
  await more.click();
  await expect(cards).toHaveCount(88);
  await expect(more).toHaveText("Show fewer");
  await more.click();
  await expect(cards).toHaveCount(24);
  // the full view shows every sub-run; none has a parent to name
  await box.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(88);
  await expect(full(page).getByTestId("run-more")).toHaveCount(0);
  await expect(full(page).getByTestId("node-parents")).toHaveCount(0);
  await expect(full(page).getByTestId("run-canvas")).not.toContainText("Start node");
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("40 nodes: every edge is a line and no two boxes overlap, in the panel or the full view; the panel never scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  await expect(panel(page)).toHaveAttribute("data-run", BIG);
  await expect(panel(page).getByTestId("run-node")).toHaveCount(40);
  const overlaps = (root: ReturnType<typeof panel>) =>
    root.getByTestId("run-node").evaluateAll((els) => {
      const rs = els.map((e) => e.getBoundingClientRect());
      let n = 0;
      for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) if (rs[i].left < rs[j].right - 0.5 && rs[j].left < rs[i].right - 0.5 && rs[i].top < rs[j].bottom - 0.5 && rs[j].top < rs[i].bottom - 0.5) n++;
      return [rs.length, n];
    });
  // every edge between two boxes has its line, each line a place of its own beside the rows it passes
  const lines = async (root: ReturnType<typeof panel>) => {
    const g = root.getByTestId("run-graph");
    return [Number(await g.getAttribute("data-edges")) > 40, (await g.getAttribute("data-drawn")) === (await g.getAttribute("data-edges")), await g.getAttribute("data-crowded")];
  };
  expect(await overlaps(panel(page))).toEqual([40, 0]);
  expect(await lines(panel(page))).toEqual([true, true, "0"]);
  expect(await page.locator(".details .pn-scroll").evaluate((e) => e.scrollWidth - e.clientWidth)).toBeLessThanOrEqual(0);
  // its many edges are a capped list of text
  await expect(panel(page).getByTestId("run-dep")).toHaveCount(12);
  await expect(panel(page).getByTestId("run-deps-more")).toHaveText(/^\+\d+ more · Show all \d+$/);
  await panel(page).getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(40);
  expect(await overlaps(full(page))).toEqual([40, 0]);
  expect(await lines(full(page))).toEqual([true, true, "0"]);
  // the full view keeps each frontier on one row (its nine-wide one too: the drawing is a little wider than the
  // window and shown that much smaller), so only the edges that skip a frontier pass a row
  const g = full(page).getByTestId("run-graph");
  const rows = () => full(page).getByTestId("run-node").evaluateAll((els) => new Set(els.map((e) => e.getAttribute("data-row"))).size);
  await expect.poll(rows).toBe(Number(await g.getAttribute("data-frontiers"))); // once the panel stepped aside
  expect(await lines(full(page))).toEqual([true, true, "0"]);
  // no arrowhead stands on another: on any box, two are at least 12px apart
  const tips = await full(page).getByTestId("run-arrow").evaluateAll((els) => els.map((e) => [e.getAttribute("data-to"), Number(e.getAttribute("data-tip")!.split(",")[0])] as [string, number]));
  for (const to of new Set(tips.map((t) => t[0]))) {
    const xs = tips.filter((t) => t[0] === to).map((t) => t[1]).sort((a, b) => a - b);
    for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1], `two arrowheads on ${to}`).toBeGreaterThanOrEqual(12);
  }
});

// ---- full view ----

test("⌘⇧G and 'Full view' open the full view over the chat; Esc and × close it; the header keeps one control", async ({ page }) => {
  await openRuns(page);
  const m = await mod(page);
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(full(page)).toBeVisible();
  // everything right of the sidebar; the side panel steps aside and comes back on close
  const vw = page.viewportSize()!.width;
  await expect.poll(async () => Math.round(await full(page).evaluate((e) => e.getBoundingClientRect().right))).toBe(vw);
  const side = await page.locator(".pane").evaluate((e) => e.getBoundingClientRect().x);
  expect(Math.round((await full(page).boundingBox())!.x)).toBe(Math.round(side));
  await expect(page.getByTestId("details")).toBeHidden();
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);
  await expect(full(page).getByTestId("run-node")).toHaveCount(6);
  // the same plain header, and the drawing at the text's own size from the top
  await expect(full(page).getByTestId("run-plan-title")).toHaveText("Codex coexistence (live)");
  await expect(full(page).getByTestId("run-plan-counts")).toHaveText(/^Running · 3 of 6 done · /);
  await expect(full(page).getByTestId("run-graph")).toHaveAttribute("data-zoom", "1.00");
  expect(await full(page).getByTestId("run-node").first().evaluate((e) => [getComputedStyle(e).fontSize, getComputedStyle(e.querySelector("[data-testid=node-title]")!).fontSize])).toEqual(["12px", "13px"]);
  // a box has the room here: no wider than 256px, its facts on one line
  expect(await full(page).getByTestId("run-node").first().evaluate((e) => e.offsetWidth)).toBeLessThanOrEqual(256);
  // the tools under the drawing are in the app's font too
  expect(await full(page).locator(".bv-tools").evaluate((e) => getComputedStyle(e).fontFamily)).not.toMatch(/mono|Menlo/i);
  const top = await full(page).evaluate((f) => {
    const g = f.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    return Math.min(...[...f.querySelectorAll("[data-testid=run-node]")].map((e) => e.getBoundingClientRect().top)) - g.top;
  });
  expect(top).toBeLessThanOrEqual(40);
  await page.keyboard.press("Escape");
  await expect(full(page)).toHaveCount(0);
  await expect(page.getByTestId("details")).toBeVisible();
  await expect(panel(page)).toBeVisible();
  await page.getByTestId("graph-expand").click();
  await expect(full(page)).toBeVisible();
  await full(page).getByRole("button", { name: "Close graph" }).click();
  await expect(full(page)).toHaveCount(0);
});

test("full view: drag moves a box and its lines; the position is kept; Reset restores; a click opens the drawer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await settled(page);
  const card = f.locator('[data-testid="run-node"][data-node="t3-doctor"]');
  const head = f.locator('[data-testid="run-arrow"][data-to="t3-doctor"]');
  const before = await card.boundingBox();
  const tipBefore = await head.getAttribute("data-tip");
  const home = await card.evaluate((e: HTMLElement) => e.offsetLeft);
  const others = () => f.locator('[data-testid="run-edge"]:not([data-from="t3-doctor"]):not([data-to="t3-doctor"])').evaluateAll((els) => els.map((e) => e.getAttribute("d")));
  const untouched = await others();
  await page.mouse.move(before!.x + 30, before!.y + 20);
  await page.mouse.down();
  await expect(card).not.toHaveClass(/\blift\b/); // held, not moved yet
  await page.mouse.move(before!.x + 90, before!.y + 60, { steps: 6 });
  // while it is dragged the box lifts: a little larger, with the soft shadow; its lines follow it live
  await expect(card).toHaveClass(/\blift\b/);
  await eased(page);
  const held = await card.evaluate((e) => [getComputedStyle(e).transform, getComputedStyle(e).boxShadow, getComputedStyle(e).cursor]);
  expect(held[0]).toBe("matrix(1.02, 0, 0, 1.02, 0, 0)");
  expect(held[1]).toMatch(/0px 4px 12px 0px/);
  expect(held[2]).toBe("grabbing");
  expect(await head.getAttribute("data-tip")).not.toBe(tipBefore);
  // the lines of the boxes it has no edge with run where the layout ran them, and none of them is broken (a line
  // leaves a gap only where it passes over another's level stretch, and none does here, before or after)
  const way = (d: string | null) => (d ?? "").replace(/ V[\d.]+ M[\d.]+,[\d.]+/g, "");
  const gaps = (ds: (string | null)[]) => ds.reduce((n, d) => n + ((d ?? "").match(/ M/g) ?? []).length, 0);
  expect((await others()).map(way)).toEqual(untouched.map(way));
  expect([gaps(untouched), gaps(await others())]).toEqual([0, 0]);
  await page.mouse.up();
  await expect(card).not.toHaveClass(/\blift\b/);
  await page.mouse.move(262, 880);
  await eased(page);
  expect(await card.evaluate((e) => [getComputedStyle(e).transform, getComputedStyle(e).boxShadow])).toEqual(["none", "none"]);
  const after = await card.boundingBox();
  expect(Math.round(after!.x - before!.x)).toBe(60);
  expect(Math.round(after!.y - before!.y)).toBe(40);
  await expect(page.getByTestId("run-drawer")).toHaveCount(0); // a drag is not a click
  // its arrowhead moved with it, and still touches its top edge
  expect(await head.getAttribute("data-tip")).not.toBe(tipBefore);
  const [tx, ty] = (await head.getAttribute("data-tip"))!.split(",").map(Number);
  const local = await card.evaluate((e: HTMLElement) => [e.offsetLeft, e.offsetTop, e.offsetWidth]);
  expect(ty).toBe(local[1]);
  expect(Math.abs(tx - (local[0] + local[2] / 2))).toBeLessThanOrEqual(1);
  // kept per run
  const saved = await page.evaluate((id) => localStorage.getItem(`omher.plans.pos.${id}`), FAN);
  expect(JSON.parse(saved!)).toHaveProperty("t3-doctor");
  await page.keyboard.press("Escape");
  await page.getByTestId("graph-expand").click();
  await page.waitForTimeout(300);
  expect(await full(page).locator('[data-testid="run-node"][data-node="t3-doctor"]').evaluate((e: HTMLElement) => e.offsetLeft)).toBe(local[0]);
  // Reset puts it back where the layout put it
  await full(page).getByTestId("run-reset").click();
  await expect.poll(() => page.evaluate((id) => localStorage.getItem(`omher.plans.pos.${id}`), FAN)).toBeNull();
  expect(await full(page).locator('[data-testid="run-node"][data-node="t3-doctor"]').evaluate((e: HTMLElement) => e.offsetLeft)).toBe(home);
  await expect(full(page).getByTestId("run-reset")).toBeDisabled();
  // a plain click (no drag) opens the node's detail in a drawer on the right
  await full(page).locator('[data-testid="run-node"][data-node="t1-discovery"]').click();
  await expect(full(page).getByTestId("run-drawer")).toContainText("Codex skill discovery reads .agents/skills");
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("full view: zoom keys, Fit and the wheel; empty space pans", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  await page.getByTestId("graph-expand").click();
  const g = full(page).getByTestId("run-graph");
  const vw = page.viewportSize()!.width;
  await expect.poll(async () => Math.round(await full(page).evaluate((e) => e.getBoundingClientRect().right))).toBe(vw);
  await page.waitForTimeout(150); // the refit after the panel stepped aside
  // it opens with the first frontier at the top, the run going on under the fold. Its widest frontier (nine) is a
  // little too long for the window, so the drawing is shown a little smaller than the text's own size: never
  // under four fifths of it for that
  const open = Number(await g.getAttribute("data-zoom"));
  expect(open).toBeGreaterThanOrEqual(0.8);
  expect(open).toBeLessThanOrEqual(1);
  const m = await mod(page);
  await page.keyboard.press(`${m}+Equal`);
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeGreaterThan(open);
  // Fit brings the whole run into view
  await full(page).getByTestId("run-fit").click();
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeLessThan(open);
  const inView = await g.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return [...el.querySelectorAll("[data-testid=run-node]")].every((e) => {
      const r = e.getBoundingClientRect();
      return r.top >= b.top - 1 && r.bottom <= b.bottom + 1 && r.left >= b.left - 1 && r.right <= b.right + 1;
    });
  });
  expect(inView).toBe(true);
  // ⌘0 is Fit too
  await page.keyboard.press(`${m}+Minus`);
  const small = Number(await g.getAttribute("data-zoom"));
  await page.keyboard.press(`${m}+Digit0`);
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeGreaterThan(small);
  // dragging empty space pans
  const b = await g.boundingBox();
  const card = full(page).getByTestId("run-node").first();
  const c0 = await card.boundingBox();
  await page.mouse.move(b!.x + 6, b!.y + 6);
  await page.mouse.down();
  await page.mouse.move(b!.x + 66, b!.y + 46, { steps: 5 });
  await page.mouse.up();
  const c1 = await card.boundingBox();
  expect(Math.round(c1!.x - c0!.x)).toBe(60);
  expect(Math.round(c1!.y - c0!.y)).toBe(40);
});

// ---- motion ----

test("motion: the boxes appear one by one in frontier order, then nothing moves but the dash into a running node", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await expect(f.getByTestId("run-node")).toHaveCount(6);
  const first = await f.getByTestId("run-node").evaluateAll((els) =>
    els.map((e) => ({ frontier: Number(e.getAttribute("data-frontier")), appear: Number(e.getAttribute("data-appear")), delay: parseFloat(getComputedStyle(e).animationDelay), anim: getComputedStyle(e).animationName })),
  );
  // in frontier order, each later than the one before it, all inside a second
  const order = [...first].sort((a, b) => a.appear - b.appear);
  expect(order.map((n) => n.frontier)).toEqual([...order.map((n) => n.frontier)].sort((a, b) => a - b));
  for (let i = 1; i < order.length; i++) expect(order[i].delay).toBeGreaterThan(order[i - 1].delay);
  expect(Math.max(...order.map((n) => n.delay))).toBeLessThan(1);
  expect(new Set(first.map((n) => n.anim))).toEqual(new Set(["bv-in"]));
  await settled(page);
  const moving = await f.locator(".bv *").evaluateAll((els) => els.filter((e) => getComputedStyle(e).animationName !== "none").map((e) => [e.getAttribute("class"), getComputedStyle(e).animationName]));
  expect(moving.length).toBeGreaterThan(0);
  for (const [cls, name] of moving) {
    expect(cls).toMatch(/\bflow\b/);
    expect(name).toBe("bv-flow");
  }
  // a box only answers the pointer (its outline, shadow and lift ease in 120ms): nothing shimmers, pulses or glows
  expect(
    await f.getByTestId("run-node").evaluateAll(
      (els) => els.filter((e) => getComputedStyle(e).transitionProperty !== "border-color, box-shadow, transform" || getComputedStyle(e).transitionDuration !== "0.12s, 0.12s, 0.12s" || getComputedStyle(e, "::before").animationName !== "none").length,
    ),
  ).toBe(0);
});

test("reduced motion: no entrance and no dash", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(6);
  expect(await full(page).locator(".bv *").evaluateAll((els) => els.filter((e) => getComputedStyle(e).animationName !== "none").length)).toBe(0);
  // and a box does not ease either
  expect(await full(page).getByTestId("run-node").evaluateAll((els) => els.filter((e) => !/^0s(, 0s)*$/.test(getComputedStyle(e).transitionDuration)).length)).toBe(0);
  await ctx.close();
});

// ---- other kinds of run ----

test("a delegate fan-out without a dag is its own run of one frontier", async ({ page }) => {
  await openRuns(page, "default");
  await showList(page);
  const row = page.locator('[data-testid="run-row"][data-kind="delegate"]').first();
  await row.click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", /^delegate:deleg_/);
  await expect(box.getByTestId("run-plan-counts")).toHaveText(/ · \d of \d done/);
  await expect(box.getByTestId("run-plan-where")).toContainText(" · main");
  await expect(box.getByTestId("run-plan")).not.toContainText("Hermes / helpers");
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-frontiers", "1");
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
  await expect(box.getByTestId("run-deps")).toHaveCount(0);
});

test("a delegate_task in chat: one plain sentence per dag part, a read-only status, and the run opens", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "d1", name: "delegate_task", detail: "Doctor check (+1 more)", dag: [{ run: "codex-coexist-live", node: "t3-doctor" }, { run: "codex-coexist-live", node: "t5-verify" }] },
    ],
  });
  const act = page.getByTestId("activity").last();
  await act.getByTestId("activity-toggle").click();
  const rows = act.getByTestId("activity-dag");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Assigned t3-doctor to a helper");
  await expect(rows.nth(0).getByTestId("activity-dag-status")).toHaveText("working");
  expect(await act.getByRole("button", { name: /reassign/i }).count()).toBe(0);
  await rows.nth(0).getByTestId("activity-dag-open").click();
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(panel(page)).toHaveAttribute("data-run", LIVE);
});

test("CLI runs: listed under the bot's own runs with the agent's mark and name; each opens as boxes", async ({ page }) => {
  await openRuns(page);
  await showList(page);
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  const rows = page.getByTestId("cli-run-row");
  await expect(rows).toHaveCount(3);
  await expect(page.getByTestId("panel-runs")).toContainText("CLI agents");
  expect(await rows.evaluateAll((els) => els.map((e) => [e.getAttribute("data-agent"), e.getAttribute("data-state")]))).toEqual([
    ["claude", "running"],
    ["claude", "failed"],
    ["codex", "done"],
  ]);
  await expect(rows.nth(0).getByTestId("run-agent")).toHaveText("Claude");
  await expect(rows.nth(0).locator("[data-mark]")).toHaveAttribute("data-mark", "claude");
  await expect(rows.nth(2).getByTestId("run-agent")).toHaveText("Codex");
  await expect(rows.nth(2).locator("[data-mark]")).toHaveAttribute("data-mark", "openai");
  await expect(rows.nth(0).locator(".rn-live")).toHaveCount(1);
  await expect(rows.nth(2).locator(".rn-n")).toHaveText(/^2\/2 · /);
  const titleX = await rows.evaluateAll((els) => els.map((e) => Math.round(e.querySelector(".rn-title")!.getBoundingClientRect().x)));
  expect(new Set(titleX).size).toBe(1);

  // Claude: one frontier, the subagent's own model on every node, a failed call with its reason
  await rows.nth(1).click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CLI_CLAUDE);
  await expect(box.getByTestId("run-plan-counts")).toHaveText(/ of 3 done/);
  await expect(box.getByTestId("run-plan-where")).toHaveText("Claude · web-app"); // the CLI, and the folder the session ran in
  await expect(box.getByTestId("run-node")).toHaveCount(3);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-frontiers", "1");
  // the mark of the model each subagent ran on (Opus 5.5: Anthropic's), one a node
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")}:${e.getAttribute("data-mark")}`))).toEqual(["model:claude", "model:claude", "model:claude"]);
  await expect(box.getByTestId("node-facts").first()).toHaveText(/^Opus 5\.5/);
  await expect(box.locator('[data-testid="run-node"][data-state="done"]').first().getByTestId("node-status")).toHaveText(/^Done /);
  const bad = box.locator('[data-testid="run-node"][data-state="failed"]');
  await expect(bad).toHaveCount(1);
  await expect(bad.getByTestId("node-status")).toHaveText(/^Failed/);
  await expect(bad.getByTestId("node-status").locator("svg")).toHaveAttribute("data-icon", "x");
  await bad.click();
  const drawer = page.getByTestId("run-drawer");
  await expect(drawer).toContainText("Agent type not available in this folder.");
  await expect(drawer).toContainText("Opus 5.5");
  // a CLI session is not the bot's: no "Ask in chat" retry
  await expect(drawer.getByTestId("run-ask")).toHaveCount(0);
  await drawer.getByRole("button", { name: "Close node" }).click();
  await box.locator('[data-testid="run-node"][data-state="done"]').first().click();
  await expect(page.getByTestId("run-summary")).toContainText("The Windows build compiles");

  // Codex: the child's own model by its name, with that model's maker's mark (GPT-6 Astra: OpenAI's)
  await showList(page);
  await rows.nth(2).click();
  await expect(box).toHaveAttribute("data-run", CLI_CODEX);
  await expect(box.getByTestId("run-node")).toHaveCount(2);
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")}:${e.getAttribute("data-mark")}`))).toEqual(["model:openai", "model:openai"]);
  // the session is Codex's own: its sub-runs say no "via Codex"
  await expect(box.getByTestId("node-via")).toHaveCount(0);
  await expect(box.getByTestId("node-facts").first()).toHaveText("GPT-6 Astra · low");
  await box.getByTestId("run-node").first().click();
  await expect(page.getByTestId("run-drawer")).toContainText("GPT-6 Astra · low");
  await expect(page.getByTestId("run-summary")).toContainText("API review done");

  // a live session: its running subagent is a card under Node details
  await showList(page);
  await rows.nth(0).click();
  await expect(box).toHaveAttribute("data-run", CLI_LIVE);
  await expect(box.getByTestId("run-state")).toHaveText("Running");
  await expect(box.getByTestId("run-detail")).toHaveCount(1);

  // read-only: only reads went to the bridge
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls).toContain("runs.cli");
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("runs.cli: filters by agent, cwd and since; bad params are refused", async () => {
  expect((await mock("runs.cli", { agent: "codex" })).runs.map((r: any) => r.id)).toEqual([CLI_CODEX]);
  expect((await mock("runs.cli", { cwd: "/w/web-app" })).runs.map((r: any) => r.agent)).toEqual(["claude", "claude"]);
  expect((await mock("runs.cli", { since: Date.now() / 1000 - 3600 })).runs.map((r: any) => r.id)).toEqual([CLI_LIVE]);
  expect((await mock("runs.cli", { agent: "grok" })).runs).toEqual([]);
  for (const bad of [{ agent: "cursor" }, { cwd: "" }, { since: "yesterday" }]) expect(await mockError("runs.cli", bad)).toBe("bad_request");
});
