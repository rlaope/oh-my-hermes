// A SESSIONS chat shows the subagents its agent starts: one card per fan-out with one row each (name, task, state,
// time; opens to its steps and answer), a subagent's approval names it, the header's panel button opens Plans for
// that session alone, and work left in the background after a turn is said in the header. Events are the ones the
// Claude adapter emitted for a real run (src-tauri/tests/fixtures/real/claude-9-*.jsonl). Read-only: nothing in
// these views assigns, steers or stops a subagent.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function session(page: Page, first: string) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("two subagents in parallel: one card, one row each, live then answered", async ({ page }) => {
  await session(page, "/subagents");
  const card = page.getByTestId("fanout-card");
  await expect(card).toHaveCount(1);
  const rows = card.getByTestId("subagent-row");
  await expect(rows).toHaveCount(2);
  // name and task, never the word "helper"
  await expect(rows.nth(0).getByTestId("subagent-goal")).toHaveText("general-purpose · Read a.txt first line");
  await expect(rows.nth(1).getByTestId("subagent-goal")).toHaveText("general-purpose · Count lines of b.txt");
  await expect(rows.nth(0)).toHaveAttribute("data-agent", "claude");
  // the first hands back while the second still works: the card stays running, the turn is not over
  await expect(rows.nth(0)).toHaveAttribute("data-state", "done");
  await expect(rows.nth(1)).toHaveAttribute("data-state", "running");
  await expect(rows.nth(0).getByTestId("subagent-line")).toHaveText("alpha line");
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(page.getByTestId("panel-button")).toHaveAttribute("data-working", "1");
  await expect(page.getByTestId("panel-button-live")).toBeVisible();
  // both done: the card reads "Ran 2 subagents", the session is idle
  await expect(rows.nth(1)).toHaveAttribute("data-state", "done");
  await expect(card).toHaveAttribute("data-state", "done");
  await expect(card.getByTestId("fanout-summary")).toContainText("2 subagents");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("panel-button")).toHaveAttribute("data-working", "0");
  // a row opens to its own steps and its answer
  await rows.nth(1).getByTestId("subagent-open").click();
  await expect(rows.nth(1).getByTestId("subagent-step")).toHaveText(["b.txt"]);
  await expect(rows.nth(1).getByTestId("subagent-answer")).toHaveText("3");
  await expect(page.locator("body")).not.toContainText(/helper/i);
  // nothing was sent to the agent for the subagents: one send, no steering
  expect((await calls(page)).filter((c) => c.op === "chat.input").map((c) => c.input?.kind)).toEqual(["send"]);
});

test("a subagent's approval names the subagent; answering it lets the subagent finish", async ({ page }) => {
  await session(page, "/subask");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("card-subagent")).toHaveText("Subagent Write c.txt via echo asks");
  await expect(card.locator(".card-cmd")).toHaveText("echo three > c.txt");
  await expect(page.getByTestId("session-status")).toHaveText("Needs you");
  await card.locator(".card-btn", { hasText: "Allow once" }).click();
  const row = page.getByTestId("fanout-card").getByTestId("subagent-row");
  await expect(row).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  const approve = (await calls(page)).find((c) => c.input?.kind === "approve");
  expect(approve?.input?.choice).toBe("once");
});

test("the session header's panel button opens Plans for that session alone", async ({ page }) => {
  await session(page, "/subagents");
  await expect(page.getByTestId("fanout-card")).toHaveAttribute("data-state", "done");
  // before the agent's own record exists: the chat's rows
  await page.getByTestId("panel-button").click();
  const panel = page.getByTestId("panel-runs");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("session-plans-rows").getByTestId("subagent-row")).toHaveCount(2);
  // the agent wrote its record: the session's own run, as a graph with each subagent's node
  await mock("mock.sessionRun");
  await page.getByTestId("panel-button").click();
  await page.getByTestId("panel-button").click();
  const box = panel.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", "claude:11111111-2222-4333-8444-555555555555");
  await expect(box.locator("[data-testid=run-node]")).toHaveCount(2);
  await expect(box.getByTestId("node-title")).toHaveText(["Read a.txt first line", "Count lines of b.txt"]);
  // the bot's own runs are not listed in a session's panel
  await expect(panel.getByTestId("cli-run-row")).toHaveCount(0);
  await expect(panel.getByTestId("run-row")).toHaveCount(0);
  // the fan-out card's Plans button opens the same panel
  await page.getByTestId("panel-button").click();
  await expect(panel).toHaveCount(0);
  await page.getByTestId("fanout-open").click();
  await expect(page.getByTestId("panel-runs")).toHaveAttribute("data-session", /.+/);
});

test("work left in the background after a turn is said in the header until it ends", async ({ page }) => {
  await session(page, "/background");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-background")).toHaveText("1 still running in the background");
  await expect(page.getByTestId("session-background")).toHaveCount(0);
});

/** Seconds of an elapsed label under a minute ("3s"); a test fan-out never runs longer. */
const secs = (s: string) => {
  const m = /^(\d+)s$/.exec(s.trim());
  if (!m) throw new Error(`not a time under a minute: ${s}`);
  return Number(m[1]);
};

/** The header once the panel has stopped sliding: from 1100px up an open panel takes its column, so the header
 *  ends where the panel begins; below, the panel lies over the chat and the header keeps the window's width. */
async function settled(page: Page, open: boolean, width: number) {
  // The grid's column slides (0.25s), and the header and the panel move together, so the header's right edge always
  // equals the panel's left edge and says nothing about the slide being over. A slide the resize starts is also only
  // pending until the next frame and holds its start value until then, so two reads 80ms apart could agree before it
  // began. Each read therefore waits two frames, and the motion is over when neither the window's columns nor the
  // panel have a transition running or pending and two reads of the header, the panel and the controls agree.
  const read = () =>
    page.evaluate(async () => {
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const moving = [".window", '[data-testid="details"]'].some((sel) => document.querySelector(sel)!.getAnimations().some((a) => a.pending || a.playState === "running"));
      const boxes = ["header", "details", "session-terminal-toggle", "model-pill", "panel-button"].map((id) => document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().toJSON());
      return { moving, boxes };
    });
  await expect
    .poll(async () => {
      const a = await read();
      const b = await read();
      const [h, d] = b.boxes;
      return !a.moving && !b.moving && JSON.stringify(a.boxes) === JSON.stringify(b.boxes) && Math.round(h.right) === (open && width >= 1100 ? Math.round(d.left) : width);
    })
    .toBe(true);
  return (await page.getByTestId("header").boundingBox())!;
}

test("the session header never overlaps or covers a control, 900 to 1440px, panel open and closed", async ({ page }) => {
  await session(page, "/subagents hold");
  await expect(page.getByTestId("subagent-row").nth(0)).toHaveAttribute("data-state", "done");
  const btn = page.getByTestId("panel-button");
  for (const open of [false, true]) {
    for (const width of [900, 1100, 1280, 1440]) {
      await page.setViewportSize({ width, height: 800 });
      if ((await btn.getAttribute("aria-pressed")) !== String(open)) await btn.click();
      await expect(btn).toHaveAttribute("aria-pressed", String(open));
      const head = await settled(page, open, width);
      const where = `${width}px, panel ${open ? "open" : "closed"}`;
      // left to right: the title, the path, the status, then the terminal toggle, the model control, the panel button
      // (the path's box is the line holding the folder and the agent: it ellipsizes as one)
      const ids = ["session-title", "session-path", "session-status", "session-terminal-toggle", "model-pill", "panel-button"];
      const rects = await page.evaluate(
        (ids) => ids.map((id) => (id === "session-path" ? document.querySelector('[data-testid="session-cwd"]')!.parentElement! : document.querySelector(`[data-testid="${id}"]`)!).getBoundingClientRect().toJSON()),
        ids,
      );
      for (let i = 1; i < rects.length; i++) expect(rects[i].left, `${ids[i]} after ${ids[i - 1]} at ${where}`).toBeGreaterThanOrEqual(rects[i - 1].right - 0.5);
      // the controls are whole and inside the header (not under the panel), the model's name is not cut
      for (const r of rects.slice(3)) expect(r.right, where).toBeLessThanOrEqual(head.x + head.width + 0.5);
      expect(Math.round(rects[3].width), where).toBe(24);
      expect(Math.round(rects[5].width), where).toBe(26);
      for (const id of ["model-pill", "model-label"])
        expect(await page.getByTestId(id).evaluate((el) => el.scrollWidth <= el.clientWidth), `${id} whole at ${where}`).toBe(true);
      // what is at each control's centre is that control (under 1100px the open panel slides over the whole chat
      // column, header included, as for a bot's chat: nothing of the header is on screen to cover there)
      if (open && width < 1100) continue;
      for (const [i, id] of [[3, "session-terminal-toggle"], [4, "model-pill"], [5, "panel-button"]] as const) {
        const r = rects[i];
        const hit = await page.evaluate(([id, x, y]) => !!document.elementFromPoint(x as number, y as number)?.closest(`[data-testid="${id}"]`), [id, r.left + r.width / 2, r.top + r.height / 2] as const);
        expect(hit, `${id} at ${where}`).toBe(true);
      }
    }
  }
});

test("the chat's card and the session's Plans read the same run the same way at the same moment", async ({ page }) => {
  await session(page, "/subagents hold");
  const sent = Date.now();
  const card = page.getByTestId("fanout-card");
  await expect(card.getByTestId("subagent-row").nth(0)).toHaveAttribute("data-state", "done");
  // the agent's record of this run, as the bridge reads it at this moment: the first handed back, the second out
  await mock("mock.sessionRun", { ago: (Date.now() - sent) / 1000, hold: true });
  await page.getByTestId("panel-button").click();
  const box = page.getByTestId("run-graph-box");
  await expect(box.locator("[data-testid=run-node]")).toHaveCount(2);
  await expect(box).toHaveAttribute("data-state", "running");
  await expect(card).toHaveAttribute("data-state", "running");
  expect(await box.locator("[data-testid=run-node]").evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).toEqual(
    await card.getByTestId("subagent-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-state"))),
  );
  await expect(box.getByTestId("run-progress")).toContainText("1 of 2 done");
  await expect(card.getByTestId("fanout-summary")).toContainText("1 of 2 done");
  // the finished one took the same time in both places
  const rowT = secs(await card.getByTestId("subagent-row").nth(0).getByTestId("subagent-time").innerText());
  await expect(box.locator("[data-testid=run-node]").nth(0).getByTestId("node-status")).toContainText(`${rowT}s`);
  // and the run's time in Plans is the card's, within the second the two clocks tick apart
  const planT = secs((await box.getByTestId("run-plan-time").innerText()).replace(/^\s*·\s*/, ""));
  const cardT = secs((await card.getByTestId("fanout-summary").innerText()).split(" · ").pop()!);
  expect(Math.abs(planT - cardT)).toBeLessThanOrEqual(1);
});

test("a card's time is the fan-out's and never less than its longest row; a running row counts from its own start", async ({ page }) => {
  await session(page, "/subagents hold");
  const card = page.getByTestId("fanout-card");
  const rows = card.getByTestId("subagent-row");
  await expect(rows.nth(0)).toHaveAttribute("data-state", "done");
  const read = async () => ({
    card: secs((await card.getByTestId("fanout-summary").innerText()).split(" · ").pop()!),
    rows: await rows.getByTestId("subagent-time").evaluateAll((els) => els.map((e) => e.textContent ?? "")),
  });
  for (let i = 0; i < 3; i++) {
    const r = await read();
    const t = r.rows.map(secs);
    // the done row took 3.7s by the agent's own count: the card says at least that
    expect(t[0]).toBe(3);
    for (const x of t) expect(r.card).toBeGreaterThanOrEqual(x);
    await page.waitForTimeout(1100);
  }
  // the running row counts on from its own first event: it moved while we watched
  const later = secs((await rows.nth(1).getByTestId("subagent-time").innerText()));
  expect(later).toBeGreaterThanOrEqual(2);
  // finished: the card's time still covers its longest row
  await page.getByTestId("composer").focus();
  await page.keyboard.press("Escape");
  await expect(card).toHaveAttribute("data-state", "done");
  const end = await read();
  for (const x of end.rows.map(secs)) expect(end.card).toBeGreaterThanOrEqual(x);
});

test("shots: a session's subagents, the subagent's ask, and its Plans", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await session(page, "/subagents hold");
  const sent = Date.now();
  await expect(page.getByTestId("subagent-row").nth(0)).toHaveAttribute("data-state", "done");
  await page.mouse.move(900, 790);
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "B1-session-subagents-live.png") });
  await page.getByTestId("subagent-row").nth(0).getByTestId("subagent-open").click();
  await page.screenshot({ path: join(SHOTS, "B2-subagent-opened.png") });
  await mock("mock.sessionRun", { ago: (Date.now() - sent) / 1000, hold: true });
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("run-graph-box")).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "B3-session-plans.png") });
  await page.getByTestId("panel-button").click();
  // Esc is the agent's interrupt
  await page.getByTestId("composer").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("/subask");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-subagent")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "B4-subagent-ask.png") });
});
