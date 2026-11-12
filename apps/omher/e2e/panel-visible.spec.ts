// The right panel is findable without a shortcut: one icon button right of the model control opens it (on Plans
// when the bot has live work or the person never picked a tab, else on their last tab) and closes it; it carries the
// live dot while subagents work. A turn's delegate_task opens the panel on Plans by itself once (≥1100px). Plans
// re-reads on its own, says plainly what it is for when empty, never opens on someone else's CLI run, and a run quiet
// for a day is not live.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const LIVE = "dag:20261102_235818_fcfb1bdd/codex-coexist-live";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "pv1") res(msg);
    };
    ws.send(JSON.stringify({ id: "pv1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const isOpen = async (page: Page) => /\bpanel-open\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "");
const runsListCalls = async () => ((await mock("mock.calls")).calls as { op: string }[]).filter((c) => c.op === "runs.list").length;

async function load(page: Page, bot = "kami") {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  if (bot !== "kami") await page.getByTestId(`bot-${bot}`).click();
  await expect(page.getByTestId("header")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the panel button sits right of the model control: closed it opens Plans, open it closes; gray when on, no accent", async ({ page }) => {
  await load(page, "friren");
  const right = page.getByTestId("head-right");
  await expect(right.locator(":scope > *")).toHaveCount(2);
  const btn = page.getByTestId("panel-button");
  // the second and last child, after the model control
  expect(await right.evaluate((el) => (el.lastElementChild as HTMLElement).dataset.testid)).toBe("panel-button");
  await expect(btn).toHaveAttribute("aria-pressed", "false");
  await expect(btn).toHaveAttribute("title", /^Panel \((⌘|Ctrl\+)\.\)$/);
  await expect(btn.getByTestId("panel-button-live")).toHaveCount(0);
  const box = (await btn.boundingBox())!;
  expect([Math.round(box.width), Math.round(box.height)]).toEqual([26, 26]);
  expect(await btn.evaluate((e) => getComputedStyle(e).borderTopWidth)).toBe("0px");
  // never opened a tab: the first open is on Plans
  await btn.click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  const on = await btn.evaluate((e) => ({ bg: getComputedStyle(e).backgroundColor, img: getComputedStyle(e).backgroundImage }));
  expect(on.img).toBe("none");
  expect(on.bg).not.toBe("rgba(0, 0, 0, 0)");
  await btn.click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  await expect(btn).toHaveAttribute("aria-pressed", "false");
  // once the person picks a tab, the button reopens on that tab
  await btn.click();
  await page.getByTestId("panel-tab-terminal").click();
  await btn.click();
  await btn.click();
  await expect(page.getByTestId("panel-tab-terminal")).toHaveAttribute("aria-selected", "true");
  // the bot's name still toggles the panel, as before
  await page.getByTestId("who").click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
});

test("while subagents work the button carries the live dot, says how many, and opens on Plans whatever tab was last", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.panelPicked", "1"));
  await load(page);
  const btn = page.getByTestId("panel-button");
  // Kami's live plan: 2 running parts (codex-coexist-live) — the stale and finished runs are not counted
  await expect(btn.getByTestId("panel-button-live")).toBeVisible();
  const n = Number(await btn.getAttribute("data-working"));
  expect(n).toBeGreaterThan(0);
  await expect(btn).toHaveAttribute("title", new RegExp(`^Plans · ${n} subagents? working \\((⌘|Ctrl\\+)\\.\\)$`));
  // the dot is the brand mark on the button's corner, inside its box
  const [b, d] = [(await btn.boundingBox())!, (await btn.getByTestId("panel-button-live").boundingBox())!];
  expect(d.x + d.width).toBeLessThanOrEqual(b.x + b.width + 0.5);
  expect(d.y).toBeGreaterThanOrEqual(b.y - 0.5);
  await btn.click();
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
});

test("Korean: the tooltip and the empty Plans text read without a particle after the bot's name", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await load(page, "friren");
  await expect(page.getByTestId("panel-button")).toHaveAttribute("title", /^패널 \((⌘|Ctrl\+)\.\)$/);
  await page.getByTestId("panel-button").click();
  const empty = page.getByTestId("plans-empty");
  await expect(empty).toContainText("아직 계획이 없습니다.");
  await expect(empty).toContainText("서브에이전트");
  await expect(empty).toContainText("dag ulw");
  await expect(empty).not.toContainText("(가)");
});

test("a bot with no plans of its own but CLI agent runs: no empty state over a CLI graph, and no CLI run picked for it", async ({ page }) => {
  await load(page, "omh-tui");
  await page.getByTestId("panel-button").click();
  const tab = page.getByTestId("panel-runs");
  await expect(tab).toBeVisible();
  // nothing of its own is selected: the empty state, then the CLI agents' list below it, and no graph
  await expect(page.getByTestId("plans-empty")).toBeVisible();
  await expect(page.getByTestId("plans-empty")).toContainText("No plans yet.");
  await expect(page.getByTestId("run-graph-box")).toHaveCount(0);
  await expect(page.getByTestId("cli-run-row")).toHaveCount(3);
  // picking a CLI run shows it; the empty text goes, and the toggle names what is listed
  await page.getByTestId("cli-run-row").first().click();
  await expect(page.getByTestId("run-graph-box")).toBeVisible();
  await expect(page.getByTestId("plans-empty")).toHaveCount(0);
  await expect(page.getByTestId("run-list-toggle")).toHaveText(/^CLI agents \(3\)/);
  await expect(tab).not.toContainText("No plans yet.");
});

test("Plans re-reads by itself while a run is live: a node's change shows within 5 s with no click", async ({ page }) => {
  await load(page);
  await page.getByTestId("panel-button").click();
  const box = page.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", LIVE);
  const node = box.locator('[data-testid="run-node"][data-state="running"]').first();
  const id = (await node.getAttribute("data-node"))!;
  await mock("mock.runNode", { bot: "kami", run: LIVE, node: id, state: "done" });
  await expect(box.locator(`[data-testid="run-node"][data-node="${id}"]`)).toHaveAttribute("data-state", "done", { timeout: 5000 });
});

test("the reads stop while the window is hidden and pick up when it shows again", async ({ page }) => {
  await load(page);
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("run-graph-box")).toBeVisible();
  const hide = (v: "hidden" | "visible") =>
    page.evaluate((v) => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v });
      document.dispatchEvent(new Event("visibilitychange"));
    }, v);
  await hide("hidden");
  await page.waitForTimeout(300);
  const before = await runsListCalls();
  await page.waitForTimeout(7000);
  expect(await runsListCalls()).toBe(before);
  await hide("visible");
  await expect.poll(runsListCalls).toBeGreaterThan(before);
});

test("a delegate_task opens the panel on Plans once per turn, and a close during that turn sticks", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 820 });
  await load(page, "friren");
  expect(await isOpen(page)).toBe(false);
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "friren" },
      { event: "tool.start", bot: "friren", tool_id: "d1", name: "delegate_task", detail: "Two lookups", dag: [{ run: "codex-coexist-live", node: "t3-doctor" }] },
    ],
  });
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  // a second fan-out in the same turn leaves it closed
  await mock("mock.emit", {
    events: [
      { event: "tool.end", bot: "friren", tool_id: "d1", name: "delegate_task", ok: true, ms: 10 },
      { event: "tool.start", bot: "friren", tool_id: "d2", name: "delegate_task", detail: "Again", dag: [{ run: "codex-coexist-live", node: "t5-verify" }] },
    ],
  });
  await page.waitForTimeout(500);
  expect(await isOpen(page)).toBe(false);
  // the next turn opens it again
  await mock("mock.emit", {
    events: [
      { event: "turn.end", bot: "friren", outcome: "done" },
      { event: "turn.start", bot: "friren" },
      { event: "tool.start", bot: "friren", tool_id: "d3", name: "delegate_task", detail: "Once more", dag: [{ run: "codex-coexist-live", node: "t5-verify" }] },
    ],
  });
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
});

test("narrower than 1100px a delegate_task leaves the panel closed (it would cover the chat)", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 760 });
  await load(page, "friren");
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "friren" },
      { event: "tool.start", bot: "friren", tool_id: "d1", name: "delegate_task", detail: "Two lookups", dag: [{ run: "codex-coexist-live", node: "t3-doctor" }] },
    ],
  });
  await expect(page.getByTestId("activity")).toHaveCount(1);
  await page.waitForTimeout(500);
  expect(await isOpen(page)).toBe(false);
});

test("/delegate on the mock: the panel opens on the run, and the summary counts the rows the details show", async ({ page }) => {
  await load(page);
  await page.getByTestId("composer").fill("/delegate two lookups");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("run-graph-box")).toHaveAttribute("data-run", LIVE);
  const act = page.getByTestId("activity").last();
  await expect(act).toHaveAttribute("data-state", "done");
  await expect(act.getByTestId("activity-text")).toHaveText(/ · 2 steps$/);
  await act.getByTestId("activity-toggle").click();
  await expect(act.getByTestId("activity-dag")).toHaveCount(2);
});

test("a run quiet for a day is not live: no live dot, a muted 'no update for', not counted on the button", async ({ page }) => {
  // the bridge marks it (`stale`); here the live plan's list row says so
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
      if (msg.ok && ops.get(msg.id) === "runs.list")
        for (const r of msg.result.runs)
          if (r.state === "running") Object.assign(r, { stale: true, updated: Date.now() / 1000 - 9 * 86400 - 60 });
      ws.send(JSON.stringify(msg));
    });
  });
  await load(page);
  const btn = page.getByTestId("panel-button");
  await expect(btn).toHaveAttribute("data-working", "0");
  await expect(btn.getByTestId("panel-button-live")).toHaveCount(0);
  await btn.click();
  await page.getByTestId("run-list-toggle").click();
  const row = page.locator('[data-testid="run-row"][data-stale="true"]').first();
  await expect(row).toBeVisible();
  await expect(row.locator(".rn-live")).toHaveCount(0);
  await expect(row.getByTestId("run-row-stale")).toHaveText("no update for 9d");
  // stale rows are listed after the finished ones that changed since
  const states = await page.getByTestId("run-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-stale") === "true"));
  expect(states[0]).toBe(false);
});

test("900px with a long model id: the model control gives way, the panel button stays whole and on top", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  const long = "openrouter-preview/anthropic/claude-opus-5-5-thinking-extended-2026-11-01";
  await mock("chat.set_model", { bot: "kami", model: long });
  await load(page);
  const head = (await page.getByTestId("header").boundingBox())!;
  const btn = page.getByTestId("panel-button");
  const b = (await btn.boundingBox())!;
  expect(Math.round(b.width)).toBe(26);
  expect(b.x + b.width).toBeLessThanOrEqual(head.x + head.width + 0.5);
  const pill = (await page.getByTestId("model-pill").boundingBox())!;
  expect(pill.x + pill.width).toBeLessThanOrEqual(b.x + 0.5);
  const label = page.getByTestId("model-label");
  expect(await label.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  // what is at the button's centre is the button (nothing overlaps it)
  const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("[data-testid]")?.getAttribute("data-testid"), [b.x + b.width / 2, b.y + b.height / 2]);
  expect(hit).toBe("panel-button");
  // the bot name, places chip and model control do not run into each other
  const ids = ["who", "places", "model-pill", "panel-button"];
  const rects = await page.evaluate((ids) => ids.map((id) => document.querySelector(`[data-testid="${id}"]`)?.getBoundingClientRect().toJSON() ?? null), ids);
  const present = rects.filter(Boolean) as { left: number; right: number }[];
  for (let i = 1; i < present.length; i++) expect(present[i].left).toBeGreaterThanOrEqual(present[i - 1].right - 0.5);
});
