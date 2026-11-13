// Three session defects found with real CLI turns (omher 0.2.6), on the mock host with the events the adapters emit
// for the recorded streams: a Codex session that closed in order shows no reason (its start-up config warning was
// shown as why it ended); Claude Code's plan-mode card asks in words and shows the plan as text (it was a cut JSON
// string); an edit Codex hands to its subagent opens to its diff (it had none). Streams: src-tauri/tests/fixtures/real
// claude-14-plan-*.jsonl and codex-15-sub-edit*.jsonl.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function session(page: Page, agent: "claude" | "codex", first: string) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/calc";
  });
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

test("a Codex session that closed in order says Ended, without its start-up warning as the reason", async ({ page }) => {
  await session(page, "codex", "/quit");
  const ended = page.getByTestId("session-ended");
  await expect(ended).toBeVisible();
  await expect(ended.locator(".ss-ended-t")).toHaveText("Ended");
  await expect(ended.locator(".ss-ended-t")).not.toHaveAttribute("title", /.+/);
  await expect(page.getByText("mcp_servers.playwright.type")).toHaveCount(0);
});

test("the plan-mode card asks in words and shows the plan as readable text", async ({ page }) => {
  await session(page, "claude", "/plan");
  const card = page.getByTestId("card-approval");
  await expect(card.locator(".card-title")).toHaveText("Start working on this plan?");
  // the plan as an answer reads: its heading, its two steps, inline code; no JSON and no command box
  const plan = card.getByTestId("card-plan");
  await expect(plan.locator("h1")).toHaveText("Plan: add mul(a, b) to calc.py");
  await expect(plan.locator("ol > li")).toHaveCount(2);
  await expect(plan.locator("code").first()).toHaveText("calc.py");
  await expect(card.locator(".card-cmd")).toHaveCount(0);
  await expect(card).not.toContainText('{"plan"');
  // whole, not cut to one line, and it scrolls inside the card when long
  await expect(plan).toContainText("assert mul(3, 4) == 12");
  const css = await plan.evaluate((el) => {
    const c = getComputedStyle(el);
    return { overflowY: c.overflowY, maxHeight: c.maxHeight, whiteSpace: c.whiteSpace, radius: c.borderRadius, font: c.fontSize };
  });
  expect(css).toEqual({ overflowY: "auto", maxHeight: "320px", whiteSpace: "normal", radius: "4px", font: "12.5px" });
  // what the CLI offers, in the card's order: Deny, then Allow once (no rule to keep for a plan)
  await expect(card.locator(".card-btn")).toHaveText(["Deny", "Allow once"]);
  await card.getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("card-line")).toContainText("Allowed once");
  await expect(page.getByTestId("card-line")).toContainText("Start working on this plan?");
});

test("an edit Codex hands to its subagent opens to the same diff a session's own edit shows", async ({ page }) => {
  await session(page, "codex", "/subedit");
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
  const row = page.getByTestId("subagent-row");
  await expect(row).toHaveAttribute("data-state", "done");
  await row.getByTestId("subagent-open").click();
  const steps = row.getByTestId("subagent-step");
  await expect(steps).toHaveText(["cat calc.py README.md", "README.md +2, calc.py +4"]);
  // the command is a plain line; the edit opens to its change per file
  await expect(row.getByTestId("diff-view")).toHaveCount(0);
  await steps.nth(1).click();
  await expect(steps.nth(1)).toHaveAttribute("aria-expanded", "true");
  const view = row.getByTestId("diff-view");
  await expect(view.getByTestId("diff-file")).toHaveCount(2);
  await expect(view.getByTestId("diff-file").nth(0)).toContainText("README.md");
  await expect(view.getByTestId("diff-file").nth(1).locator(".dv-l.add")).toHaveText(["", "", "def mul(a, b):", "    return a * b"]);
  await expect(view.getByTestId("diff-file").nth(1).locator(".dv-l.ctx")).toHaveText(["    return a - b"]);
  await steps.nth(1).click();
  await expect(row.getByTestId("diff-view")).toHaveCount(0);
});
