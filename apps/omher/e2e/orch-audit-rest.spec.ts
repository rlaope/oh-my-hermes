// The four audit findings left open by the orchestration check (AUDIT.md O5, O11, O13, O15), as a person sees them in a
// SESSIONS chat. The mock host emits what the adapters emitted for the real recordings
// (src-tauri/tests/fixtures/real/omo-12-retry.jsonl, codex-12-late-step*.jsonl) and the mock bridge returns what
// CliRuns read from a real OmO 5.1.56 session's records. With OMHER_SHOTS=<dir> each test also writes its shot
// (`orch-audit-<what>-<OMHER_SHOT_TAG>-<theme>.png`), taken before its first assertion so the old tree writes the
// before shots too. omher only shows what the agent does: nothing here picks a mode or steers a subagent.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

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

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function session(page: Page, agent: string, theme: string, first?: string, globals: Record<string, unknown> = {}) {
  await page.addInitScript(
    ([t, g]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.removeItem("omher.sessions.recent");
      Object.assign(window, { __omherPickFolder: "/Users/you/code/omher", __omherMockAgents: ["claude", "codex", "omo", "omh"], ...(g as object) });
    },
    [theme, globals] as const,
  );
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  if (first !== undefined) {
    await page.getByTestId("composer").fill(first);
    await page.keyboard.press("Enter");
  }
}

async function shot(page: Page, what: string, theme: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.mouse.move(1270, 10);
  await page.screenshot({ path: join(SHOTS, `orch-audit-${what}-${TAG}-${theme}.png`), animations: "disabled" });
}

const themes = SHOTS ? (["dark", "light"] as const) : (["dark"] as const);

for (const theme of themes) {
  test(`O5 an OmO retry is one turn that fails once with OmO's reason, never the raw reply (${theme})`, async ({ page }) => {
    await session(page, "omo", theme, "/retry");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await page.waitForTimeout(300);
    await shot(page, "retry", theme);
    await expect(page.getByTestId("activity")).toHaveCount(1);
    const failed = page.getByTestId("activity");
    await expect(failed).toHaveAttribute("data-state", "error");
    await expect(failed.getByTestId("activity-text")).toContainText("Anthropic rejected this conversation's request format");
    await expect(failed.getByTestId("activity-text")).not.toContainText('{"type"');
    // the line is cut to the row; its whole reason is on hover
    await expect(failed.getByTestId("activity-text")).toHaveAttribute("title", /Run \/compact or start a new session to continue/);
  });

  test(`O5 while OmO retries, the live line says which try (${theme})`, async ({ page }) => {
    await session(page, "omo", theme, "/retry hold");
    await expect(page.getByTestId("activity-text")).toHaveText("Retrying 1 of 5");
    await expect(page.getByTestId("activity")).toHaveCount(1);
  });

  test(`O11 a command Stop cut short reads as stopped, then as finished late (${theme})`, async ({ page }) => {
    await session(page, "codex", theme, "/stoplate");
    await expect(page.getByTestId("activity-text")).toContainText("sleep 40; echo late");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    const act = page.getByTestId("activity").last();
    await act.getByTestId("activity-toggle").click();
    const step = act.getByTestId("activity-step");
    // (the mock's late end comes 0.6 s after Stop; the shot shows the row once it has)
    await page.waitForTimeout(1200);
    await shot(page, "stopped", theme);
    await expect(step).toHaveAttribute("data-ok", "stopped");
    // Codex says 37 s later that the command finished: the same row says it kept running and how long it ran
    await expect(step).toHaveAttribute("data-late", "done");
    await expect(step.getByTestId("activity-step-time")).toHaveText("Stopped · kept running, finished after 39s");
    await expect(act).toHaveAttribute("data-state", "interrupted");
    await expect(page.getByTestId("activity")).toHaveCount(1);
  });

  test(`O13 Codex running its own config with no approvals says so where the mode is (${theme})`, async ({ page }) => {
    await session(page, "codex", theme, undefined, { __omherMockCodexUnguarded: true });
    await page.getByTestId("composer").fill("/status");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    const mode = page.getByTestId("session-mode");
    await shot(page, "noapproval", theme);
    await expect(mode).toHaveText("No approvals · full disk access");
    await expect(mode).toHaveAttribute("data-own", "unguarded");
    await expect(mode).toHaveAttribute("title", "No approvals · full disk access · from Codex's own config");
    // quiet: 12-13px text, no box or fill
    const look = await mode.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { size: parseFloat(cs.fontSize), bg: cs.backgroundColor, border: cs.borderTopWidth };
    });
    expect(look.size).toBeGreaterThanOrEqual(12);
    expect(look.size).toBeLessThanOrEqual(13);
    expect(look.bg).toBe("rgba(0, 0, 0, 0)");
    expect(look.border).toBe("0px");
    // whole, never cut with an ellipsis
    const name = mode.locator(".ss-pick-n");
    expect(await name.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    // the menu says where it comes from, and still offers only omher's own modes
    await mode.click();
    await expect(page.getByTestId("session-mode-own")).toHaveText("No approvals · full disk access · from Codex's own config");
    await expect(page.getByTestId("session-mode-opt")).toHaveText([/^Read-only/, /^Ask/, /^Auto in folder/]);
    await page.locator('[data-testid=session-mode-opt][data-mode="ask"]').click();
    await expect(mode).toHaveText("Ask");
    await expect(mode).not.toHaveAttribute("data-own", /.+/);
    expect((await calls(page)).filter((c) => c.input?.kind === "mode").map((c) => c.input?.mode)).toEqual(["ask"]);
  });

  test(`O13 a Codex whose own config still asks keeps "Agent's own" (${theme})`, async ({ page }) => {
    await session(page, "codex", theme, "/status");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await expect(page.getByTestId("session-mode")).toHaveText("Agent's own");
  });

  test(`O15 an OmO session's subagents show as its run in Plans (${theme})`, async ({ page }) => {
    await session(page, "omo", theme, "/subagents");
    await expect(page.getByTestId("fanout-card")).toHaveAttribute("data-state", "done");
    // OmO 5.1.56 wrote its records: the session's own run
    await mock("mock.sessionRun", { agent: "omo" });
    await page.getByTestId("panel-button").click();
    const panel = page.getByTestId("panel-runs");
    await expect(panel).toBeVisible();
    await page.waitForTimeout(400);
    await shot(page, "omo-plans", theme);
    const box = panel.getByTestId("run-graph-box");
    await expect(box).toHaveAttribute("data-run", "omo:01a1ce7b-1c30-7e45-8913-aa00b3b32296");
    await expect(box.locator("[data-testid=run-node]")).toHaveCount(2);
    await expect(box.getByTestId("node-title")).toHaveText(["Read a.txt first line", "Count lines of b.txt"]);
  });
}
