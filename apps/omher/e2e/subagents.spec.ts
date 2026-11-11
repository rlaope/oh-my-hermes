// The chat's fan-out card: one per delegate_task, one row per subagent, updating in place from Hermes' subagent
// events (mock `/delegate` sends them in the order the real kami turn did), on after its turn ends; done it folds
// to "Ran 2 subagents · …". The run name opens that run in Plans. Read-only.
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
      if (msg.id === "cs1") res(msg);
    };
    ws.send(JSON.stringify({ id: "cs1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function send(page: Page, text: string) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("composer").fill(text);
  await page.keyboard.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("/delegate: one card, one row per subagent, live then done after the turn ended", async ({ page }) => {
  await send(page, "/delegate two lookups");
  const card = page.getByTestId("fanout-card");
  await expect(card).toHaveCount(1);
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(card.getByTestId("fanout-summary")).toHaveText(/^2 subagents running · 0 of 2 · \d+s$/);
  const rows = card.getByTestId("subagent-row");
  await expect(rows).toHaveCount(2);
  // each row: the model's vendor mark, the goal in a few words, the state, the current step, the time
  await expect(rows.nth(0).getByTestId("subagent-goal")).toHaveText("Doctor check for the Codex pack");
  await expect(rows.nth(0).locator("[data-mark]")).toHaveAttribute("data-mark", "openai");
  await expect(rows.nth(1).locator("[data-mark]")).toHaveAttribute("data-mark", "claude");
  await expect(rows.nth(1).getByTestId("subagent-line")).toHaveText("pnpm test --run");
  await expect(rows.nth(1).getByTestId("subagent-state")).toHaveText("running");
  await expect(rows.nth(0).getByTestId("subagent-time")).toHaveText(/^\d+s$/);
  // the parent's turn ends first (background fan-out); the card keeps going
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
  await expect(card).toHaveAttribute("data-state", "running");
  // the first returns: its result line replaces the step; the count moves in place
  await expect(rows.nth(0)).toHaveAttribute("data-state", "done");
  await expect(rows.nth(0).getByTestId("subagent-line")).toHaveText("The Codex pack is current (12 skills).");
  await expect(card.getByTestId("fanout-summary")).toHaveText(/ · 1 of 2 · /);
  // both done: the card folds to its summary
  await expect(card).toHaveAttribute("data-state", "done");
  await expect(card.getByTestId("fanout-summary")).toHaveText(/^Ran 2 subagents · \d+s$/);
  await expect(rows.nth(1).getByTestId("subagent-line")).toHaveText("All 6 probes pass on the branch.");
  await expect(page.getByTestId("fanout-card")).toHaveCount(1);
  // read-only: no stop, steer or retry control on the card
  expect(await card.getByRole("button", { name: /stop|steer|retry|cancel|assign/i }).count()).toBe(0);
});

test("a failed subagent reads failed in red, and the card says how many failed", async ({ page }) => {
  await send(page, "/delegate fail");
  const card = page.getByTestId("fanout-card");
  await expect(card).toHaveAttribute("data-state", "done");
  await expect(card.getByTestId("fanout-summary")).toHaveText(/^Ran 2 subagents · \d+s · 1 failed$/);
  const bad = card.locator('[data-testid="subagent-row"][data-state="failed"]');
  await expect(bad.getByTestId("subagent-state")).toHaveText("failed");
  await expect(bad.getByTestId("subagent-line")).toHaveText("Two probes timed out.");
  const [red, danger] = await bad.getByTestId("subagent-state").evaluate((e) => {
    const probe = document.createElement("i");
    probe.style.color = "var(--danger)";
    document.body.append(probe);
    const want = getComputedStyle(probe).color;
    probe.remove();
    return [getComputedStyle(e).color, want];
  });
  expect(red).toBe(danger);
});

test("the card's run name opens that run in Plans", async ({ page }) => {
  await send(page, "/delegate two lookups");
  const open = page.getByTestId("fanout-card").getByTestId("fanout-open");
  await expect(open).toHaveText("codex-coexist-live");
  // the panel opened by itself on this turn's fan-out; close it, then the card's link opens it on the run
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  await open.click();
  await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("run-graph-box")).toHaveAttribute("data-run", LIVE);
});

test("the words say subagents, never helpers, in every language", async ({ page }) => {
  for (const [lang, word] of [["en", "subagent"], ["ko", "서브에이전트"], ["ja", "サブエージェント"], ["zh", "子代理"]] as const) {
    await mock("mock.reset");
    await page.addInitScript((l) => localStorage.setItem("omher.lang", l), lang);
    await send(page, "/delegate two lookups");
    const card = page.getByTestId("fanout-card");
    await expect(card).toHaveAttribute("data-state", "done");
    await expect(card.getByTestId("fanout-summary")).toContainText(word);
    const act = page.getByTestId("activity").last();
    await act.getByTestId("activity-toggle").click();
    await expect(act.getByTestId("activity-dag").first()).toContainText(word);
    for (const bad of ["helper", "도우미", "ヘルパー", "助手"]) await expect(page.getByTestId("timeline")).not.toContainText(bad);
  }
});

test("dark and light: the card has no fill and 6px corners, its text is readable", async ({ page }) => {
  for (const theme of ["dark", "light"]) {
    await mock("mock.reset");
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await send(page, "/delegate two lookups");
    const card = page.getByTestId("fanout-card");
    await expect(card).toHaveAttribute("data-state", "done");
    const st = await card.evaluate((e) => {
      const cs = getComputedStyle(e);
      return { bg: cs.backgroundColor, img: cs.backgroundImage, r: cs.borderTopLeftRadius, fs: getComputedStyle(e.querySelector(".sa-goal")!).fontSize };
    });
    expect(st).toEqual({ bg: "rgba(0, 0, 0, 0)", img: "none", r: "6px", fs: "12px" });
  }
});

test("the chat stays at the bottom as the panel opens and the card grows after its turn; scrolling up lets go", async ({ page }) => {
  // a returning person (a tab picked before) in light: the panel opens by itself mid-turn and narrows the column
  await page.addInitScript(() => {
    localStorage.setItem("omher.panelPicked", "1");
    localStorage.setItem("omher.theme", "light");
    localStorage.removeItem("omher.resume");
  });
  await send(page, "/delegate two lookups");
  const card = page.getByTestId("fanout-card");
  await expect(card).toHaveAttribute("data-state", "done");
  await page.waitForTimeout(300);
  const gap = () => page.getByTestId("timeline").evaluate((el) => Math.round(el.scrollHeight - el.scrollTop - el.clientHeight));
  expect(await gap()).toBeLessThan(2);
  // both rows sit above the composer, uncovered
  const rows = await card.getByTestId("subagent-row").evaluateAll((els) =>
    els.map((e) => {
      const b = e.getBoundingClientRect();
      return document.elementFromPoint(b.left + 40, b.top + b.height / 2)?.closest('[data-testid="fanout-card"]') !== null;
    }),
  );
  expect(rows).toEqual([true, true]);
  // the person scrolls up: a later card update does not pull them down
  await page.getByTestId("composer").fill("/delegate again");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("fanout-card")).toHaveCount(2);
  // once the turn is over (its own messages are in), the person scrolls up while the subagents still work
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("fanout-card").last()).toHaveAttribute("data-state", "running");
  await page.getByTestId("timeline").hover();
  await page.mouse.wheel(0, -500);
  await expect.poll(gap).toBeGreaterThan(300);
  await expect(page.getByTestId("fanout-card").last()).toHaveAttribute("data-state", "done");
  expect(await gap()).toBeGreaterThan(300);
});
