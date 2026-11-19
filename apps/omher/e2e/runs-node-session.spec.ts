// A plan node's session as a chat between agents (harness lane): clicking a Hermes-subagent node or a Codex fanout
// node in the Plans graph opens its drawer, whose Session section is our own chat read-only: the parent's prompt and
// later steer as RIGHT bubbles (the person's bubble look) labelled with the parent's name; the child's words as LEFT
// bubbles with its harness mark as the face (a Hermes child also wears its model's mark); its commands as our step
// rows in order, each opening to its full input and result; its own child as our subagent row that opens in place
// (breadcrumb Kami › child › grandchild). The answer is the last left bubble. The chat's own subagent cards open the
// same view. Mock data: e2e/mock-bridge.mjs `runs.node_session`.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { motionDone } from "./motion";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const DEMO = "dag:20261110_091904_d4a1c7e2/docs-dark-mode";
const SHOTS = process.env.OMHER_SHOTS || process.env.OMHER_SHOTS_DIR || "";

/** A shot only when OMHER_SHOTS names a folder (CI and other machines take none). */
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name) });
}

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "ns1") res(msg);
    };
    ws.send(JSON.stringify({ id: "ns1", op, ...params }));
  });
  ws.close();
  return reply;
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.demo");
});

async function openFull(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("places").click();
  // the tabs slide in with the panel: press one once it has stopped
  await motionDone(page);
  await page.getByTestId("panel-tab-runs").click();
  await expect(page.getByTestId("run-graph-box")).toHaveAttribute("data-run", DEMO);
  await page.getByTestId("run-graph-box").getByTestId("run-node").first().waitFor();
  return page.getByTestId("run-graph-box");
}

const nodeOf = (root: Locator, id: string) => root.locator(`[data-testid="run-node"][data-node="${id}"]`);

async function openNode(page: Page, id: string) {
  const box = await openFull(page);
  await nodeOf(box, id).click();
  const chat = page.getByTestId("run-session").getByTestId("agent-chat");
  await expect(chat.getByTestId("agent-chat-timeline")).toBeVisible();
  return chat;
}

async function sides(chat: Locator) {
  return chat.getByTestId("agent-chat-timeline").evaluate((tl) =>
    [...tl.children].map((el) => {
      const t = el.getAttribute("data-testid") ?? "";
      if (t === "bubble-user") return "R";
      if (t === "agent-chat-said" || t === "agent-chat-answer") return "L";
      if (t === "agent-chat-steps") return `S${el.querySelectorAll("[data-testid=activity-step]").length}`;
      if (t === "agent-chat-child") return "C";
      return t;
    }),
  );
}

test("a Hermes subagent node opens as a chat: parent right, child left with Hermes + model marks, steps in order", async ({ page }) => {
  const chat = await openNode(page, "contrast");
  await expect(chat).toHaveAttribute("data-kind", "hermes");
  await expect(chat).toHaveAttribute("data-harness", "hermes");
  // the order of the chat: prompt, child's words, 2 steps, a steer, the delegate step, the grandchild, a step, answer
  expect(await sides(chat)).toEqual(["R", "L", "S2", "R", "S1", "C", "S1", "L"]);
  // the parent's bubbles are the person's own bubble look, right-aligned, labelled with the parent's name
  const right = chat.getByTestId("bubble-user");
  await expect(right.first()).toContainText("Check every text colour");
  await expect(right.first().getByTestId("bubble-from-name")).toHaveText("Kami");
  await expect(right.nth(1)).toContainText("Also check the code block colours.");
  const box = await chat.getByTestId("agent-chat-body").boundingBox();
  const rb = await right.first().locator(".b").boundingBox();
  expect(rb!.x + rb!.width).toBeGreaterThan(box!.x + box!.width - 30);
  // the child's face: Hermes's mark with its model's (DeepSeek) mark on the corner, never Claude Code's
  const face = chat.getByTestId("agent-chat-said").first().getByTestId("harness-face");
  await expect(face).toHaveAttribute("data-harness", "hermes");
  await expect(face).toHaveAttribute("data-model-mark", "deepseek");
  await expect(chat.locator('[data-harness="claude"]')).toHaveCount(0);
  // commands in order, one row each, opening to the full input and result
  const steps = chat.getByTestId("activity-step");
  await expect(steps.nth(0)).toContainText("docs/theme.css");
  await expect(steps.nth(1)).toContainText("node scripts/contrast.mjs docs/theme.css");
  await steps.nth(1).click();
  // a single shell command already reads in full on its "Ran" row: the opened box shows only the result
  await expect(chat.getByTestId("activity-step-input")).toHaveCount(0);
  // a Hermes tool's JSON result reads as its text: the two lines, not a JSON string with "\n" in it
  const result = chat.getByTestId("activity-step-result").first();
  expect(await result.textContent()).toContain("muted on bg (dark): 3.9:1  FAIL\nfg on bg (dark)");
  await expect(result).not.toContainText('"output"');
  // a token in a command shows masked, never in full
  await expect(chat).toContainText("sk-•••");
  // the answer is the last left bubble, markdown rendered; no thinking anywhere
  const answer = chat.getByTestId("agent-chat-answer");
  await expect(answer.locator("strong")).toHaveText("One pair fails AA:");
  await expect(chat).not.toContainText(/thinking/i);
  await page.getByTestId("run-session").scrollIntoViewIfNeeded();
  await shot(page, "harness-drawer-hermes.png");
  // Open as chat: the whole view, right/left bubbles
  await chat.getByTestId("agent-chat-full").click();
  await expect(page.getByTestId("run-session")).toHaveClass(/full/);
  await shot(page, "harness-agentchat-hermes.png");
  // its own child opens in place: breadcrumb Kami › Contrast check › Code block palette contrast
  await chat.getByTestId("agent-chat-child").click();
  await expect(chat.getByTestId("agent-chat-crumb-current")).toHaveText("Code block palette contrast");
  await expect(chat.getByTestId("agent-chat-trail")).toContainText("Kami");
  await expect(chat.getByTestId("agent-chat-trail")).toContainText("Contrast check");
  await expect(chat.getByTestId("agent-chat-answer")).toContainText("All 9 code colours pass AA");
  await expect(chat.getByTestId("bubble-from-name").first()).toHaveText("Contrast check");
  await expect(chat.getByTestId("agent-chat-said").or(chat.getByTestId("agent-chat-answer")).first().getByTestId("harness-face")).toHaveAttribute("data-model-mark", "zhipu");
  await chat.getByTestId("agent-chat-crumb").click();
  await expect(chat.getByTestId("agent-chat-crumb-current")).toHaveText("Contrast check");
});

test("a Codex fanout node opens as a chat with Codex's mark: prompt, commands in order, answer", async ({ page }) => {
  const chat = await openNode(page, "code-colors");
  await expect(chat).toHaveAttribute("data-kind", "codex");
  await expect(chat).toHaveAttribute("data-harness", "codex");
  expect(await sides(chat)).toEqual(["R", "S4", "L"]);
  await expect(chat.getByTestId("bubble-user")).toContainText("give code blocks a dark palette");
  await expect(chat.getByTestId("harness-face").first()).toHaveAttribute("data-harness", "codex");
  // a Codex session has no Hermes model badge
  await expect(chat.getByTestId("harness-model-mark")).toHaveCount(0);
  const steps = chat.getByTestId("activity-step");
  await expect(steps).toHaveCount(4);
  const lines = await steps.evaluateAll((els) => els.map((e) => e.querySelector(".v")?.textContent ?? ""));
  expect(lines).toEqual(['rg -n "pre code" docs/', expect.stringContaining("*** Update File: docs/theme.css"), "pnpm test --run", 'gh pr create --draft --title "docs: code block palette"']);
  await expect(chat.getByTestId("agent-chat-answer")).toContainText("Draft PR #2360 is open.");
  await page.getByTestId("run-session").scrollIntoViewIfNeeded();
  await shot(page, "harness-drawer-codex.png");
  await chat.getByTestId("agent-chat-full").click();
  await shot(page, "harness-agentchat-codex.png");
});

test("graph nodes keep one mark each from the registry: Codex and Claude Code lanes, Hermes children by model", async ({ page }) => {
  const box = await openFull(page);
  const marks = async (id: string) => nodeOf(box, id).getByTestId("node-mark").evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")}:${e.getAttribute("data-mark")}`));
  expect(await marks("contrast")).toEqual(["model:deepseek"]);
  expect(await marks("code-colors")).toEqual(["model:openai"]);
  expect(await marks("page-styles")).toEqual(["model:claude"]);
  expect(await nodeOf(box, "code-colors").getByTestId("node-facts").getAttribute("title")).toContain("via Codex");
  await shot(page, "harness-graph.png");
});

test("the chat's own subagent rows open the same chat view", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("composer").fill("/delegate two lookups");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("fanout-card");
  await expect(card.getByTestId("subagent-row")).toHaveCount(2);
  // each row: Hermes's mark, its model's mark beside it
  await expect(card.getByTestId("subagent-row").first().locator(".sa-mark")).toHaveAttribute("data-harness", "hermes");
  await card.getByTestId("subagent-chat").first().click();
  const chat = card.getByTestId("subagent-chat-view").getByTestId("agent-chat");
  await expect(chat.getByTestId("agent-chat-timeline")).toBeVisible();
  await expect(chat.getByTestId("bubble-user").first().getByTestId("bubble-from-name")).toHaveText("Kami");
  await expect(chat.getByTestId("agent-chat-answer")).toBeVisible();
});

test("the op validates and stays read-only", async () => {
  const bad = await mock("runs.node_session", { bot: "kami", ref: "hermes:../../etc/passwd" });
  expect(bad.ok).toBe(false);
  const none = await mock("runs.node_session", { bot: "kami", run: DEMO, node: "verify-pr" });
  expect(none.ok).toBe(true);
  expect(none.result).toMatchObject({ session: null, why: "no_cli_session", executor: "omp" });
});
