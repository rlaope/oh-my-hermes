// Runs tab: the bot's runs as a list, a compact read-only graph in the panel and a large one over the chat
// column (⌘⇧G / Expand). Real (redacted) dag runs, real delegation logs for the models and routes, and a
// synthetic 40-node run for the layout.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-v02");
const FAN = "dag:20261102_235818_fcfb1bdd/codex-coexist";
const LIVE = "dag:20261102_235818_fcfb1bdd/codex-coexist-live";
const CANCELLED = "dag:20261026_134438_3ae70257/omh-dap";
const BIG = "dag:synthetic/big-run";
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
/** Unfolds the run list when it sits folded into the selected run's header ("All runs ▾"). */
async function showList(page: Page) {
  const t = page.getByTestId("run-list-toggle");
  await expect(t).toBeVisible();
  if ((await t.getAttribute("aria-expanded")) === "false") await t.click();
  await expect(page.getByTestId("run-list")).toBeVisible();
}
/** Opens a run from the list (which then folds away again). */
async function pickRow(page: Page, text: string | RegExp, testId = "run-row") {
  await showList(page);
  await page.getByTestId(testId).filter({ hasText: text }).click();
}
const panel = (page: Page) => page.getByTestId("run-graph-box");
const full = (page: Page) => page.getByTestId("runs-full");
type Box = { x: number; y: number; width: number; height: number };
const meets = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Runs is the sixth tab; the header still holds one control; the panel is 460px", async ({ page }) => {
  await openRuns(page);
  const tabs = page.getByRole("tablist", { name: "Panel" }).getByRole("tab");
  expect(await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("title")))).toEqual([
    "Details",
    "Terminal",
    "Schedule",
    "Worktrees",
    "Diff",
    "Runs",
  ]);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBe(460);
  // the selected tab and the selected run are gray, never the brand gradient
  expect(await page.getByTestId("panel-tab-runs").evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
  await showList(page);
  const sel = page.locator('[data-testid="run-row"][aria-current="true"]');
  expect(await sel.evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
});

test("the list: running first with a live dot, then newest; dots differ by state; the header badge shows progress", async ({ page }) => {
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
  // done = green-gray, cancelled = gray + the word, all different colours
  const dot = (i: number) => rows.nth(i).locator("i").first().evaluate((e) => getComputedStyle(e).backgroundColor);
  const [done, cancelled] = [await dot(1), await dot(2)];
  expect(done).not.toBe(cancelled);
  await expect(rows.nth(2)).toContainText("Cancelled");
  // the header: a status badge with the live dot, a slim bar and 3/6
  const badge = panel(page).getByTestId("run-state");
  await expect(badge).toContainText("Running");
  await expect(badge.locator(".rn-live")).toHaveCount(1);
  await expect(badge.getByTestId("run-progress")).toHaveText("3/6");
  const bar = await badge.locator(".rn-bar i").first().evaluate((e) => [e.getBoundingClientRect().width, e.parentElement!.getBoundingClientRect().width]);
  expect(bar[0] / bar[1]).toBeCloseTo(0.5, 1);
  // the running node: a live dot, a tinted card, never a gradient fill on the card itself
  const doing = panel(page).locator('[data-testid="run-node"][data-state="running"]');
  await expect(doing).toHaveCount(1);
  await expect(doing.locator(".rg-live")).toHaveCount(1);
  expect(await doing.evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
});

test("the fan-out: 6 cards in 3 layers, every link drawn right-middle to left-middle, the failed node marked", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", FAN);
  const detail = await mock("runs.get", { bot: "kami", run: FAN });
  // links as OMH counts them: deps and repair links; verify's dependency on the failed node is drawn from that
  // node's two repairs instead (a failed node whose repairs are done counts as satisfied)
  const links = detail.run.nodes.reduce((a: number, n: any) => a + n.deps.length + (n.repairOf ? 1 : 0), 0) + 1;
  // three layers do not fit side by side at the panel's 132px floor: the panel stacks them, top to bottom in layer
  // order, and draws no links (the full view does)
  const cards = box.getByTestId("run-node");
  await expect(cards).toHaveCount(6);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-mode", "stack");
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
  const bands = await box.getByTestId("run-col").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().y)));
  expect(bands).toHaveLength(3);
  const ys = await cards.evaluateAll((els) => els.map((e) => [Number(e.getAttribute("data-layer")), Math.round(e.getBoundingClientRect().y)] as const));
  for (const [l, y] of ys) {
    expect(y).toBeGreaterThan(bands[l]);
    if (l + 1 < bands.length) expect(y).toBeLessThan(bands[l + 1]);
  }
  // the legend names no kind of line the panel does not draw (node states stay: "repaired")
  await expect(box.getByTestId("run-legend").locator('[class^="l-"]')).toHaveCount(0);
  await expect(box.getByTestId("run-legend")).toContainText("repaired");
  // the full view draws every link: columns are real columns, every card of a layer shares one x
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  const fcards = f.getByTestId("run-node");
  await expect(fcards).toHaveCount(6);
  await expect(f.getByTestId("run-graph")).toHaveAttribute("data-cols", "3");
  const xs = await fcards.evaluateAll((els) => els.map((e) => [e.getAttribute("data-layer"), (e as HTMLElement).offsetLeft]));
  for (const l of ["0", "1", "2"]) expect(new Set(xs.filter(([k]) => k === l).map(([, x]) => x)).size).toBe(1);
  // 4 dependencies (one replaced by the two repairs) + 2 repair links: every one is drawn
  expect(links).toBe(7);
  await expect(f.getByTestId("run-edge")).toHaveCount(links);
  for (const id of ["t1-hermes", "t4-fence"]) await expect(f.locator(`[data-testid="run-edge"][data-to="${id}"]`)).toHaveCount(1);
  // each edge starts at its source's right-middle and ends at its target's left-middle
  const geo = await f.evaluate((el) => {
    const cards = Object.fromEntries(
      [...el.querySelectorAll<HTMLElement>('[data-testid="run-node"]')].map((c) => [
        c.dataset.node,
        { l: c.offsetLeft, r: c.offsetLeft + c.offsetWidth, m: c.offsetTop + c.offsetHeight / 2 },
      ]),
    );
    const edges = [...el.querySelectorAll<SVGGElement>('[data-testid="run-edge"]')].map((g) => ({
      from: g.dataset.from!,
      to: g.dataset.to!,
      end: g.dataset.end!.split(",").map(Number),
      d: g.querySelector(".rg-line")!.getAttribute("d")!,
    }));
    return { cards, edges };
  });
  for (const e of geo.edges) {
    expect(e.end).toEqual([geo.cards[e.from].r, geo.cards[e.from].m, geo.cards[e.to].l, geo.cards[e.to].m]);
    // the path itself starts and ends there, and its last segment is horizontal (never enters from below)
    const n = e.d.match(/-?\d+(\.\d+)?/g)!.map(Number);
    expect([n[0], n[1]]).toEqual([e.end[0], e.end[1]]);
    expect(n.slice(-2)).toEqual([e.end[2], e.end[3]]);
    expect(n[n.length - 3]).toBe(e.end[3]); // the point before the end is on the same y
  }
  // edges out of the failed node are dashed
  for (const g of await f.locator('[data-testid="run-edge"][data-from="t1-discovery"] .rg-line').all())
    expect(await g.evaluate((e) => getComputedStyle(e).strokeDasharray)).not.toBe("none");
  await page.keyboard.press("Escape");
  const failed = box.locator('[data-node="t1-discovery"]');
  await expect(failed).toHaveClass(/\bbad\b/);
  // its two repairs are done: still the failed node (its class, its rail), marked "repaired" with ↺, amber
  await expect(failed).toHaveClass(/\brepaired\b/);
  await expect(failed.locator(".rg-st")).toHaveText("↺");
  await expect(box.locator('[data-node="t2-status-update"] .rg-st')).toHaveText("✓");
  // hovering a card lights the parts it waits on and the parts waiting on it, and dims the rest
  await box.locator('[data-node="t3-doctor"]').hover();
  await expect(box.locator('[data-node="t2-status-update"]')).not.toHaveClass(/\bdim\b/);
  await expect(box.locator('[data-node="t5-verify"]')).not.toHaveClass(/\bdim\b/);
  await expect(box.locator('[data-node="t1-discovery"]')).toHaveClass(/\bdim\b/);
  await page.mouse.move(5, 5);
  // the graph never pushes the panel wider than itself, and its height follows its content (its 16px margin)
  const g = await box.getByTestId("run-graph").boundingBox();
  const pane = await page.getByTestId("details").boundingBox();
  expect(g!.x + g!.width).toBeLessThanOrEqual(Math.ceil(pane!.x + pane!.width));
  const lowest = Math.max(...(await cards.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().bottom))));
  expect(g!.y + g!.height - lowest).toBeLessThanOrEqual(17);
});

test("card titles wrap at words to three lines; two alike titles stay apart; the meta line is proportional", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  const box = panel(page);
  await expect(box.getByTestId("run-node")).toHaveCount(6);
  await expect(box.locator(".rg-card.enter")).toHaveCount(0); // after the entrance
  const titles = await box.locator(".rg-t").evaluateAll((els) => els.map((e) => (e as HTMLElement).innerText));
  const labels = (await mock("runs.get", { bot: "kami", run: FAN })).run.nodes.map((n: any) => n.label);
  const words = new Set(labels.flatMap((l: string) => l.split(/\s+/)).concat(["Hermes:"]));
  for (const t of titles) {
    expect(t.split("\n").length).toBeLessThanOrEqual(3);
    // every word shown is a whole word of the label (no mid-word cut); a cut title ends with "…"
    for (const w of t.replace(/…$/, "").split(/\s+/)) expect(words.has(w) || words.has(w.replace(/^\(|\)$/g, ""))).toBe(true);
  }
  expect(new Set(titles).size).toBe(titles.length);
  expect(titles.filter((t) => t.startsWith("Hermes:")), JSON.stringify(titles)).toHaveLength(1);
  // one line high each, inside the card
  for (const c of await box.getByTestId("run-node").all()) {
    const [ch, sh] = await c.evaluate((e) => [e.clientHeight, e.scrollHeight]);
    expect(sh).toBeLessThanOrEqual(ch + 1);
  }
  expect(await box.locator(".rg-mt").first().evaluate((e) => getComputedStyle(e).fontFamily)).not.toMatch(/mono/i);
});

test("states look different: done, running, failed, waiting; selection is a gray ring on top", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", LIVE);
  await expect(box.locator(".rg-card.enter")).toHaveCount(0); // after the entrance
  const look = (id: string) =>
    box.locator(`[data-testid="run-node"][data-node="${id}"]`).evaluate((e) => {
      const s = getComputedStyle(e);
      return { border: s.borderLeftStyle + " " + s.borderLeftColor + " " + s.borderLeftWidth, style: s.borderTopStyle, tint: getComputedStyle(e, "::before").backgroundImage, op: s.opacity };
    });
  const done = await look("t2-status-update");
  const failed = await look("t1-discovery");
  const pending = await look("t5-verify");
  const running = await look("t3-doctor");
  expect(done.tint).toMatch(/gradient/);
  expect(Number(done.op)).toBe(1); // done never looks disabled
  expect(failed.border).toMatch(/3px$/);
  expect(["dashed", "dotted"]).toContain(pending.style);
  expect(running.tint).toMatch(/gradient/);
  expect(new Set([done.tint, failed.tint, running.tint]).size).toBe(3);
  // selecting the failed card keeps its rail and adds a gray (not gradient) ring
  const card = box.getByTestId("run-node").and(box.locator('[data-node="t1-discovery"]'));
  await card.click();
  await expect(card).toHaveClass(/\bon\b/);
  const sel = await card.evaluate((e) => [getComputedStyle(e).outlineStyle, getComputedStyle(e).outlineColor, getComputedStyle(e).borderLeftWidth]);
  expect(sel[0]).toBe("solid");
  const [r, g, b] = sel[1].match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24); // gray
  expect(sel[2]).toBe("3px");
});

test("clicking a node opens its drawer; a failed node offers 'Ask in chat', which only prefills the composer", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  const box = panel(page);
  await box.locator('[data-node="t5-verify"]').click();
  const drawer = page.getByTestId("run-drawer");
  await expect(drawer).toContainText("Independent verify vs base + live probes");
  await expect(drawer.getByTestId("run-attempt")).toHaveText("attempt 2 of 2");
  await expect(drawer.getByTestId("run-reason")).toContainText("2nd verifier HOLD");
  await expect(drawer.getByTestId("run-handoff")).toBeVisible();
  const before = (await drawer.getByTestId("run-handoff").innerText()).length;
  await drawer.getByTestId("run-handoff-more").click();
  await expect.poll(async () => (await drawer.getByTestId("run-handoff").innerText()).length).toBeGreaterThan(before);
  // the failed node: one rail (no outline around it), a red "failed", the reason, a quiet prefill button
  await box.locator('[data-node="t1-discovery"]').click();
  await expect(drawer).toHaveClass(/\bbad\b/);
  const frame = await drawer.evaluate((e) => {
    const s = getComputedStyle(e);
    return [s.borderLeftWidth, s.borderTopColor];
  });
  expect(frame[0]).toBe("3px");
  expect(frame[1]).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  const word = drawer.getByTestId("run-state-word");
  await expect(word).toHaveText("failed");
  expect(await word.evaluate((e) => getComputedStyle(e).color)).not.toBe(await drawer.evaluate((e) => getComputedStyle(e).color));
  await expect(drawer).toContainText("No handoff written.");
  await expect(drawer).not.toContainText("Ask Kami in chat to retry.");
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

test("a cancelled run is labelled, its unfinished nodes dimmed", async ({ page }) => {
  await openRuns(page);
  await showList(page);
  const r = page.getByTestId("run-row").filter({ hasText: "omh-dap" });
  await expect(r).toContainText("Cancelled");
  await r.click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CANCELLED);
  await expect(box.getByTestId("run-state")).toContainText("Cancelled");
  await expect(box.locator('[data-testid="run-node"][data-state="cancelled"]')).toHaveCount(2);
  expect(Number(await box.locator('[data-node="verify"]').evaluate((e) => getComputedStyle(e).opacity))).toBeLessThan(1);
});

test("a bot with no runs says so", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("panel-runs")).toContainText("No runs yet.");
});

// ---- T4: big runs, full view ----

test("40 nodes: no two cards overlap, the layout takes under 50 ms, crossings are reduced", async ({ page }) => {
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", BIG);
  const graph = box.getByTestId("run-graph");
  expect(Number(await graph.getAttribute("data-layout-ms"))).toBeLessThan(50);
  // the panel: no two cards (or group cards) overlap, and it never zooms by itself
  const cards = box.locator('[data-testid="run-node"], [data-testid="run-group"]');
  const boxes = await cards.evaluateAll((els: HTMLElement[]) => els.map((e) => ({ x: e.offsetLeft, y: e.offsetTop, width: e.offsetWidth, height: e.offsetHeight })));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(meets(boxes[i], boxes[j]), `${i} vs ${j}`).toBe(false);
  expect(await box.getByTestId("run-canvas").evaluate((e) => getComputedStyle(e).transform)).toBe("none");
  // the full view: all 40 as a layered graph, every link drawn
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await expect(f.getByTestId("run-node")).toHaveCount(40);
  await expect(f.getByTestId("run-graph")).toHaveAttribute("data-cols", "6");
  const fb = await f.getByTestId("run-node").evaluateAll((els: HTMLElement[]) => els.map((e) => ({ x: e.offsetLeft, y: e.offsetTop, width: e.offsetWidth, height: e.offsetHeight })));
  for (let i = 0; i < fb.length; i++) for (let j = i + 1; j < fb.length; j++) expect(meets(fb[i], fb[j]), `${i} vs ${j}`).toBe(false);
  const links = (await mock("runs.get", { bot: "default", run: BIG })).run.nodes.reduce((a: number, n: any) => a + n.deps.length, 0);
  await expect(f.getByTestId("run-edge")).toHaveCount(links);
});

/** Every card's width, title font size and title lines in the panel graph, plus titles cut mid-word. */
async function floorFacts(page: Page) {
  return panel(page).evaluate((b) => {
    const cards = [...b.querySelectorAll<HTMLElement>('[data-testid="run-node"], [data-testid="run-group"]')];
    const titles = [...b.querySelectorAll<HTMLElement>('[data-testid="run-node"] .rg-t')];
    return {
      minW: Math.min(...cards.map((c) => c.getBoundingClientRect().width)),
      minFont: Math.min(...titles.map((t) => parseFloat(getComputedStyle(t).fontSize) * (t.getBoundingClientRect().height / (t.offsetHeight || 1)))),
      maxLines: Math.max(...titles.map((t) => t.innerText.split("\n").length)),
      clipped: titles.filter((t) => t.scrollHeight > t.clientHeight + 1 || t.scrollWidth > t.clientWidth + 1).length,
    };
  });
}

test("the floor: no panel card narrower than 132px or set under 11px; titles at most 2 lines, never clipped", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [bot, row, id] of [
    ["kami", "Codex coexistence (live)", "run-row"],
    ["default", "omher v0.2", "run-row"],
    ["default", "Big run", "run-row"],
    ["kami", "Ship the API fix", "cli-run-row"],
  ] as const) {
    await openRuns(page, bot);
    await pickRow(page, row, id);
    await expect(panel(page).locator(".rg-card.enter")).toHaveCount(0);
    const f = await floorFacts(page);
    expect(f.minW, row).toBeGreaterThanOrEqual(132);
    expect(f.minFont, row).toBeGreaterThanOrEqual(11);
    expect(f.maxLines, row).toBeLessThanOrEqual(2);
    expect(f.clipped, row).toBe(0);
    // a title cut short ends with "…" and its card's tooltip names it whole
    for (const c of await panel(page).locator('[data-testid="run-node"]').all()) {
      const t = await c.locator(".rg-t").innerText();
      if (t.endsWith("…")) expect(await c.getAttribute("title")).toContain(t.replace(/\n/g, " ").replace(/…$/, "").split(" ")[0]);
    }
  }
});

test("a run too wide for its layers side by side stacks them as bands, every part on screen, 16px margins", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "omher v0.2");
  const box = panel(page);
  const graph = box.getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-mode", "stack");
  await expect(graph).toHaveAttribute("data-overflow", "false");
  await expect(graph).not.toHaveAttribute("data-fit", /.*/); // the floor's scale: no shrinking
  const nodes = (await mock("runs.get", { bot: "default", run: "dag:20261108_213859_c9a97486/omher-v02" })).run.nodes;
  await expect(box.getByTestId("run-node")).toHaveCount(nodes.length);
  // one band per layer, in order, its name and size
  expect(await box.getByTestId("run-col").evaluateAll((els) => els.map((e) => e.textContent))).toEqual(["L1 · Build · 3 parts", "L2 · Build · 4 parts", "L3 · Build · 1 part", "L4 · Verify · 1 part"]);
  // every card whole in the box, 16px from its sides; a band's last short row shares the width (no empty cell)
  await expect(box.locator(".rg-card.enter")).toHaveCount(0); // after the entrance (cards rise 6px into place)
  const geo = await box.evaluate((b) => {
    const g = b.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    const rs = [...b.querySelectorAll("[data-testid=run-node]")].map((c) => c.getBoundingClientRect());
    // per row (cards sharing a top), the gap from its last card to the box's right side
    const rows = new Map<number, number>();
    for (const r of rs) rows.set(Math.round(r.top), Math.max(rows.get(Math.round(r.top)) ?? 0, r.right));
    return { l: Math.min(...rs.map((r) => r.left)) - g.left, r: g.right - Math.max(...rs.map((r) => r.right)), b: g.bottom - Math.max(...rs.map((r) => r.bottom)), rights: [...rows.values()].map((x) => Math.round(g.right - x)) };
  });
  for (const k of ["l", "r", "b"] as const) expect(geo[k], k).toBeGreaterThanOrEqual(15);
  for (const k of ["l", "r"] as const) expect(geo[k], k).toBeLessThanOrEqual(18);
  for (const x of geo.rights) expect(x).toBeLessThanOrEqual(18);
  // no lines are drawn in the stack, and the legend names none; the full view keeps the graph with its links
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
  await expect(box.getByTestId("run-legend").locator('[class^="l-"]')).toHaveCount(0);
  await page.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-edge").first()).toBeVisible();
  await expect(full(page).getByTestId("route-pill").first()).toBeVisible();
});

test("a layer the box is too short for folds into a group card: counts, logos; it opens in place and folds back", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  const box = panel(page);
  const graph = box.getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-mode", "stack");
  await expect(graph).toHaveAttribute("data-overflow", "false");
  // every part is on screen once: as a card, or counted in its group card (read in one pass, after the box's height
  // settled: the fold follows the room the panel has)
  const accounted = () =>
    box.evaluate((b) =>
      [...b.querySelectorAll<HTMLElement>('[data-testid="run-node"], [data-testid="run-group"]')].reduce((a, e) => a + (e.dataset.testid === "run-group" ? Number(e.dataset.count) : 1), 0),
    );
  await expect.poll(accounted).toBe(40);
  await expect(box.locator(".rg-card.enter")).toHaveCount(0);
  const groups = box.getByTestId("run-group");
  expect(await groups.count()).toBeGreaterThan(0);
  const g = groups.first();
  const n = Number(await g.getAttribute("data-count"));
  const layer = Number(await g.getAttribute("data-layer"));
  const run = (await mock("runs.get", { bot: "default", run: BIG })).run;
  const members = run.nodes.filter((x: any) => x.layer === layer);
  expect(members).toHaveLength(n);
  // "9 parallel", its counts in the grid's order, stacked logos, the parts named in its tooltip
  await expect(g).toContainText(`${n} parallel`);
  const done = members.filter((x: any) => x.state === "done").length;
  await expect(g.getByTestId("run-group-counts")).toContainText(`${done} done`);
  expect(await g.locator(".rg-glogos [data-testid=node-mark]").count()).toBeGreaterThanOrEqual(1);
  expect(await g.getAttribute("title")).toContain(members[0].label);
  // the folded layer is the finished one: a layer with a running part stays open
  expect(members.some((x: any) => x.state === "running")).toBe(false);
  // opening it shows every part in place (the box scrolls if it must); its band label folds it back
  await g.click();
  await expect(box.locator(`[data-testid="run-group"][data-layer="${layer}"]`)).toHaveCount(0);
  for (const m of members) await expect(box.locator(`[data-testid="run-node"][data-node="${m.id}"]`)).toHaveCount(1);
  expect(await accounted()).toBe(40);
  await box.getByTestId("run-group-fold").click();
  await expect(box.locator(`[data-testid="run-group"][data-layer="${layer}"]`)).toHaveCount(1);
  // the full view always shows every part
  await page.getByTestId("graph-expand").click();
  await expect(full(page).getByTestId("run-node")).toHaveCount(40);
  await expect(full(page).getByTestId("run-group")).toHaveCount(0);
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("zoomed past the panel, a run opens on its running node, with fades and an 'Open full view' hint", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", BIG);
  const graph = box.getByTestId("run-graph");
  // it fits at first; two steps of + make it larger than the box
  await expect(graph).toHaveAttribute("data-overflow", "false");
  await box.getByTestId("run-zoom-in").click();
  await box.getByTestId("run-zoom-in").click();
  await expect(graph).toHaveAttribute("data-overflow", "true");
  // the first running node is in the visible part of the graph box, whole
  const live = box.locator('[data-testid="run-node"][data-state="running"]').first();
  const g = (await graph.boundingBox())!;
  const c = (await live.boundingBox())!;
  expect(c.x).toBeGreaterThanOrEqual(g.x - 1);
  expect(c.y).toBeGreaterThanOrEqual(g.y - 1);
  expect(c.x + c.width).toBeLessThanOrEqual(g.x + g.width + 1);
  expect(c.y + c.height).toBeLessThanOrEqual(g.y + g.height + 1);
  // a soft fade on each side that holds more of the run, none on a side that does not
  const [sl, sw, cw, st, sh, ch] = await graph.evaluate((e) => [e.scrollLeft, e.scrollWidth, e.clientWidth, e.scrollTop, e.scrollHeight, e.clientHeight]);
  await expect(box.getByTestId("run-fade-l")).toHaveAttribute("data-on", String(sl > 1));
  await expect(box.getByTestId("run-fade-r")).toHaveAttribute("data-on", String(sl + cw < sw - 1));
  await expect(box.getByTestId("run-fade-t")).toHaveAttribute("data-on", String(st > 1));
  await expect(box.getByTestId("run-fade-b")).toHaveAttribute("data-on", String(st + ch < sh - 1));
  expect(sw > cw || sh > ch).toBe(true);
  // the hint sits in the legend row, on screen, says how many parts are not whole in the box, and opens the full view
  const hint = box.getByTestId("run-full-hint");
  await expect(hint).toContainText(/Open full view (⌘⇧G|Ctrl\+Shift\+G)/);
  const cut = await box.evaluate((b) => {
    const g = b.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    return [...b.querySelectorAll('[data-testid="run-node"], [data-testid="run-group"]')].filter((c) => {
      const r = c.getBoundingClientRect();
      return r.left < g.left - 1 || r.right > g.right + 1 || r.top < g.top - 1 || r.bottom > g.bottom + 1;
    }).length;
  });
  expect(cut).toBeGreaterThan(0);
  await expect(box.getByTestId("run-hidden")).toHaveText(`${cut} more ·`);
  const pane = (await page.getByTestId("details").boundingBox())!;
  const h = (await hint.boundingBox())!;
  expect(h.y + h.height).toBeLessThanOrEqual(pane.y + pane.height);
  await hint.click();
  await expect(full(page)).toBeVisible();
  await page.keyboard.press("Escape");
  // a small run fits: no fades, no hint
  await openRuns(page);
  await pickRow(page, "Ship the API fix", "cli-run-row");
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-overflow", "false");
  await expect(box.getByTestId("run-full-hint")).toHaveCount(0);
  for (const k of ["l", "r", "t", "b"]) await expect(box.getByTestId(`run-fade-${k}`)).toHaveAttribute("data-on", "false");
  // a stacked run fits too, but its links live in the full view: the hint says so, with no "more" count
  await pickRow(page, "Codex coexistence fixes");
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-overflow", "false");
  await expect(box.getByTestId("run-full-hint")).toContainText("Open full view");
  await expect(box.getByTestId("run-hidden")).toHaveCount(0);
  for (const k of ["l", "r", "t", "b"]) await expect(box.getByTestId(`run-fade-${k}`)).toHaveAttribute("data-on", "false");
});

test("never a stub: zoomed in, a clipped side gets a fade and a '‹ N more' cue, and edges to it fade out", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  const box = panel(page);
  const graph = box.getByTestId("run-graph");
  const fit0 = Number(await graph.getAttribute("data-fit"));
  // fitted: every edge has both ends on screen, no mask, no cue
  await expect(box.getByTestId("run-edges-clip")).toHaveAttribute("data-mask", "false");
  await expect(box.locator(".rg-edge.off")).toHaveCount(0);
  await expect(box.locator(".rg-more")).toHaveCount(0);
  for (let i = 0; i < 3; i++) await box.getByTestId("run-zoom-in").click();
  await expect(graph).toHaveAttribute("data-overflow", "true");
  expect(Number(await graph.getAttribute("data-fit"))).toBeGreaterThan(fit0);
  await graph.evaluate((e) => (e.scrollLeft = e.scrollWidth / 2 - e.clientWidth / 2));
  await expect(box.getByTestId("run-fade-l")).toHaveAttribute("data-on", "true");
  await expect(box.getByTestId("run-fade-r")).toHaveAttribute("data-on", "true");
  // the cue counts the cards cut on its side
  const cut = await box.evaluate((b) => {
    const g = b.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    const rs = [...b.querySelectorAll("[data-testid=run-node]")].map((c) => c.getBoundingClientRect());
    return { l: rs.filter((r) => r.left < g.left - 1).length, r: rs.filter((r) => r.left >= g.left - 1 && r.right > g.right + 1).length };
  });
  await expect(box.getByTestId("run-more-l")).toHaveText(`‹ ${cut.l} more`);
  await expect(box.getByTestId("run-more-r")).toHaveText(`${cut.r} more ›`);
  // every edge with an end off screen is the quiet kind, and the edges fade out at the box's sides
  await expect(box.getByTestId("run-edges-clip")).toHaveAttribute("data-mask", "true");
  const bad = await box.evaluate((b) => {
    const g = b.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    const on = (id: string) => {
      const r = b.querySelector(`[data-testid=run-node][data-node="${id}"]`)!.getBoundingClientRect();
      return r.right > g.left + 8 && r.left < g.right - 8 && r.bottom > g.top + 8 && r.top < g.bottom - 8;
    };
    return [...b.querySelectorAll<SVGGElement>("[data-testid=run-edge]")].filter((e) => (!on(e.dataset.from!) || !on(e.dataset.to!)) && !e.classList.contains("off")).length;
  });
  expect(bad).toBe(0);
  // Fit brings it back whole
  await box.getByTestId("run-zoom-fit").click();
  await expect(graph).toHaveAttribute("data-overflow", "false");
  expect(Number(await graph.getAttribute("data-fit"))).toBe(fit0);
  await expect(box.locator(".rg-more")).toHaveCount(0);
});

test("the graph box is as tall as the run: no empty canvas under a short run; zoom sits in the legend row", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await pickRow(page, "Ship the API fix", "cli-run-row");
  const box = panel(page);
  const wrap = (await box.locator(".rn-gwrap").boundingBox())!;
  const g = (await box.getByTestId("run-graph").boundingBox())!;
  expect(wrap.height - g.height).toBeLessThanOrEqual(2);
  const lowest = Math.max(...(await box.getByTestId("run-node").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().bottom))));
  expect(g.y + g.height - lowest).toBeLessThanOrEqual(24);
  // − / Fit / + in the legend row, on its line
  const legend = (await box.getByTestId("run-legend").boundingBox())!;
  for (const id of ["run-zoom-out", "run-zoom-fit", "run-zoom-in"]) {
    const b = (await box.getByTestId(id).boundingBox())!;
    expect(b.y).toBeGreaterThanOrEqual(legend.y - 1);
    expect(b.y + b.height).toBeLessThanOrEqual(legend.y + legend.height + 1);
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
  // folded: no rows, the section header carries the toggle, the selected run's title and state lead the panel
  await expect(page.getByTestId("panel-runs")).toHaveAttribute("data-list", "closed");
  await expect(toggle).toHaveText("All 7 runs"); // the bot's 4 and the CLI agents' 3
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(page.getByTestId("cli-run-row")).toHaveCount(0);
  await expect(page.getByTestId("run-list-more")).toHaveCount(0);
  await expect(panel(page).getByTestId("run-state")).toContainText("Running");
  // the graph starts high and the running node is on screen, whole, with no scrolling
  const g = (await panel(page).getByTestId("run-graph").boundingBox())!;
  expect(g.y).toBeLessThanOrEqual(360);
  const live = (await panel(page).locator('[data-testid="run-node"][data-state="running"]').boundingBox())!;
  expect(live.y + live.height).toBeLessThanOrEqual(800);
  expect(await page.locator(".details .pn-scroll").evaluate((e) => e.scrollTop)).toBe(0);
  // the graph box is as tall as the run (no empty canvas under it) and the legend stays inside the panel
  const wrap = (await panel(page).locator(".rn-gwrap").boundingBox())!;
  expect(wrap.height - g.height).toBeLessThanOrEqual(2);
  const pane = (await page.locator(".details .pn-scroll").boundingBox())!;
  const leg = (await panel(page).getByTestId("run-legend").boundingBox())!;
  expect(leg.y + leg.height).toBeLessThanOrEqual(pane.y + pane.height + 0.5);
  // the toggle unfolds both lists; picking a run folds them away and opens it
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  await expect(page.getByTestId("cli-run-row")).toHaveCount(3);
  await page.getByTestId("run-row").filter({ hasText: "Codex coexistence fixes" }).click();
  await expect(panel(page)).toHaveAttribute("data-run", FAN);
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  // the toggle also folds the list back without picking
  await toggle.click();
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  await toggle.click();
  await expect(page.getByTestId("run-row")).toHaveCount(0);
  await expect(panel(page)).toHaveAttribute("data-run", FAN);
});

test("the panel plan card is one line of words; the layer chips get a second line only when they all fit", async ({ page }) => {
  await openRuns(page);
  const plan = panel(page).getByTestId("run-plan");
  const top = plan.locator(".rp-top");
  const lh = await top.evaluate((e) => e.getBoundingClientRect().height);
  expect(lh).toBeLessThanOrEqual(22);
  await expect(top).toContainText("3 layers · 6 parts");
  await expect(top.getByTestId("run-plan-counts")).toContainText("3 done");
  // the goal moves to the card's tooltip in the panel
  await expect(plan.locator(".rp-goal")).toHaveCount(0);
  expect(await plan.getAttribute("title")).toContain("OMH suggests its own skills");
  const chips = plan.getByTestId("run-plan-chips");
  await expect(chips).toHaveAttribute("data-fits", "true");
  await expect(chips).toBeVisible();
  // a one-layer run has no chip row (it would repeat "1 layer")
  await pickRow(page, "Ship the API fix", "cli-run-row");
  await expect(panel(page).getByTestId("run-plan")).toContainText("1 layer · ");
  await expect(panel(page).getByTestId("run-plan-chips")).toBeHidden();
  // a run with more layers than one line holds: no chips, the card stays two rows shorter
  await openRuns(page, "default");
  await pickRow(page, "Big run");
  const big = panel(page).getByTestId("run-plan-chips");
  const fits = await big.getAttribute("data-fits");
  const ol = await big.locator("ol").evaluate((e) => [e.scrollWidth, e.clientWidth]);
  expect(fits).toBe(ol[0] <= ol[1] + 1 ? "true" : "false");
  expect((await panel(page).getByTestId("run-plan").boundingBox())!.height).toBeLessThanOrEqual(fits === "true" ? 64 : 40);
});

test("the legend under the panel graph is never clipped by the panel's bottom", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  for (const id of ["cli-run-row", "run-row"]) {
    await showList(page);
    await page.getByTestId(id).first().click();
    const legend = panel(page).getByTestId("run-legend");
    await expect(legend).toBeVisible();
    const pane = (await page.locator(".details .pn-scroll").boundingBox())!;
    const l = (await legend.boundingBox())!;
    expect(l.y).toBeGreaterThanOrEqual(pane.y);
    expect(l.y + l.height).toBeLessThanOrEqual(pane.y + pane.height + 0.5);
  }
});

test("⌘⇧G and Expand open the full view over the chat; Esc and × close it; the header keeps one control", async ({ page }) => {
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
  await page.keyboard.press("Escape");
  await expect(full(page)).toHaveCount(0);
  await expect(page.getByTestId("details")).toBeVisible();
  await expect(panel(page)).toBeVisible();
  await page.getByTestId("graph-expand").click();
  await expect(full(page)).toBeVisible();
  await full(page).getByRole("button", { name: "Close graph" }).click();
  await expect(full(page)).toHaveCount(0);
});

test("full view: whole titles, a model mark on every routed node, route pill on one line", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  const t5 = f.locator('[data-node="t5-verify"]');
  await expect(t5.locator(".rg-t")).toHaveText("Independent verify vs base + live probes");
  // the model it ran on; a fanout node: the agent CLI that took it (codex -> the OpenAI mark)
  await expect(t5.getByTestId("node-mark")).toHaveAttribute("data-mark", "claude");
  await expect(f.locator('[data-node="t1-discovery"]').getByTestId("node-mark")).toHaveAttribute("data-mark", "openai");
  await expect(f.locator('[data-node="t1-discovery"]').getByTestId("node-mark")).toHaveAttribute("data-source", "executor");
  await expect(f.locator('[data-mark="category"]')).toHaveCount(0);
  await expect(f).not.toContainText("model not logged");
  await expect(t5).toContainText("Opus 5.5");
  await expect(t5).toContainText("attempt 2 of 2");
  const pill = t5.getByTestId("route-pill");
  await expect(pill).toHaveText("route: review");
  await expect(f.locator('[data-node="t3-doctor"]').getByTestId("route-pill")).toHaveText("route: low");
  await expect(f.locator('[data-node="t3-doctor"]').getByTestId("route-pill")).toHaveAttribute("title", "route: unspecified-low");
  const ph = await pill.evaluate((e) => [e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).lineHeight)]);
  expect(ph[0]).toBeLessThan(ph[1] * 1.6 + 4); // one line
  // nothing inside a card is clipped
  for (const c of await f.getByTestId("run-node").all()) {
    const [ch, sh] = await c.evaluate((e) => [e.clientHeight, e.scrollHeight]);
    expect(sh).toBeLessThanOrEqual(ch + 1);
  }
});

test("full view: nodes appear in layer order; edges draw after their ends; reduced motion turns it off", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const cards = full(page).getByTestId("run-node");
  await expect(cards).toHaveCount(6);
  const seen = await cards.evaluateAll((els) =>
    els.map((e) => ({ layer: Number(e.dataset.layer), i: Number(e.dataset.appear), delay: parseFloat(getComputedStyle(e).animationDelay) })),
  );
  const order = [...seen].sort((a, b) => a.i - b.i);
  for (let k = 1; k < order.length; k++) {
    expect(order[k].layer).toBeGreaterThanOrEqual(order[k - 1].layer);
    expect(order[k].delay).toBeGreaterThan(order[k - 1].delay);
  }
  expect(order[order.length - 1].delay).toBeLessThan(1.5);
  const edge = full(page).locator('[data-testid="run-edge"][data-to="t3-doctor"]');
  const ed = await edge.evaluate((g) => parseFloat(getComputedStyle(g.querySelector(".rg-line")!).animationDelay));
  const ends = await full(page).locator('[data-node="t2-status-update"], [data-node="t3-doctor"]').evaluateAll((els) => els.map((e) => parseFloat(getComputedStyle(e).animationDelay)));
  expect(ed).toBeGreaterThan(Math.max(...ends));
  // the panel finishes in under 1s
  const pd = await panel(page).getByTestId("run-node").evaluateAll((els) => els.map((e) => parseFloat(getComputedStyle(e).animationDelay) || 0));
  expect(Math.max(...pd) + 0.26 + 0.28).toBeLessThan(1);
});

test("reduced motion: no entrance, no shimmer, no pulse", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await mock("mock.reset");
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const names = await full(page)
    .locator(".rg-card, .rg-line, .rg-live")
    .evaluateAll((els) => els.map((e) => getComputedStyle(e).animationName));
  expect(names.every((n) => n === "none")).toBe(true);
  await expect(full(page).locator(".rg-card.enter")).toHaveCount(0);
  await ctx.close();
});

test("full view: drag moves a card and its edges; the position is kept; Reset restores; a click opens the drawer", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await page.waitForTimeout(1600); // entrance done
  const card = f.locator('[data-node="t3-doctor"]');
  const edge = f.locator('[data-testid="run-edge"][data-to="t3-doctor"]');
  const before = await card.boundingBox();
  const endBefore = await edge.getAttribute("data-end");
  await page.mouse.move(before!.x + 30, before!.y + 20);
  await page.mouse.down();
  await page.mouse.move(before!.x + 80, before!.y + 70, { steps: 6 });
  await page.mouse.up();
  const after = await card.boundingBox();
  expect(after!.x - before!.x).toBeGreaterThan(30);
  expect(after!.y - before!.y).toBeGreaterThan(30);
  await expect(page.getByTestId("run-drawer")).toHaveCount(0); // a drag is not a click
  expect(await edge.getAttribute("data-end")).not.toBe(endBefore);
  // the edge still ends on the card's left-middle
  const [, , x2, y2] = (await edge.getAttribute("data-end"))!.split(",").map(Number);
  const local = await card.evaluate((e: HTMLElement) => [e.offsetLeft, e.offsetTop + e.offsetHeight / 2]);
  expect([x2, y2]).toEqual(local);
  // kept per run
  const saved = await page.evaluate((id) => localStorage.getItem(`omher.runs.pos.${id}`), FAN);
  expect(JSON.parse(saved!)).toHaveProperty("t3-doctor");
  await page.keyboard.press("Escape");
  await page.getByTestId("graph-expand").click();
  await page.waitForTimeout(300);
  expect(await full(page).locator('[data-node="t3-doctor"]').evaluate((e: HTMLElement) => e.offsetLeft)).toBe(local[0]);
  // Reset puts it back where the layout put it
  await full(page).getByTestId("run-reset").click();
  await expect.poll(() => page.evaluate((id) => localStorage.getItem(`omher.runs.pos.${id}`), FAN)).toBeNull();
  expect(await full(page).locator('[data-node="t3-doctor"]').evaluate((e: HTMLElement) => e.offsetLeft)).not.toBe(local[0]);
  // a plain click (no drag) opens the same drawer as the panel
  await full(page).locator('[data-node="t1-discovery"]').click();
  await expect(full(page).getByTestId("run-drawer")).toContainText("Codex skill discovery reads .agents/skills");
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("full view: Fit, zoom keys and the wheel zoom; empty space pans", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const g = full(page).getByTestId("run-graph");
  const vw = page.viewportSize()!.width;
  await expect.poll(async () => Math.round(await full(page).evaluate((e) => e.getBoundingClientRect().right))).toBe(vw);
  await page.waitForTimeout(100); // the refit after the panel stepped aside
  const z0 = Number(await g.getAttribute("data-zoom"));
  const m = await mod(page);
  await page.keyboard.press(`${m}+Equal`);
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeGreaterThan(z0);
  await full(page).getByTestId("run-fit").click();
  await expect.poll(async () => Number(await g.getAttribute("data-zoom"))).toBeCloseTo(z0, 1);
  const b = await g.boundingBox();
  const card = full(page).locator('[data-node="t1-discovery"]');
  const c0 = await card.boundingBox();
  await page.mouse.move(b!.x + 12, b!.y + 12);
  await page.mouse.down();
  await page.mouse.move(b!.x + 72, b!.y + 52, { steps: 5 });
  await page.mouse.up();
  const c1 = await card.boundingBox();
  expect(Math.round(c1!.x - c0!.x)).toBe(60);
});


// ---- the finished look: logos, sizes, plan card, motion (on the LIVE fan-out)

test("live run: every node has a model logo (14px panel, 18px full); none says 'model not logged'", async ({ page }) => {
  await openRuns(page);
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", LIVE);
  const marks = box.getByTestId("node-mark");
  await expect(marks).toHaveCount(6);
  expect(await marks.evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).not.toContain("category");
  expect(Math.round((await marks.first().locator("svg, img").first().boundingBox())!.width)).toBe(14);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await expect(f.getByTestId("node-mark")).toHaveCount(6);
  expect(await f.getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")).sort())).toEqual(["claude", "openai", "openai", "openai", "openai", "openai"]);
  await expect(f).not.toContainText("model not logged");
  const w18 = await f.locator('[data-node="t3-doctor"] [data-testid="node-mark"]').evaluate((e) => (e.querySelector("svg, img") as Element).getBoundingClientRect().width);
  expect(Math.round(w18 / Number(await f.getByTestId("run-graph").getAttribute("data-zoom")))).toBe(18);
  await expect(f.locator('[data-node="t3-doctor"]')).toContainText("Codex");
  await expect(f.locator('[data-node="t5-verify"]')).toContainText("Opus 5.5");
});

test("node size carries meaning: leads taller, the closing verify a wider gate with its mark", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  await expect(f.getByTestId("run-node")).toHaveCount(6);
  const size = (id: string) => f.locator(`[data-testid="run-node"][data-node="${id}"]`).evaluate((e) => [(e as HTMLElement).dataset.size, (e as HTMLElement).offsetWidth, (e as HTMLElement).offsetHeight] as const);
  const [lead, normal, gate] = [await size("t2-status-update"), await size("t3-doctor"), await size("t5-verify")];
  expect(lead[0]).toBe("lead");
  expect(normal[0]).toBe("normal");
  expect(gate[0]).toBe("gate");
  expect(lead[2]).toBeGreaterThan(normal[2]);
  expect(lead[1]).toBe(normal[1]); // width stays fixed
  expect(gate[1]).toBeGreaterThan(normal[1]);
  await expect(f.locator('[data-node="t5-verify"] .rg-gate')).toHaveCount(1);
  await expect(f.locator('[data-node="t2-status-update"]').getByTestId("node-lead")).toHaveText("unblocks 2");
});

test("colours and motion: running has the brand ring, a shimmer and a glow; only edges into it flow", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("graph-expand").click();
  const f = full(page);
  const run = f.locator('[data-node="t3-doctor"]');
  await expect(run).toHaveClass(/\bs-running\b/);
  const look = await run.evaluate((e) => {
    const after = getComputedStyle(e, "::after");
    const before = getComputedStyle(e, "::before");
    return { ring: after.backgroundImage, ringAnim: after.animationName, sweep: before.animationName, glow: getComputedStyle(e).boxShadow };
  });
  expect(look.ring).toMatch(/conic-gradient/);
  expect(look.ringAnim).toBe("rg-turn");
  expect(look.sweep).toBe("rg-sweep");
  expect(look.glow).not.toBe("none");
  const done = await f.locator('[data-node="t2-status-update"]').evaluate((e) => getComputedStyle(e, "::before").backgroundImage);
  expect(done).toMatch(/gradient/);
  expect(await f.locator('[data-node="t5-verify"]').evaluate((e) => getComputedStyle(e).borderTopStyle)).toMatch(/dashed|dotted/);
  // the flow line only on edges into the running node
  const flows = await f.locator('[data-testid="run-edge"]').evaluateAll((els) => els.filter((g) => g.querySelector(".rg-flowline")).map((g) => (g as SVGGElement).dataset.to));
  expect(flows.length).toBeGreaterThan(0);
  expect(new Set(flows)).toEqual(new Set(["t3-doctor"]));
  // repair links are their own (amber, dashed) kind
  for (const id of ["t1-hermes", "t4-fence"]) await expect(f.locator(`[data-testid="run-edge"][data-from="t1-discovery"][data-to="${id}"]`)).toHaveClass(/\brepair\b/);
  // verify waits on the repairs, not on the failed node
  await expect(f.locator('[data-testid="run-edge"][data-from="t1-discovery"][data-to="t5-verify"]')).toHaveCount(0);
  await expect(f.getByTestId("run-legend")).toContainText("repair");
});

test("plan card: title, goal, layers as chips, counts and time, first in the panel and on top of the full view", async ({ page }) => {
  await openRuns(page);
  const plan = panel(page).getByTestId("run-plan");
  await expect(plan).toBeVisible();
  // it comes before the graph
  const [py, gy] = [(await plan.boundingBox())!.y, (await panel(page).getByTestId("run-graph").boundingBox())!.y];
  expect(py).toBeLessThan(gy);
  await expect(plan).toContainText("3 layers · 6 parts");
  // the panel keeps the goal in the card's tooltip; the full view prints it
  expect(await plan.getAttribute("title")).toContain("OMH suggests its own skills");
  // one name per layer, the same in the chips and over the graph's columns
  expect(await plan.getByTestId("run-plan-layer").allInnerTexts()).toEqual(["L1 · Plan", "L2 · Repair", "L3 · Verify"]);
  // the panel stacks this run's layers: each band starts with the same name
  expect((await panel(page).getByTestId("run-col").evaluateAll((els) => els.map((e) => e.querySelector(".rg-coln")?.textContent ?? e.textContent)))).toEqual(["L1 · Plan", "L2 · Repair", "L3 · Verify"]);
  const counts = plan.getByTestId("run-plan-counts");
  // the failed node's two repairs are done: it counts as repaired, not as an open failure
  for (const t of ["3 done", "1 running", "1 waiting", "1 repaired"]) await expect(counts).toContainText(t);
  await expect(counts).not.toContainText("failed");
  await expect(panel(page).locator('[data-node="t1-discovery"]')).toHaveClass(/\brepaired\b/);
  await expect(plan.getByTestId("run-plan-time")).toHaveText(/^\d+(s|m)$/);
  await page.getByTestId("graph-expand").click();
  const fp = full(page).getByTestId("run-plan");
  await expect(fp).toBeVisible();
  await expect(fp.locator(".rp-goal")).toContainText("OMH suggests its own skills");
  expect(await fp.getByTestId("run-plan-layer").allInnerTexts()).toEqual(["L1 Plan + Build · 2 parts", "L2 Repair + Check · 3 parts", "L3 Verify · 1 part"]);
});

test("a run that has not started: 'Starts in 0:..' with Start now / Edit, which only prefill the composer", async ({ page }) => {
  await openRuns(page, "default");
  await pickRow(page, "Codex coexistence (next)");
  const plan = panel(page).getByTestId("run-plan");
  await expect(plan.getByTestId("run-plan-time")).toHaveText(/^Starts in 0:(0\d|10)$/);
  await plan.getByTestId("run-plan-start").click();
  const composer = page.getByTestId("composer");
  await expect(composer).toHaveValue("Start run `codex-coexist-next` now");
  await plan.getByTestId("run-plan-edit").click();
  await expect(composer).toHaveValue("Edit the plan of run `codex-coexist-next`: ");
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

// ---- T5: helpers' models and routes ----

test("cards show the helper's model and a one-line route pill from the route record; a pill that does not fit is left out", async ({ page }) => {
  await openRuns(page);
  await pickRow(page, "Codex coexistence fixes");
  // a route pill shows whole or not at all (one line, never cut); a routed card without one names it in its tooltip
  const pills = panel(page).getByTestId("route-pill");
  const routed = (await mock("runs.get", { bot: "kami", run: FAN })).run.nodes.filter((n: any) => n.route);
  expect(routed.length).toBeGreaterThan(0);
  for (const n of routed) {
    const c = panel(page).locator(`[data-testid="run-node"][data-node="${n.id}"]`);
    if ((await c.getByTestId("route-pill").count()) === 0) expect(await c.getAttribute("title")).toContain(`route: ${n.route}`);
  }
  for (const pill of await pills.all()) {
    const p = await pill.evaluate((e) => [e.getBoundingClientRect().height, e.scrollWidth <= e.clientWidth + 1, getComputedStyle(e).whiteSpace, getComputedStyle(e).fontSize]);
    expect(p[0]).toBeLessThanOrEqual(16); // one line, never wraps
    expect(p[1]).toBe(true); // whole, never "r…"
    expect(p[2]).toBe("nowrap");
    expect(p[3]).toBe("9.5px");
  }
  await openRuns(page, "default");
  await pickRow(page, "omher v0.2");
  const box = panel(page);
  const card = box.locator('[data-node="t7-t10-usage"]');
  await expect(card.getByTestId("node-mark")).toHaveAttribute("data-mark", "claude");
  // "visual-engineering" does not fit this card: no pill (never a letter and "…"); the card's tooltip names it
  await expect(card.getByTestId("route-pill")).toHaveCount(0);
  expect(await card.getAttribute("title")).toContain("route: visual-engineering");
  for (const pill of await box.getByTestId("route-pill").all()) expect(await pill.evaluate((e) => e.scrollWidth <= e.clientWidth + 1)).toBe(true);
  // a node no helper ran yet: the model its route goes to (OMH's route records), never a hollow glyph
  const t9 = box.locator('[data-node="t9-verify"]');
  await expect(t9.getByTestId("node-mark")).toHaveAttribute("data-mark", "claude");
  await expect(t9.getByTestId("node-mark")).toHaveAttribute("data-source", "route");
  expect(await t9.getAttribute("title")).toContain("route: review");
  // the drawer names the model and effort from the delegation log
  await card.click();
  await expect(page.getByTestId("run-drawer")).toContainText("Opus 5.5 · high");
});

test("a delegate fan-out without a dag is its own one-layer run", async ({ page }) => {
  await openRuns(page, "default");
  await showList(page);
  const row = page.locator('[data-testid="run-row"][data-kind="delegate"]').first();
  await expect(row).toContainText("helpers");
  await row.click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", /^delegate:deleg_/);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-cols", "1");
  await expect(box.getByTestId("run-edge")).toHaveCount(0);
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

// ---- screenshots (T4-graph-*, T4-panel-*, T4-full-*, entrance frames) ----

for (const theme of ["dark", "light"] as const) {
  test(`screenshots: panel and full view, ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await openRuns(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    mkdirSync(SHOTS, { recursive: true });
    await expect(panel(page)).toHaveAttribute("data-run", LIVE);
    await page.waitForTimeout(1100);
    await page.mouse.move(5, 5);
    await page.getByTestId("details").screenshot({ path: join(SHOTS, `T4-panel-${theme}.png`) });
    await page.screenshot({ path: join(SHOTS, `T4-graph-panel-${theme}.png`) });
    await page.getByTestId("graph-expand").click();
    await page.waitForTimeout(1700);
    await page.mouse.move(700, 890);
    await page.screenshot({ path: join(SHOTS, `T4-full-${theme}.png`) });
    await full(page).locator('[data-node="t2-status-update"]').hover();
    await expect(full(page).getByTestId("run-tip")).toBeVisible();
    // the snippet never covers the card it describes, and hides at most a corner of any other
    const tip = (await full(page).getByTestId("run-tip").boundingBox())!;
    expect(meets(tip, (await full(page).locator('[data-testid="run-node"][data-node="t2-status-update"]').boundingBox())!)).toBe(false);
    for (const c of await full(page).getByTestId("run-node").all()) {
      const b = (await c.boundingBox())!;
      const ov = Math.max(0, Math.min(tip.x + tip.width, b.x + b.width) - Math.max(tip.x, b.x)) * Math.max(0, Math.min(tip.y + tip.height, b.y + b.height) - Math.max(tip.y, b.y));
      expect(ov / (b.width * b.height)).toBeLessThan(0.34);
    }
    await page.waitForTimeout(250);
    await page.screenshot({ path: join(SHOTS, `T4-full-hover-${theme}.png`) });
    await full(page).locator('[data-node="t1-discovery"]').click();
    await page.mouse.move(700, 890);
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(SHOTS, `T4-graph-full-${theme}.png`) });
  });
}

test("screenshots: entrance frames at 0 / 300 / 800 ms", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRuns(page);
  await expect(panel(page)).toHaveAttribute("data-run", LIVE);
  await page.waitForTimeout(1200);
  await page.getByTestId("graph-expand").click();
  await full(page).getByTestId("run-node").first().waitFor();
  // the frames are exact: every animation is paused and set to the same moment of the entrance
  const at = (ms: number) =>
    page.evaluate((t) => {
      for (const a of document.getAnimations()) {
        a.pause();
        a.currentTime = t;
      }
    }, ms);
  const shown = () =>
    full(page)
      .getByTestId("run-node")
      .evaluateAll((els) => els.filter((e) => Number(getComputedStyle(e).opacity) > 0.5).map((e) => Number((e as HTMLElement).dataset.layer)));
  const seen: number[][] = [];
  for (const ms of [0, 300, 800]) {
    await at(ms);
    seen.push(await shown());
    await page.screenshot({ path: join(SHOTS, `T4-enter-${ms}ms.png`) });
  }
  // nothing at 0, the first layer before the last at 300, everything by 800
  expect(seen[0]).toEqual([]);
  expect(Math.max(...seen[1])).toBeLessThan(2);
  expect(seen[2]).toHaveLength(6);
});

// ---- T6: CLI agents' runs (Claude Code subagents, Codex sub-agents) ----

const CLI_CLAUDE = "claude:ec38bc0b-8eb7-936b-b856-daaee28015c4";
const CLI_CODEX = "codex:c5e14c89-54b2-c703-769f-a6207ed501ea";
const CLI_LIVE = "claude:live-session";

test("CLI runs: listed under the bot's own runs with the agent's mark and name; each opens as a graph", async ({ page }) => {
  await openRuns(page);
  await showList(page);
  // the bot's own list is unchanged
  await expect(page.getByTestId("run-row")).toHaveCount(4);
  const rows = page.getByTestId("cli-run-row");
  await expect(rows).toHaveCount(3);
  await expect(page.getByTestId("panel-runs")).toContainText("CLI agents");
  expect(await rows.evaluateAll((els) => els.map((e) => [e.getAttribute("data-agent"), e.getAttribute("data-state")]))).toEqual([
    ["claude", "running"],
    ["claude", "failed"],
    ["codex", "done"],
  ]);
  // a plain text badge with the official mark: "Claude" / "Codex"
  await expect(rows.nth(0).getByTestId("run-agent")).toHaveText("Claude");
  await expect(rows.nth(0).locator("[data-mark]")).toHaveAttribute("data-mark", "claude");
  await expect(rows.nth(2).getByTestId("run-agent")).toHaveText("Codex");
  await expect(rows.nth(2).locator("[data-mark]")).toHaveAttribute("data-mark", "openai");
  await expect(rows.nth(0).locator(".rn-live")).toHaveCount(1);
  await expect(rows.nth(1)).toContainText("Failed");
  await expect(rows.nth(2).locator(".rn-n")).toHaveText(/^2\/2 · /);
  // the badge is gray, never the brand gradient, and one width so the titles after it line up
  expect(await rows.nth(0).getByTestId("run-agent").evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
  const titleX = await rows.evaluateAll((els) => els.map((e) => Math.round(e.querySelector(".rn-title")!.getBoundingClientRect().x)));
  expect(new Set(titleX).size).toBe(1);

  // Claude: one layer, the subagent's model on every node, the plan card, a failed call with its reason
  await rows.nth(1).click();
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CLI_CLAUDE);
  await expect(box.getByTestId("run-node")).toHaveCount(3);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-cols", "1");
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => [e.getAttribute("data-mark"), e.getAttribute("data-source")]))).toEqual([
    ["claude", "ran"],
    ["claude", "ran"],
    ["claude", "ran"],
  ]);
  await expect(box).not.toContainText("model not logged");
  await expect(box.getByTestId("run-plan")).toBeVisible();
  const bad = box.locator('[data-testid="run-node"][data-state="failed"]');
  await expect(bad).toHaveCount(1);
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
  await expect(box.getByTestId("node-mark")).toHaveCount(2);
  expect(await box.getByTestId("node-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(["openai", "openai"]);
  await box.getByTestId("run-node").first().click();
  await expect(page.getByTestId("run-drawer")).toContainText("gpt-6-astra · low");
  await expect(page.getByTestId("run-summary")).toContainText("API review done");

  // read-only: only reads went to the bridge
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls).toContain("runs.cli");
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

for (const theme of ["dark", "light"] as const) {
  test(`CLI runs: a live Claude session with its running subagent, panel and full view, ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await openRuns(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await showList(page);
    await page.getByTestId("cli-run-row").first().click();
    const box = panel(page);
    await expect(box).toHaveAttribute("data-run", CLI_LIVE);
    await expect(box.locator('[data-testid="run-node"][data-state="running"] [data-testid="node-mark"]')).toHaveAttribute("data-mark", "claude");
    mkdirSync(SHOTS, { recursive: true });
    await page.waitForTimeout(900);
    await page.screenshot({ path: join(SHOTS, `T6-cli-panel-${theme}.png`), animations: "disabled" });
    await page.getByTestId("graph-expand").click();
    const f = full(page);
    await expect(f.getByTestId("node-mark")).toHaveCount(3);
    await expect(f.locator('[data-testid="run-node"][data-state="running"]')).toHaveCount(1);
    await expect(f.getByTestId("run-node").first()).toContainText("Opus 5.5");
    // the running subagent's clock counts from its own start (1m30s ago), not 0s
    await expect(f.locator('[data-testid="run-node"][data-state="running"]')).toContainText(/1m so far/);
    await expect(f).not.toContainText("model not logged");
    await page.waitForTimeout(900);
    await page.screenshot({ path: join(SHOTS, `T6-cli-full-${theme}.png`), animations: "disabled" });
    await page.keyboard.press("Escape");
    await showList(page);
    await page.getByTestId("cli-run-row").nth(2).click();
    await expect(box).toHaveAttribute("data-run", CLI_CODEX);
    await page.waitForTimeout(900);
    await page.screenshot({ path: join(SHOTS, `T6-cli-codex-${theme}.png`), animations: "disabled" });
  });
}

test("88 parallel sub-runs: a grid across the panel, running then failed first, a summary, 'Show all' past 24", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // the Codex session grows to 88 sub-runs, as a real one did: 3 still running, 1 failed, 84 done
  const grow = (run: any) => {
    const base = run.nodes[0];
    run.nodes = Array.from({ length: 88 }, (_, i) => ({
      ...base,
      id: `sub-${i}`,
      label: i % 7 === 0 ? `Sub-run ${i}: a longer title that has to wrap onto a second line` : `Sub-run ${i}`,
      state: i >= 85 ? "running" : i === 40 ? "failed" : "done",
      ...(i >= 85 ? { ended: undefined } : {}),
    }));
    return run;
  };
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
        grow(msg.result.run);
        ws.send(JSON.stringify(msg));
        return;
      }
      if (msg.ok && op === "runs.cli")
        for (const r of msg.result.runs) if (r.id === CLI_CODEX) r.counts = { nodes: 88, done: 84, running: 3, failed: 1 };
      ws.send(op === "runs.cli" ? JSON.stringify(msg) : raw);
    });
  });
  await openRuns(page);
  await pickRow(page, "88", "cli-run-row");
  const box = panel(page);
  await expect(box).toHaveAttribute("data-run", CLI_CODEX);
  const graph = box.getByTestId("run-graph");
  await expect(graph).toHaveAttribute("data-mode", "grid");
  // the summary line
  await expect(box.getByTestId("run-sub-summary")).toHaveText("88 sub-runs · 3 running · 1 failed · 84 done");
  // 24 cards, running first, then the failure, then done
  const cards = box.getByTestId("run-node");
  await expect(cards).toHaveCount(24);
  expect((await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).slice(0, 5)).toEqual(["running", "running", "running", "failed", "done"]);
  // the width is used: as many columns as fit at the floor, edge to edge inside the 16px margins
  const geo = await box.evaluate((b) => {
    const g = b.querySelector("[data-testid=run-graph]")!.getBoundingClientRect();
    const rs = [...b.querySelectorAll("[data-testid=run-node]")].map((c) => c.getBoundingClientRect());
    const inView = rs.filter((r) => r.top >= g.top - 1 && r.bottom <= g.bottom + 1 && r.left >= g.left - 1 && r.right <= g.right + 1).length;
    return { inner: g.width - 32, used: Math.max(...rs.map((r) => r.right)) - Math.min(...rs.map((r) => r.left)), cols: new Set(rs.map((r) => Math.round(r.left))).size, minW: Math.min(...rs.map((r) => r.width)), inView, heights: new Set(rs.map((r) => Math.round(r.height))).size };
  });
  expect(geo.used / geo.inner).toBeGreaterThanOrEqual(0.98);
  expect(geo.cols).toBeGreaterThanOrEqual(2);
  expect(geo.minW).toBeGreaterThanOrEqual(132);
  expect(geo.inView).toBe(24);
  expect(geo.heights).toBe(1); // one row height: the grid reads as a table
  // each card: logo, title of at most 2 lines, time, state
  for (const c of (await cards.all()).slice(0, 6)) {
    await expect(c.getByTestId("node-mark")).toHaveCount(1);
    await expect(c.locator(".rg-st")).toHaveCount(1);
    expect((await c.locator(".rg-t").innerText()).split("\n").length).toBeLessThanOrEqual(2);
  }
  // "Show all 88" shows them all, and back
  const more = box.getByTestId("run-grid-all");
  await expect(more).toHaveText("Show all 88 · 64 more");
  await more.click();
  await expect(cards).toHaveCount(88);
  await expect(more).toHaveText("Show fewer");
  await more.click();
  await expect(cards).toHaveCount(24);
  // nothing written
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
});

test("runs.cli: filters by agent, cwd and since; bad params are refused", async () => {
  expect((await mock("runs.cli", { agent: "codex" })).runs.map((r: any) => r.id)).toEqual([CLI_CODEX]);
  expect((await mock("runs.cli", { cwd: "/w/web-app" })).runs.map((r: any) => r.agent)).toEqual(["claude", "claude"]);
  expect((await mock("runs.cli", { since: Date.now() / 1000 - 3600 })).runs.map((r: any) => r.id)).toEqual([CLI_LIVE]);
  expect((await mock("runs.cli", { agent: "grok" })).runs).toEqual([]);
  for (const bad of [{ agent: "cursor" }, { cwd: "" }, { since: "yesterday" }]) expect(await mockError("runs.cli", bad)).toBe("bad_request");
});

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
