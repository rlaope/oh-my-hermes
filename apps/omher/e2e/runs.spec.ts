// Runs tab: the bot's dag runs as a list and a read-only layered graph, from three real (redacted) runs.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-v02");
const FAN = "dag:20261102_235818_fcfb1bdd/codex-coexist";
const CANCELLED = "dag:20261026_134438_3ae70257/omh-dap";
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

async function openRuns(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  await expect(page.getByTestId("panel-runs")).toBeVisible();
}

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
  const sel = page.locator('[data-testid="run-row"][aria-current="true"]');
  expect(await sel.evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
});

test("the list puts the running run first with a live dot, then the newest; each row says done/total", async ({ page }) => {
  await openRuns(page);
  const rows = page.getByTestId("run-row");
  await expect(rows).toHaveCount(4);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).toEqual(["running", "done", "cancelled", "done"]);
  const upd = (await mock("runs.list", { bot: "kami" })).runs.map((r: any) => r.updated).slice(1);
  expect(upd).toEqual([...upd].sort((a: number, b: number) => b - a));
  await expect(rows.nth(0).locator(".rn-live")).toHaveCount(1);
  await expect(rows.nth(1).locator(".rn-live")).toHaveCount(0);
  await expect(rows.nth(0).locator(".rn-n")).toHaveText(/^3\/6 · \d+(s|m)$/);
  await expect(rows.nth(1)).toContainText("Codex coexistence fixes");
  await expect(rows.nth(1).locator(".rn-n")).toHaveText(/^5\/6 · /);
  // the running run is drawn by default, its running node ringed, not gradient-filled
  await expect(page.getByTestId("run-graph-box")).toHaveAttribute("data-state", "running");
  const doing = page.locator('[data-testid="run-node"][data-state="running"]');
  await expect(doing).toHaveCount(1);
  expect(await doing.evaluate((e) => getComputedStyle(e).boxShadow)).not.toBe("none");
  expect(await doing.evaluate((e) => getComputedStyle(e).backgroundImage)).toBe("none");
});

test("the fan-out draws 6 cards in 3 columns, one edge per dependency, the failed node marked", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("run-row").filter({ hasText: "Codex coexistence fixes" }).click();
  const box = page.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", FAN);
  const detail = await mock("runs.get", { bot: "kami", run: FAN });
  const deps = detail.run.nodes.reduce((a: number, n: any) => a + n.deps.length, 0);
  const cards = box.getByTestId("run-node");
  await expect(cards).toHaveCount(6);
  await expect(box.getByTestId("run-graph")).toHaveAttribute("data-cols", "3");
  const layers = await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-layer")));
  expect(new Set(layers)).toEqual(new Set(["0", "1", "2"]));
  // columns are real columns: every card of a layer shares one x
  const xs = await cards.evaluateAll((els) => els.map((e) => [e.getAttribute("data-layer"), Math.round(e.getBoundingClientRect().x)]));
  for (const l of ["0", "1", "2"]) expect(new Set(xs.filter(([k]) => k === l).map(([, x]) => x)).size).toBe(1);
  expect(deps).toBe(4);
  await expect(box.getByTestId("run-edge")).toHaveCount(deps);
  // each edge runs from the right-middle of its dep to the left-middle of its node
  const geo = await box.evaluate((el) => {
    const cards = Object.fromEntries(
      [...el.querySelectorAll<HTMLElement>('[data-testid="run-node"]')].map((c) => [
        c.dataset.node,
        { l: c.offsetLeft, r: c.offsetLeft + c.offsetWidth, m: c.offsetTop + c.offsetHeight / 2 },
      ]),
    );
    return { cards, paths: [...el.querySelectorAll("path")].map((p) => p.getAttribute("d")!) };
  });
  const ends = geo.paths.map((d) => d.match(/-?\d+(\.\d+)?/g)!.map(Number)).map((n) => [n[0], n[1], n[6], n[7]].join(","));
  const want = detail.run.nodes.flatMap((n: any) =>
    n.deps.map((d: string) => [geo.cards[d].r, geo.cards[d].m, geo.cards[n.id].l, geo.cards[n.id].m].join(",")),
  );
  expect(ends.sort()).toEqual(want.sort());
  const failed = box.locator('[data-node="t1-discovery"]');
  await expect(failed).toHaveClass(/\bbad\b/);
  await expect(failed.locator(".rn-g")).toHaveText("✕");
  await expect(box.locator('[data-node="t2-status-update"] .rn-g')).toHaveText("✓");
  // the graph never pushes the panel wider than itself
  const g = await box.getByTestId("run-graph").evaluate((e) => [e.clientWidth, e.getBoundingClientRect().right]);
  const panel = await page.getByTestId("details").boundingBox();
  expect(g[1]).toBeLessThanOrEqual(Math.ceil(panel!.x + panel!.width));
});

test("clicking a node opens its drawer with attempts, reason and handoff; no write controls", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("run-row").filter({ hasText: "Codex coexistence fixes" }).click();
  const box = page.getByTestId("run-graph-box");
  await box.locator('[data-node="t5-verify"]').click();
  const drawer = page.getByTestId("run-drawer");
  await expect(drawer).toContainText("Independent verify vs base + live probes");
  await expect(drawer.getByTestId("run-attempt")).toHaveText("attempt 2 of 2");
  await expect(drawer.getByTestId("run-reason")).toContainText("2nd verifier HOLD");
  await expect(drawer.getByTestId("run-handoff")).toBeVisible();
  const before = (await drawer.getByTestId("run-handoff").innerText()).length;
  await drawer.getByTestId("run-handoff-more").click();
  await expect.poll(async () => (await drawer.getByTestId("run-handoff").innerText()).length).toBeGreaterThan(before);
  // the failed node: red reason, a plain hint, and nothing that writes
  await box.locator('[data-node="t1-discovery"]').click();
  await expect(drawer.getByTestId("run-reason")).toHaveClass(/\bbad\b/);
  await expect(drawer).toContainText("No handoff written.");
  await expect(drawer).toContainText("Ask Kami in chat to retry.");
  expect(await page.getByTestId("run-graph-box").getByRole("button", { name: /retry|cancel|settle|stop/i }).count()).toBe(0);
  expect(await page.getByTestId("details-panel").locator("textarea, input, [contenteditable=true]").count()).toBe(0);
  await drawer.getByRole("button", { name: "Close node" }).click();
  await expect(drawer).toHaveCount(0);
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
  expect(calls).toEqual(expect.arrayContaining(["runs.list", "runs.get"]));
});

test("a cancelled run is labelled, its unfinished nodes dimmed", async ({ page }) => {
  await openRuns(page);
  const r = page.getByTestId("run-row").filter({ hasText: "omh-dap" });
  await expect(r).toContainText("Cancelled");
  await r.click();
  const box = page.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", CANCELLED);
  await expect(box.getByTestId("run-state")).toHaveText("Cancelled");
  await expect(box.locator('[data-testid="run-node"][data-state="cancelled"]')).toHaveCount(2);
  expect(Number(await box.locator('[data-node="verify"]').evaluate((e) => getComputedStyle(e).opacity))).toBeLessThan(1);
});

test("a bot with no runs says so", async ({ page }) => {
  await openRuns(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("panel-runs")).toContainText("No runs yet.");
});

for (const theme of ["dark", "light"] as const) {
  test(`screenshot: Runs tab, ${theme}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await openRuns(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.getByTestId("run-row").filter({ hasText: "Codex coexistence (live)" }).click();
    await page.getByTestId("run-graph-box").locator('[data-node="t1-discovery"]').click();
    await expect(page.getByTestId("run-drawer")).toBeVisible();
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `T3-runs-${theme}.png`) });
  });
}
