// SESSIONS chat controls on the mock host: the permission mode (per session, kept across a reload), reasoning
// effort next to the model, the agent's own `/` commands, the branch and context line, a message sent while a
// turn runs, and the model menu's search and provider groups.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string): Promise<{ calls?: { op: string; input?: Record<string, unknown> }[] }> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<string>((res) => {
    ws.onmessage = (m) => res(String(m.data));
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
  return JSON.parse(reply).result ?? {};
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

const inputs = (page: Page) =>
  page.evaluate(() =>
    ((window as unknown as { __omherSessionCalls?: { op: string; input?: Record<string, unknown> }[] }).__omherSessionCalls ?? [])
      .filter((c) => c.op === "chat.input")
      .map((c) => c.input!),
  );

async function running(page: Page, agent: "claude" | "codex" | "omo" = "claude", folder = "/Users/you/code/omher") {
  await page.addInitScript(
    ([f, a]) => {
      localStorage.removeItem("omher.sessions.recent");
      const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
      w.__omherPickFolder = f;
      w.__omherMockAgents = ["claude", "codex", "omo", "omh"];
      void a;
    },
    [folder, agent],
  );
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

test("Claude Code: the mode is a quiet label in the composer row; picking one sends Claude Code's own switch", async ({ page }) => {
  await running(page);
  const mode = page.getByTestId("session-mode");
  await expect(mode).toHaveText("Ask");
  await mode.click();
  const opts = page.getByTestId("session-mode-opt");
  await expect(opts).toHaveText([/^Ask/, /^Plan/, /^Accept edits/]);
  // never a mode that skips approvals
  await expect(page.getByTestId("session-mode-menu")).not.toContainText(/bypass|skip|danger/i);
  await opts.filter({ hasText: "Plan" }).click();
  await expect(mode).toHaveText("Plan");
  expect((await inputs(page)).filter((i) => i.kind === "mode")).toEqual([{ kind: "mode", mode: "plan" }]);
  // a borderless label, like the agent's
  const border = await mode.evaluate((el) => getComputedStyle(el).borderTopWidth);
  expect(border).toBe("0px");
});

test("the mode survives a reload: the restarted chat is set to it again", async ({ page }) => {
  await running(page);
  await page.getByTestId("session-mode").click();
  await page.getByTestId("session-mode-opt").filter({ hasText: "Accept edits" }).click();
  await expect(page.getByTestId("session-mode")).toHaveText("Accept edits");
  await page.waitForTimeout(700); // the resume snapshot is written a moment after a change
  await page.reload();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-mode")).toHaveText("Accept edits");
  expect((await inputs(page)).filter((i) => i.kind === "mode")).toEqual([{ kind: "mode", mode: "acceptEdits" }]);
});

test("Codex: read-only, ask and auto in the folder; its own setting shows as the agent's", async ({ page }) => {
  await running(page, "codex");
  const mode = page.getByTestId("session-mode");
  await expect(mode).toHaveText("Agent's own");
  await mode.click();
  await expect(page.getByTestId("session-mode-opt")).toHaveText([/^Read-only/, /^Ask/, /^Auto in folder/]);
  await expect(page.getByTestId("session-mode-menu")).toContainText("Applies from the next message");
  await page.getByTestId("session-mode-opt").filter({ hasText: "Read-only" }).click();
  await expect(mode).toHaveText("Read-only");
});

test("an agent without modes gets no mode control", async ({ page }) => {
  await running(page, "omo");
  await expect(page.getByTestId("session-agent-fixed")).toBeVisible();
  await expect(page.getByTestId("session-mode")).toHaveCount(0);
});

test("reasoning effort sits next to the model, with the agent's own levels", async ({ page }) => {
  await running(page);
  await expect(page.getByTestId("reasoning-label")).toHaveText("High");
  await page.getByTestId("model-pill").click();
  const seg = page.getByTestId("reasoning-seg");
  await expect(seg.getByRole("radio")).toHaveText(["Low", "Med", "High", "X-High", "Max"]);
  await seg.getByRole("radio", { name: "Low" }).click();
  await expect(page.getByTestId("reasoning-label")).toHaveText("Low");
  expect((await inputs(page)).filter((i) => i.kind === "effort")).toEqual([{ kind: "effort", effort: "low" }]);
  // "Applies to this session" stays
  await expect(page.getByTestId("model-pop")).toContainText("Applies to this session");
});

test("/ at the start of the box lists the agent's own commands; typing narrows; a pick fills the box", async ({ page }) => {
  await running(page);
  const box = page.getByTestId("composer");
  await box.fill("/");
  const picker = page.getByTestId("command-picker");
  await expect(picker).toBeVisible();
  // 65 reported, 50 shown, the rest by typing
  await expect(page.getByTestId("command-option")).toHaveCount(50);
  await expect(page.getByTestId("command-more")).toHaveText("15 more · keep typing");
  await expect(page.getByTestId("skill-hint")).toHaveCount(0);
  await box.fill("/comp");
  await expect(page.getByTestId("command-option").first()).toHaveAttribute("data-name", "compact");
  // a skill is marked apart from a command
  await box.fill("/archi");
  await expect(page.getByTestId("command-option").first()).toHaveAttribute("data-kind", "skill");
  await expect(page.getByTestId("command-option").first()).toContainText("skill");
  await box.fill("/comp");
  await page.keyboard.press("Enter");
  await expect(box).toHaveValue("/compact ");
  await expect(picker).toHaveCount(0);
  // Esc closes it; text in the middle of a message never opens it
  await box.fill("/");
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await box.fill("please /compact");
  await expect(picker).toHaveCount(0);
});

test("Codex skills come with their $ and only $ entries show on $", async ({ page }) => {
  await running(page, "codex");
  await page.getByTestId("composer").fill("$");
  await expect(page.getByTestId("command-option")).toHaveCount(1);
  await expect(page.getByTestId("command-option")).toContainText("$review");
});

test("the line under the box shows the branch and the context the agent counted", async ({ page }) => {
  await running(page);
  await expect(page.getByTestId("session-branch")).toHaveText("feat/session-controls");
  await expect(page.getByTestId("session-usage")).toHaveText(/^\d+k \/ 1M · \d+%$/);
  // a folder that is not a repository: no branch
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-codex").click();
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/notes"));
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-usage")).toBeVisible();
  await expect(page.getByTestId("session-branch")).toHaveCount(0);
});

test("a message sent while a turn runs waits, then the agent takes it; Stop still stops the turn", async ({ page }) => {
  await running(page);
  const box = page.getByTestId("composer");
  await box.fill("/slow");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  await box.fill("also check the changelog");
  await page.keyboard.press("Enter");
  const waiting = page.getByTestId("bubble-user").filter({ hasText: "also check the changelog" });
  await expect(waiting).toHaveAttribute("data-wait", "queued");
  await expect(waiting.getByTestId("bubble-queued")).toHaveText("Waiting");
  // Stop stops the running turn and drops what waited
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(waiting).toHaveAttribute("data-wait", "dropped");
  // a finished turn takes it: no mark left
  await box.fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  await box.fill("and then this");
  await page.keyboard.press("Enter");
  const next = page.getByTestId("bubble-user").filter({ hasText: "and then this" });
  await expect(next).toHaveAttribute("data-wait", "queued");
  await expect(next).not.toHaveAttribute("data-wait", /.+/, { timeout: 5000 });
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "You said: and then this" })).toBeVisible();
});

test("the model menu searches and groups by provider", async ({ page }) => {
  await running(page, "omo");
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await expect(pop.getByTestId("model-search")).toBeFocused();
  await expect(pop.getByTestId("model-group")).toHaveCount(2);
  await expect(pop.locator(".mp-g")).toHaveText(["anthropic", "opengateway"]);
  await pop.getByTestId("model-search").fill("gpt");
  await expect(pop.getByTestId("model-opt")).toHaveText(["GPT-6 (gateway)"]);
  await pop.getByTestId("model-search").fill("zzz");
  await expect(pop.getByTestId("model-empty")).toBeVisible();
  await expect(pop).toContainText("Applies to this session");
});
