// Plans tab (runs in the code): the bot's plans as a list of plain text rows, and the selected one as the OMH
// TUI's box view: a plain three-line header,
// frontiers of outlined boxes of four text lines, connected 1px lines, in the side panel and at full size over the
// chat column (⌘⇧G). Real (redacted) dag runs, real delegation logs for the models and routes, and a synthetic
// 40-node run for the layout.
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
/** The entrance (boxes one by one, then the lines) is over. */
const settled = (page: Page) => page.waitForTimeout(1500);

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

test("Plans is the sixth tab; the header still holds one control; the panel is 460px", async ({ page }) => {
  await openRuns(page);
  const tabs = page.getByRole("tablist", { name: "Panel" }).getByRole("tab");
  expect(await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("title")))).toEqual(["Details", "Terminal", "Schedule", "Worktrees", "Diff", "Plans"]);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBe(460);
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
  expect(first.y).toBeLessThanOrEqual(220);
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

test("the run's header is three plain lines of text and its goal: no card, badge, bar, chips or icon", async ({ page }) => {
  await openRuns(page);
  const head = panel(page).getByTestId("run-plan");
  await expect(head.getByTestId("run-plan-source")).toHaveText("OMH / DAG · 6 tasks");
  await expect(head.getByTestId("run-plan-title")).toHaveText("Codex coexistence (live)");
  await expect(head).toContainText("· main ");
  await expect(head.getByTestId("run-plan-counts")).toHaveText(/^Running · Done 3\/6 · 1 repaired · 1 waiting · \d+(s|m)$/);
  await expect(head.getByTestId("run-plan-goal")).toContainText("OMH suggests its own skills to Codex fanouts");
  // lines of 18px monospace text, nothing drawn around or behind them
  const look = await head.evaluate((e) => {
    const s = getComputedStyle(e);
    const lines = [...e.querySelectorAll(".ph-l")].map((l) => Math.round(l.getBoundingClientRect().height));
    const boxed = [e, ...e.querySelectorAll("*")].filter((x) => {
      const c = getComputedStyle(x);
      return c.backgroundImage !== "none" || c.boxShadow !== "none" || parseFloat(c.borderTopWidth) > 0 || !/rgba\(0, 0, 0, 0\)|transparent/.test(c.backgroundColor);
    }).length;
    return { font: s.fontFamily, size: s.fontSize, lines, boxed, svgs: e.querySelectorAll("svg").length };
  });
  expect(look.font).toMatch(/monospace/);
  expect(look.size).toBe("12px");
  expect(look.lines).toEqual([18, 18, 18, 18]);
  expect(look.boxed).toBe(0);
  expect(look.svgs).toBe(0);
  // what the card held is gone
  for (const gone of [".rn-badge", ".rn-bar", ".rn-head", ".rp", ".rp-chip", "[data-testid=run-plan-layer]", "[data-testid=run-legend]", "[data-testid=run-zoom]"])
    await expect(page.locator(gone)).toHaveCount(0);
  // the full view opens from a line of text, not an icon
  await expect(head.getByTestId("graph-expand")).toHaveText(/^Full view (⌘⇧G|Ctrl\+Shift\+G)$/);
});

test("a run that has not started: 'Starts in 0:..' with Start now / Edit as text, which only prefill the composer", async ({ page }) => {
  await openRuns(page, "default");
  await pickRow(page, "Codex coexistence (next)");
  const plan = panel(page).getByTestId("run-plan");
  await expect(plan.getByTestId("run-state")).toHaveText(/^Starts in 0:(0\d|10)$/);
  await expect(plan.getByTestId("run-plan-counts")).toContainText("Done 0/6");
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

test("a node is four lines of the TUI's wording in monospace: a 1px outline, one 2px state line, no fill", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  await settled(page);
  const nodes = box.getByTestId("run-node");
  await expect(nodes).toHaveCount(6);
  // the four lines, as the TUI words them
  const text = await nodes.evaluateAll((els) => els.map((e) => [...e.querySelectorAll(".bx-l")].map((l) => (l.textContent ?? "").trim())));
  for (const lines of text) expect(lines).toHaveLength(4);
  const by = Object.fromEntries(await nodes.evaluateAll((els) => els.map((e) => [e.getAttribute("data-node"), [...e.querySelectorAll(".bx-l")].map((l) => (l.textContent ?? "").trim())])));
  expect(by["t2-status-update"][1]).toBe("unspecified-high · codex");
  expect(by["t2-status-update"][2]).toMatch(/^✓ Accepted \d+m$/);
  expect(by["t2-status-update"][3]).toBe("Start node");
  expect(by["t1-discovery"][2]).toMatch(/^✗ Failed \d+m · repaired$/);
  expect(by["t3-doctor"][2]).toMatch(/^● Running \d+m$/);
  expect(by["t3-doctor"][3]).toMatch(/^← Honest pack status/);
  expect(by["t5-verify"][1]).toBe("review · opus-5-5:high");
  expect(by["t5-verify"][2]).toBe("○ Waits on 1 lane");
  // a node added to repair another carries ↻ before its title
  expect(by["t1-hermes"][0]).toMatch(/^↻ /);
  // every box: one width, 1px outline, the panel's own surface behind it, nothing else painted
  const surface = await page.getByTestId("details").evaluate((e) => getComputedStyle(e).backgroundColor);
  const looks = await nodes.evaluateAll((els) =>
    els.map((e) => {
      const s = getComputedStyle(e);
      const rail = getComputedStyle(e, "::before");
      return {
        tone: e.getAttribute("data-tone"),
        w: Math.round(e.getBoundingClientRect().width),
        h: Math.round(e.getBoundingClientRect().height),
        bg: s.backgroundColor,
        image: s.backgroundImage,
        shadow: s.boxShadow,
        filter: s.filter,
        border: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth].join(" "),
        style: s.borderTopStyle,
        radius: s.borderTopLeftRadius,
        anim: s.animationName,
        after: getComputedStyle(e, "::after").content,
        rail: [rail.width, rail.backgroundImage, rail.backgroundColor, rail.animationName],
        font: s.fontFamily,
        size: s.fontSize,
      };
    }),
  );
  expect(new Set(looks.map((l) => l.w)).size).toBe(1);
  expect(new Set(looks.map((l) => l.h))).toEqual(new Set([84]));
  for (const l of looks) {
    expect(l.bg, "a box has no colour of its own").toBe(surface);
    expect(l.image).toBe("none");
    expect(l.shadow).toBe("none");
    expect(l.filter).toBe("none");
    expect(l.border).toBe("1px 1px 1px 1px");
    expect(l.radius).toBe("4px");
    expect(l.anim).toBe("none");
    expect(l.after).toBe("none");
    expect(l.rail[0]).toBe("2px");
    expect(l.rail[1]).toBe("none");
    expect(l.rail[3]).toBe("none");
    expect(l.font).toMatch(/monospace/);
    expect(l.size).toBe("12px");
  }
  // the state is the 2px line: a colour per state, none on a node not handed out (its outline is dashed)
  const rail = (tone: string) => looks.find((l) => l.tone === tone)!.rail[2];
  expect(new Set([rail("done"), rail("running"), rail("repaired")]).size).toBe(3);
  expect(rail("waiting")).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  expect(looks.find((l) => l.tone === "waiting")!.style).toBe("dashed");
  expect(looks.find((l) => l.tone === "done")!.style).toBe("solid");
  // a 12px mark on every node, and none says "model not logged"
  const marks = await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => [e.getAttribute("data-mark"), Math.round(e.querySelector("svg")!.getBoundingClientRect().width)]));
  expect(marks).toHaveLength(6);
  for (const [mark, size] of marks) {
    expect(mark).not.toBe("none");
    expect(size).toBe(12);
  }
  await expect(box).not.toContainText("model not logged");
});

test("the panel wraps a frontier of three, two boxes to a row, and joins it with the centred connector", async ({ page }) => {
  await openRuns(page);
  const graph = panel(page).getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-frontiers", "3");
  await expect(graph).toHaveAttribute("data-per-row", "2");
  // the frontier of three wraps, so neither gap beside it has a single row to draw to: ╎ over ▽, never a line
  await expect(graph).toHaveAttribute("data-undrawn", "2");
  await expect(panel(page).getByTestId("run-undrawn")).toHaveCount(2);
  await expect(panel(page).getByTestId("run-edge")).toHaveCount(0);
  // "· Same frontier" under each frontier of several boxes: dim text, not a chip or a band
  const labels = panel(page).getByTestId("run-frontier");
  await expect(labels).toHaveText(["· Same frontier", "· Same frontier"]);
  const label = await labels.first().evaluate((e) => {
    const s = getComputedStyle(e);
    return [s.borderTopWidth, s.backgroundImage, s.color, getComputedStyle(e.closest(".bv")!).color];
  });
  expect(label[0]).toBe("0px");
  expect(label[1]).toBe("none");
  expect(label[2]).not.toBe(label[3]);
  // no box is narrower than the TUI's narrowest (26 cells), and the drawing stays inside the panel
  const geo = await graph.evaluate((g) => {
    const cw = parseFloat(getComputedStyle(g).getPropertyValue("--bv-cw"));
    const rs = [...g.querySelectorAll("[data-testid=run-node]")].map((e) => e.getBoundingClientRect());
    const b = g.getBoundingClientRect();
    return { cw, minW: Math.min(...rs.map((r) => r.width)), left: Math.min(...rs.map((r) => r.left)) - b.left, right: b.right - Math.max(...rs.map((r) => r.right)), scroll: g.scrollWidth - g.clientWidth };
  });
  expect(geo.minW).toBeGreaterThanOrEqual(26 * geo.cw - 0.5);
  expect(geo.left).toBeGreaterThanOrEqual(-0.5);
  expect(geo.right).toBeGreaterThanOrEqual(-0.5);
  expect(geo.scroll).toBeLessThanOrEqual(0);
});

test("full view: every line leaves a parent's bottom and ends with a ▼ on a child's top, in the parent's colour", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  const graph = f.getByTestId("run-graph");
  // three boxes fit a row here, so both gaps are drawn
  await expect(graph).toHaveAttribute("data-per-row", "3");
  await expect(graph).toHaveAttribute("data-undrawn", "0");
  await expect(f.getByTestId("run-undrawn")).toHaveCount(0);
  await settled(page);
  const geo = await graph.evaluate((g) => {
    const box = (id: string) => {
      const e = g.querySelector(`[data-node="${id}"]`) as HTMLElement;
      return { x: e.offsetLeft, y: e.offsetTop, w: e.offsetWidth, h: e.offsetHeight, rail: getComputedStyle(e, "::before").backgroundColor };
    };
    const lines = [...g.querySelectorAll<SVGPathElement>("[data-testid=run-edge]")].map((p) => {
      const a = p.getPointAtLength(0);
      const b = p.getPointAtLength(p.getTotalLength());
      const s = getComputedStyle(p);
      return { from: p.getAttribute("data-from")!.split(" "), to: p.getAttribute("data-to")!.split(" "), a: [a.x, a.y], b: [b.x, b.y], stroke: s.stroke, width: s.strokeWidth, anim: s.animationName, cls: p.getAttribute("class")! };
    });
    const heads = [...g.querySelectorAll("[data-testid=run-arrow]")].map((p) => ({ to: p.getAttribute("data-to")!, tip: p.getAttribute("data-tip")!.split(",").map(Number) }));
    const ids = [...g.querySelectorAll("[data-testid=run-node]")].map((e) => e.getAttribute("data-node")!);
    return { boxes: Object.fromEntries(ids.map((id) => [id, box(id)])), lines, heads };
  });
  expect(geo.lines.length).toBeGreaterThan(0);
  for (const l of geo.lines) expect(l.width).toBe("1px");
  // a line out of one parent starts on that parent's bottom edge, at its middle, in its state colour
  const stubs = geo.lines.filter((l) => l.from.length === 1);
  expect(stubs.length).toBeGreaterThanOrEqual(3);
  for (const l of stubs.filter((s) => Math.abs(s.a[1] - (geo.boxes[s.from[0]].y + geo.boxes[s.from[0]].h)) < 1)) {
    const p = geo.boxes[l.from[0]];
    expect(Math.abs(l.a[0] - (p.x + p.w / 2))).toBeLessThanOrEqual(1);
    expect(l.stroke.replace(/[^\d,]/g, "").split(",").slice(0, 3)).toEqual(p.rail.replace(/[^\d,]/g, "").split(",").slice(0, 3));
  }
  const starts = new Set(stubs.map((l) => l.from[0]).filter((id) => stubs.some((s) => s.from[0] === id && Math.abs(s.a[1] - (geo.boxes[id].y + geo.boxes[id].h)) < 1)));
  expect([...starts].sort()).toEqual(["t1-discovery", "t1-hermes", "t2-status-update", "t3-doctor", "t4-fence"]);
  // every ▼ touches the top edge of the box it points into, inside its width
  expect(geo.heads.map((h) => h.to).sort()).toEqual(["t1-hermes", "t3-doctor", "t4-fence", "t5-verify"]);
  for (const h of geo.heads) {
    const c = geo.boxes[h.to];
    expect(h.tip[1]).toBe(c.y);
    expect(h.tip[0]).toBeGreaterThan(c.x);
    expect(h.tip[0]).toBeLessThan(c.x + c.w);
  }
  // "· Same frontier" stands right of the first box's middle: the line that leaves that box is not drawn over
  const label = await f.getByTestId("run-frontier").last().evaluate((e: HTMLElement) => e.offsetLeft);
  const firstOfRow = Object.values(geo.boxes).filter((b) => b.y === geo.boxes["t3-doctor"].y).sort((a, b) => a.x - b.x)[0];
  expect(label).toBeGreaterThan(firstOfRow.x + firstOfRow.w / 2 + 4);
  // motion: only the lines into the running node carry the slow dash
  const flowing = geo.lines.filter((l) => l.anim.includes("bv-flow"));
  expect(flowing.length).toBeGreaterThan(0);
  for (const l of flowing) expect(l.to).toEqual(["t3-doctor"]);
  for (const l of geo.lines.filter((x) => !x.anim.includes("bv-flow"))) expect(l.anim).toBe("none");
});

test("hovering a box lights its own lines and steps the rest back", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await settled(page);
  await f.locator('[data-testid="run-node"][data-node="t2-status-update"]').hover();
  const lit = await f.getByTestId("run-edge").evaluateAll((els) => els.map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), e.classList.contains("lit"), getComputedStyle(e).opacity]));
  const own = lit.filter(([from, to]) => `${from} ${to}`.split(" ").includes("t2-status-update"));
  expect(own.length).toBeGreaterThan(0);
  for (const [, , on, opacity] of own) expect([on, opacity]).toEqual([true, "1"]);
  const rest = lit.filter(([from, to]) => !`${from} ${to}`.split(" ").includes("t2-status-update"));
  expect(rest.length).toBeGreaterThan(0);
  for (const [, , on, opacity] of rest) expect([on, Number(opacity) < 1]).toEqual([false, true]);
  // the boxes it has no edge with step back too
  await expect(f.locator('[data-testid="run-node"][data-node="t3-doctor"]')).not.toHaveClass(/\bdim\b/);
  await expect(f.locator('[data-testid="run-node"][data-node="t1-discovery"]')).toHaveClass(/\bdim\b/);
  await page.mouse.move(5, 5);
  await expect(f.locator(".bx.dim")).toHaveCount(0);
});

test("Dependencies and Node details are plain text under the boxes", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  const deps = box.getByTestId("run-deps");
  await expect(deps.locator("h4")).toHaveText("Dependencies");
  await expect(deps.getByTestId("run-dep")).toHaveCount(7);
  await expect(deps.getByTestId("run-dep").nth(2)).toHaveText("Honest pack status + omh update refresh → Doctor check for the Codex pack");
  await expect(deps.getByTestId("run-dep").filter({ hasText: "(repair)" })).toHaveCount(2);
  // a card of text for the running node: its whole title, category and model, status, layer
  const details = box.getByTestId("run-details");
  await expect(details.locator("h4")).toHaveText("Node details");
  const card = details.getByTestId("run-detail");
  await expect(card).toHaveCount(1);
  await expect(card).toHaveAttribute("data-node", "t3-doctor");
  expect((await card.innerText()).split("\n").map((s) => s.trim())).toEqual(["● Doctor check for the Codex pack", "unspecified-low · codex", expect.stringMatching(/^Running \d+m · layer 2 · /)]);
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
  await expect(drawer.getByTestId("run-reason")).toContainText("2nd verifier HOLD");
  await expect(drawer.getByTestId("run-handoff")).toBeVisible();
  const before = (await drawer.getByTestId("run-handoff").innerText()).length;
  await drawer.getByTestId("run-handoff-more").click();
  await expect.poll(async () => (await drawer.getByTestId("run-handoff").innerText()).length).toBeGreaterThan(before);
  // selection is gray, on top of any state
  const ring = await box.locator('[data-testid="run-node"][data-node="t5-verify"]').evaluate((e) => [getComputedStyle(e).borderTopColor, getComputedStyle(e).backgroundImage]);
  const [r, g, b] = ring[0].match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThanOrEqual(24);
  expect(ring[1]).toBe("none");
  // the failed node: a red "failed", the reason, a quiet prefill button
  await box.locator('[data-testid="run-node"][data-node="t1-discovery"]').click();
  await expect(drawer).toHaveClass(/\bbad\b/);
  const word = drawer.getByTestId("run-state-word");
  await expect(word).toHaveText("failed");
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
  await expect(off.first().getByTestId("node-status")).toHaveText("▪ Cancelled");
  expect(await off.first().evaluate((e) => getComputedStyle(e).borderTopStyle)).toBe("dashed");
});

// ---- big runs ----

test("88 sub-runs: the first 8 rows, running then failed first; 'Show all 88' opens the rest", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await grow88(page);
  await openRuns(page);
  await pickRow(page, /\/88 · /, "cli-run-row");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CLI_CODEX);
  await expect(box.getByTestId("run-plan-source")).toHaveText("Codex / subagents · 88 tasks");
  const graph = box.getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-frontiers", "1");
  const cards = box.getByTestId("run-node");
  await expect(cards).toHaveCount(16);
  expect((await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).slice(0, 5)).toEqual(["running", "running", "running", "failed", "done"]);
  // one frontier: no line, no connector, and every box says "Start node"
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
  await expect(box.getByTestId("run-undrawn")).toHaveCount(0);
  await expect(box.getByTestId("run-frontier")).toHaveText(["· Same frontier"]);
  expect(new Set(await box.getByTestId("node-parents").allInnerTexts())).toEqual(new Set(["Start node"]));
  await expect(cards.nth(4).getByTestId("node-status")).toHaveText(/^✓ Done \d+s$/);
  // two to a row, one width, inside the panel
  const geo = await graph.evaluate((g) => {
    const b = g.getBoundingClientRect();
    const rs = [...g.querySelectorAll("[data-testid=run-node]")].map((c) => c.getBoundingClientRect());
    return { cols: new Set(rs.map((r) => Math.round(r.left))).size, widths: new Set(rs.map((r) => Math.round(r.width))).size, inside: rs.every((r) => r.left >= b.left - 0.5 && r.right <= b.right + 0.5) };
  });
  expect(geo).toEqual({ cols: 2, widths: 1, inside: true });
  // a long title is cut in the middle with "…", never wrapped
  await expect(box.locator('[data-testid="run-node"][data-node="sub-0"]').getByTestId("node-title")).toHaveText(/^Sub-run 0.* … .*$/);
  // "Show all 88" is a line of text under the rows; it shows them all, and back
  const more = box.getByTestId("run-more");
  await expect(more).toHaveText("+72 more · Show all 88");
  await more.click();
  await expect(cards).toHaveCount(88);
  await expect(more).toHaveText("Show fewer");
  await more.click();
  await expect(cards).toHaveCount(16);
  // the full view shows every sub-run
  await box.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(88);
  await expect(full(page).getByTestId("run-more")).toHaveCount(0);
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("40 nodes: no two boxes overlap, in the panel or the full view, and the panel never scrolls sideways", async ({ page }) => {
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
  expect(await overlaps(panel(page))).toEqual([40, 0]);
  expect(await page.locator(".details .pn-scroll").evaluate((e) => e.scrollWidth - e.clientWidth)).toBeLessThanOrEqual(0);
  // its many edges are a capped list of text
  await expect(panel(page).getByTestId("run-dep")).toHaveCount(12);
  await expect(panel(page).getByTestId("run-deps-more")).toHaveText(/^\+\d+ more · Show all \d+$/);
  await panel(page).getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(40);
  expect(await overlaps(full(page))).toEqual([40, 0]);
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
  await expect(full(page).getByTestId("run-plan-source")).toHaveText("OMH / DAG · 6 tasks");
  await expect(full(page).getByTestId("run-plan-counts")).toHaveText(/^Running · Done 3\/6 · /);
  await expect(full(page).getByTestId("run-graph")).toHaveAttribute("data-zoom", "1.00");
  expect(await full(page).getByTestId("run-node").first().evaluate((e) => getComputedStyle(e).fontSize)).toBe("12.5px");
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
  await page.mouse.move(before!.x + 30, before!.y + 20);
  await page.mouse.down();
  await page.mouse.move(before!.x + 90, before!.y + 60, { steps: 6 });
  await page.mouse.up();
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
  // it opens at the text's own size, the first frontier at the top; the run goes on under the fold
  await expect(g).toHaveAttribute("data-zoom", "1.00");
  const m = await mod(page);
  await page.keyboard.press(`${m}+Equal`);
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeGreaterThan(1);
  // Fit brings the whole run into view
  await full(page).getByTestId("run-fit").click();
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeLessThan(1);
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
  // and no transition anywhere on a box: nothing shimmers, pulses or glows
  expect(await f.getByTestId("run-node").evaluateAll((els) => els.filter((e) => getComputedStyle(e).transitionDuration !== "0s" || getComputedStyle(e, "::before").animationName !== "none").length)).toBe(0);
});

test("reduced motion: no entrance and no dash", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(6);
  expect(await full(page).locator(".bv *").evaluateAll((els) => els.filter((e) => getComputedStyle(e).animationName !== "none").length)).toBe(0);
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
  await expect(box.getByTestId("run-plan-source")).toHaveText(/^Hermes \/ helpers · \d tasks$/);
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
  await expect(box.getByTestId("run-plan-source")).toHaveText("Claude / subagents · 3 tasks");
  await expect(box.getByTestId("run-plan")).toContainText("· web-app"); // the folder the session ran in
  await expect(box.getByTestId("run-node")).toHaveCount(3);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-frontiers", "1");
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => [e.getAttribute("data-mark"), e.getAttribute("data-source")]))).toEqual([
    ["claude", "ran"],
    ["claude", "ran"],
    ["claude", "ran"],
  ]);
  // a CLI's sub-run is "Done", never "Accepted" (that is a dag's word)
  await expect(box.locator('[data-testid="run-node"][data-state="done"]').first().getByTestId("node-status")).toHaveText(/^✓ Done /);
  const bad = box.locator('[data-testid="run-node"][data-state="failed"]');
  await expect(bad).toHaveCount(1);
  await expect(bad.getByTestId("node-status")).toHaveText(/^✗ Failed/);
  await bad.click();
  const drawer = page.getByTestId("run-drawer");
  await expect(drawer).toContainText("Agent type not available in this folder.");
  await expect(drawer).toContainText("Opus 5.5");
  // a CLI session is not the bot's: no "Ask in chat" retry
  await expect(drawer.getByTestId("run-ask")).toHaveCount(0);
  await drawer.getByRole("button", { name: "Close node" }).click();
  await box.locator('[data-testid="run-node"][data-state="done"]').first().click();
  await expect(page.getByTestId("run-summary")).toContainText("The Windows build compiles");

  // Codex: OpenAI marks with the child's own model
  await showList(page);
  await rows.nth(2).click();
  await expect(box).toHaveAttribute("data-run", CLI_CODEX);
  await expect(box.getByTestId("run-node")).toHaveCount(2);
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(["openai", "openai"]);
  await expect(box.getByTestId("node-facts").first()).toHaveText("gpt-6-astra:low");
  await box.getByTestId("run-node").first().click();
  await expect(page.getByTestId("run-drawer")).toContainText("gpt-6-astra · low");
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
