// Changed-flow proof: an attached oh-my-hermes folder's Plans panel reads only its DAG.
import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const FIXTURE = "dag:20261028_093610_1b12a114/route-hint-dedup";

async function mock(op: string, params: Record<string, unknown> = {}) {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((resolve, reject) => { ws.onopen = () => resolve(); ws.onerror = () => reject(new Error("mock bridge unavailable")); });
  const result = await new Promise<{ ok: boolean; result?: Record<string, unknown>; error?: unknown }>((resolve) => {
    ws.onmessage = (m) => { const frame = JSON.parse(String(m.data)); if (frame.id === "dag-test") resolve(frame); };
    ws.send(JSON.stringify({ id: "dag-test", op, ...params }));
  });
  ws.close();
  if (!result.ok) throw new Error(`${op}: ${JSON.stringify(result.error)}`);
  return result.result ?? {};
}

test.beforeEach(async () => { await mock("mock.reset"); });

test("selected folder shows its DAG and only the clicked node's inert handoff", async ({ page }) => {
  test.setTimeout(90000);
  const attachments: { bot: string; cwd: string; fid: string; stored: string }[] = [];
  let connections = 0;
  let delayNode = false;
  let releaseNode: (() => void) | undefined;
  let disconnect: () => void = () => { throw new Error("bridge is not connected"); };
  await page.routeWebSocket(new RegExp(`127\\.0\\.0\\.1:${MOCK}`), (ws) => {
    const server = ws.connectToServer();
    // Withhold exactly one already-computed response from the real app, not from the mock's store.
    const delayed = new Set<string>();
    const opens = new Map<string, { bot: string; cwd: string }>();
    ws.onMessage((raw) => {
      const req = JSON.parse(String(raw));
      if (req.op === "folder.open") opens.set(req.id, { bot: req.bot, cwd: req.cwd });
      if (delayNode && req.op === "runs.session_get" && req.node === "verify") {
        delayNode = false; delayed.add(req.id);
      }
      server.send(raw);
    });
    server.onMessage((raw) => {
      const reply = JSON.parse(String(raw));
      const opened = opens.get(reply.id);
      if (opened && reply.ok) {
        opens.delete(reply.id);
        attachments.push({ ...opened, fid: reply.result.session, stored: reply.result.stored });
      }
      if (delayed.delete(reply.id)) {
        reply.result.handoffs.verify = "PRIVATE_LATE_VERIFY";
        releaseNode = () => ws.send(JSON.stringify(reply));
      } else ws.send(raw);
    });
    connections++;
    disconnect = () => { void ws.close({ code: 1011, reason: "test reconnect" }); };
  });
  await page.goto("/");
  const bot = "kami";
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const panel = page.getByTestId("session-dag-panel");
  async function openFolder(cwd: string, fixture: string) {
    // Browser-host substitute for the OS directory picker only. Navigation, creation and selection are UI clicks.
    await page.evaluate((path) => { Object.assign(window, { __omherPickFolder: path }); }, cwd);
    await page.getByTestId("places").click();
    await page.getByRole("tab", { name: "Details", exact: true }).click();
    await page.getByRole("button", { name: "New folder session…" }).click();
    await expect(panel).toBeVisible();
    await expect.poll(() => attachments.at(-1)?.cwd).toBe(cwd);
    const attached = attachments.at(-1)!;
    expect(attached.bot).toBe(bot);
    expect(attached.fid).toMatch(/^f[0-9a-f]{10}$/);
    await expect(page.getByTestId("session-chat")).toHaveAttribute("data-pane", `fold:${bot}:${attached.fid}`);
    await expect(panel.getByRole("status")).toContainText("No DAG runs");
    const seeded = await mock("mock.sessionDag", { bot, session: attached.fid, fixture });
    const run = `dag:${attached.stored}/${fixture.split("/").at(-1)}`;
    expect(seeded.run).toBe(run);
    await page.getByTestId("panel-button").click();
    await page.getByTestId("panel-button").click();
    return { ...attached, run };
  }
  const { fid, run, stored } = await openFolder("/home/you/code/omher", FIXTURE);
  await expect(panel.getByTestId("run-graph-box")).toHaveAttribute("data-run", run);
  await expect(panel.getByTestId("run-node")).toHaveCount(2);
  const pick = panel.locator('[data-testid="run-node"][data-node="implement"]');
  await pick.focus();
  await page.keyboard.press("Enter");
  await expect(pick).toBeFocused();
  await expect(pick).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node).map((c) => c.params.node)).toEqual(["implement"]);
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  const scoped = await mock("runs.session_get", { bot, session: fid, run, node: "implement" }) as { run: { nodes: { id: string; handoff?: string; attempts: { reason?: string }[] }[] }; handoffs: Record<string, string> };
  expect(Object.keys(scoped.handoffs)).toEqual(["implement"]);
  const sibling = scoped.run.nodes.find((n) => n.id === "verify")!;
  expect(sibling.handoff).toBeUndefined();
  expect(sibling.attempts.every((a) => a.reason === undefined)).toBe(true);
  const bare = await mock("runs.session_get", { bot, session: fid, run }) as typeof scoped;
  expect(bare.handoffs).toEqual({});
  expect(bare.run.nodes.every((n) => n.handoff === undefined && n.attempts.every((a) => a.reason === undefined))).toBe(true);
  // Focus refresh must retain the selected drawer and its handoff; no second click should be needed.
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && !c.params.node).length).toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node === "implement").length).toBeGreaterThanOrEqual(2);
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  await expect(panel.getByTestId("run-handoff")).not.toContainText("verify handoff");
  const nodeReads = (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node === "implement").length;
  // The 15-second foreground tick must reread the open node without closing its drawer.
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node === "implement").length, { timeout: 22000 }).toBeGreaterThan(nodeReads);
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  await expect(panel.locator("[data-evidence] img, [data-evidence] a, [data-testid=run-session], [data-testid=run-ask]")).toHaveCount(0);
  // The selected node remains open and is read again after a bridge reconnect.
  const beforeReconnect = connections;
  const beforeReconnectReads = (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node === "implement").length;
  disconnect();
  await expect.poll(() => connections, { timeout: 10000 }).toBeGreaterThan(beforeReconnect);
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.filter((c) => c.op === "runs.session_get" && c.params.node === "implement").length).toBeGreaterThan(beforeReconnectReads);
  // Deliver verify's private reply *after* implement is selected again. The panel must ignore it.
  delayNode = true;
  await panel.locator('[data-testid="run-node"][data-node="verify"]').click();
  await expect.poll(() => typeof releaseNode).toBe("function");
  await pick.click();
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  releaseNode!();
  // A later focus read acts as an ordered WS barrier after the delayed frame.
  const prior = (await mock("mock.calls") as { calls: unknown[] }).calls.length;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(async () => (await mock("mock.calls") as { calls: { op: string; params: { node?: string } }[] }).calls.slice(prior)
    .some((c) => c.op === "runs.session_get" && c.params.node === "implement")).toBe(true);
  await expect(panel.getByTestId("run-drawer")).toHaveAttribute("data-node", "implement");
  await expect(panel.getByTestId("run-handoff")).not.toContainText("PRIVATE_LATE_VERIFY");
  const shotDir = process.env.OMHER_SHOTS;
  if (shotDir) { mkdirSync(shotDir, { recursive: true }); await page.screenshot({ path: join(shotDir, "session-dag-evidence.png"), animations: "disabled" }); }
  await page.getByTestId("panel-button").click();
  await expect(panel).toHaveCount(0);

  // A second folder on the same bot has a different bridge-issued key and DAG.
  // Switching the app's selected session must not reuse the first folder's evidence.
  await page.getByTestId("bot-kami").click();
  const second = await openFolder("/home/you/code/second-folder", "dag:20261102_235818_fcfb1bdd/codex-coexist");
  const secondFid = second.fid;
  expect(secondFid).not.toBe(fid);
  expect(second.stored).not.toBe(stored);
  await expect(panel.getByTestId("run-graph-box")).toHaveAttribute("data-run", String(second.run));
  await expect(panel.getByTestId("run-graph-box")).not.toHaveAttribute("data-run", run);
  await panel.locator('[data-testid="run-node"][data-node="t2-status-update"]').click();
  await expect(panel.getByTestId("run-handoff")).toBeVisible();
  await expect(panel.getByTestId("run-handoff").locator('[data-evidence="basic-v1"]')).toBeVisible();
  await expect(panel.getByTestId("run-handoff")).toContainText("Links");
  await expect(panel.locator("[data-evidence] img, [data-evidence] a, [data-testid=run-session], [data-testid=run-ask]")).toHaveCount(0);
  await expect(mock("runs.session_get", { bot, session: secondFid, run, node: "implement" })).rejects.toThrow("not_found");
  await expect(mock("runs.session_list", { bot, session: fid, extra: true })).rejects.toThrow("bad_request");
  await expect(mock("runs.session_list", { bot, session: stored })).rejects.toThrow("bad_request");
  await expect(mock("runs.session_list", { bot: "default", session: fid })).rejects.toThrow("not_found");
  // Revisit the exact first attachment from Details, without creating a new chat or sending any prompt.
  await page.getByTestId("panel-button").click();
  await page.getByTestId("bot-kami").click();
  await page.getByTestId("places").click();
  await page.getByRole("tab", { name: "Details", exact: true }).click();
  await page.getByRole("button", { name: `/home/you/code/omher · ${stored}`, exact: true }).click();
  await expect(panel.getByTestId("run-graph-box")).toHaveAttribute("data-run", run);
  expect(attachments).toHaveLength(2);
  const calls = (await mock("mock.calls") as { calls: { op: string }[] }).calls;
  expect(calls.filter(({ op }) => ["chat.send", "approval.respond", "clarify.respond"].includes(op))).toEqual([]);
});
