// A background subagent's approval that comes AFTER its turn ended (Claude Code 2.1.322, the event order of
// src-tauri/tests/fixtures/real/claude-13-late-ask.jsonl, mock host `/lateask`): the card is live with its three
// buttons, the session header says "Needs you", the sidebar row turns to the waiting state and the needs strip counts
// it; answering it sends the answer to the agent with no turn running, the card settles, and the subagent's row ends
// with its answer. With OMHER_SHOTS=<dir> it also writes orch-late-ask-<tag>-{dark,light}.png (OMHER_SHOT_TAG,
// default "after") of the live card.
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
    ws.send(JSON.stringify({ id: "la1", op, ...params }));
  });
  ws.close();
}

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function lateAsk(page: Page, theme: "dark" | "light", shot = false) {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/web-app";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // staged shots never show a bot named after the product
  await mock("bots.rename", { bot: "default", name: "Mira" });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/lateask");
  await page.keyboard.press("Enter");
  // the turn ends first ("started", Ready) with the subagent still out in the background
  // (it reads "1 still running in the background" until the subagent asks, then "1 waiting in the background")
  await expect(page.getByTestId("session-background")).toHaveText(/^1 (still running|waiting) in the background$/);
  // the subagent's ask has come (as a live card, or as the closed line omher 0.2.5 drew)
  await expect(page.locator("[data-testid=card-approval], [data-testid=card-line]").filter({ hasText: "echo gamma > c.txt" })).toBeVisible();
  if (shot && SHOTS) {
    // taken before any assertion on the card, so the same spec on the unfixed tree writes the before shots
    mkdirSync(SHOTS, { recursive: true });
    await page.mouse.move(640, 700);
    await page.screenshot({ path: join(SHOTS, `orch-late-ask-${TAG}-${theme}.png`), animations: "disabled" });
  }
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  return card;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of SHOTS ? (["dark", "light"] as const) : (["dark"] as const)) {
  test(`a background subagent's ask after the turn ended reaches the person and the answer reaches the agent (${theme})`, async ({ page }) => {
    const card = await lateAsk(page, theme, true);
    const row = page.locator("[data-testid=session-list] .ss-row").first();
    // no turn runs: the composer offers Send, the turn's activity is over
    await expect(page.getByTestId("send")).toBeVisible();
    await expect(card.getByTestId("card-subagent")).toHaveText("Subagent Write gamma to c.txt asks");
    await expect(card.locator(".card-cmd")).toHaveText("echo gamma > c.txt");
    await expect(card.locator(".card-btn")).toHaveText(["Deny", "Allow once", "Allow for session"]);
    await expect(page.getByTestId("session-status")).toHaveText("Needs you");
    await expect(row).toHaveAttribute("data-needs-you", "true");
    await expect(row.getByTestId("needs")).toBeVisible();
    await expect(page.getByTestId("subagent-row")).toHaveAttribute("data-state", "waiting");
    // looking elsewhere, the needs strip counts it
    await page.getByTestId("bot-friren").click();
    await expect(page.getByTestId("needs-strip")).toContainText("1 needs you");
    await row.click();
    await page.getByTestId("card-approval").locator(".card-btn", { hasText: "Allow once" }).click();
    // the answer went to the agent with no turn running
    const approve = (await calls(page)).filter((c) => c.input?.kind === "approve");
    expect(approve.map((c) => c.input?.choice)).toEqual(["once"]);
    // the card settles; the subagent runs on and hands back; the session is Ready again
    await expect(page.getByTestId("card-line").filter({ hasText: "echo gamma > c.txt" })).toContainText("Allowed once");
    await expect(page.getByTestId("subagent-row")).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("subagent-row").getByTestId("subagent-line")).toHaveText("WROTE");
    await expect(page.getByTestId("session-background")).toHaveCount(0);
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await expect(row).not.toHaveAttribute("data-needs-you", "true");
  });
}

test("a late ask reads as not answered once its session's program has gone", async ({ page }) => {
  await lateAsk(page, "dark");
  await expect(page.getByTestId("session-status")).toHaveText("Needs you");
  // the person sends something else and the program dies (mock `/die`): nobody is left to take the answer
  await page.getByTestId("composer").fill("/die");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-line").filter({ hasText: "echo gamma > c.txt" })).toContainText("Not answered");
  await expect(page.getByTestId("card-approval")).toHaveCount(0);
  await expect(page.getByTestId("session-status")).not.toHaveText("Needs you");
});
