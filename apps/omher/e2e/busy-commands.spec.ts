// A slash command typed in a bot's chat while the bot answers follows Claude Code's mid-turn rule (2.1.332): /usage
// and /status run at once beside the turn (chat.command) and their answer shows above the running answer; a bare
// /model opens the header's model picker, which says a pick applies from the next turn; any other command waits in
// the steer queue, and its ↵ stops the turn and sends it first. Shots (dark/light, en/ko, 900x600): OMHER_SHOTS=<dir>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const out = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out.result;
}
const calls = async (op: string) => ((await mock("mock.calls")).calls as { op: string; params: any }[]).filter((c) => c.op === op);

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.manual", { bot: "kami" });
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
});

async function running(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await say(page, "Refactor the gateway retry code");
  await expect(page.getByTestId("stop")).toBeVisible();
}
async function say(page: Page, text: string) {
  const box = page.getByTestId("composer");
  await box.fill(text);
  await box.press("Enter"); // never Escape: during a turn it stops the answer
}

test("/usage mid-answer runs at once: its answer shows, nothing waits, the answer keeps running", async ({ page }) => {
  await running(page);
  await say(page, "/usage");
  await expect.poll(async () => (await calls("chat.command")).map((c) => c.params)).toEqual([{ bot: "kami", text: "/usage" }]);
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "Session tokens: 1,234 in" })).toBeVisible();
  await expect(page.getByTestId("command-line")).toHaveText("/usage");
  // no answer of the turn: no reply quote on it, and the typing dots go on below it
  await expect(page.getByTestId("bubble-quote")).toHaveCount(0);
  await expect(page.locator(".row-typing")).toBeVisible();
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(0);
  expect(await calls("chat.interrupt")).toEqual([]);
  expect((await calls("chat.send")).map((c) => c.params.text)).not.toContain("/usage");
  await expect(page.getByTestId("stop")).toBeVisible();
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, "usage-mid-turn.png") });
  }
});

test("/status mid-answer runs at once too", async ({ page }) => {
  await running(page);
  await say(page, "/status");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "Model: sonnet" })).toBeVisible();
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(0);
});

test("a bare /model mid-answer opens the model picker, which says the pick applies from the next turn", async ({ page }) => {
  await running(page);
  await say(page, "/model");
  const pop = page.getByTestId("model-pop");
  await expect(pop).toBeVisible();
  await expect(pop).toContainText(/next turn/i);
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(0);
  expect(await calls("chat.command")).toEqual([]);
  await page.waitForTimeout(600);
  await expect(pop).toBeVisible(); // stays open: the composer's Enter does not close it
  if (SHOTS) await page.screenshot({ path: join(SHOTS, "model-mid-turn.png") });
});

test("/compress mid-answer waits; its ↵ stops the answer and sends it first", async ({ page }) => {
  await running(page);
  await say(page, "/compress");
  const row = page.locator("[data-testid=bubble-user][data-held]", { hasText: "/compress" });
  await expect(row).toBeVisible();
  expect(await calls("chat.command")).toEqual([]);
  await row.getByTestId("queue-mark").click();
  await expect.poll(async () => (await calls("chat.interrupt")).length).toBe(1);
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params.text).slice(-1)).toEqual(["/compress"]);
});
