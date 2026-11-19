// omher's Slack briefing: after the bridge set it up (`brief.ready`), the bot's chat shows one gray line, once, whose
// Turn off pauses that job through the bot's own cron.manage; its answers carry a "Brief" line (not "Watch"), the
// Automations row says when it speaks ("When something needs you") instead of "every 15m", and the app never adds a
// job for it itself (no automations.add).
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "u1") res(msg);
    };
    ws.send(JSON.stringify({ id: "u1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
type Call = { op: string; params: Record<string, unknown> };
const calls = async (prefix: string): Promise<Call[]> =>
  ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op.startsWith(prefix));

async function open(page: Page) {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("brief-init")) return;
    sessionStorage.setItem("brief-init", "1");
    localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren"]));
    localStorage.removeItem("omher.briefNoticed");
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("one notice after the briefing is set up; Turn off pauses that job", async ({ page }) => {
  await open(page);
  const { id } = await mock("mock.brief", { bot: "kami" });
  const notice = page.getByTestId("brief-notice");
  await expect(notice).toHaveCount(1);
  await expect(notice).toContainText("will brief you here when something in Slack needs you");
  await expect(page.getByTestId("brief-turn-off")).toBeEnabled();
  await page.getByTestId("brief-turn-off").click();
  await expect(page.getByTestId("brief-turn-off")).toHaveText("Turned off");
  const paused = await calls("automations.pause");
  expect(paused.map((c) => c.params)).toEqual([expect.objectContaining({ bot: "kami", job: id })]);
  // a second brief.ready for the same bot (a later bridge run) draws nothing new, also after a reload
  await mock("mock.emit", { events: [{ event: "brief.ready", bot: "kami", owner_name: "Hope" }] });
  await expect(notice).toHaveCount(1);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.emit", { events: [{ event: "brief.ready", bot: "kami", owner_name: "Hope" }] });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("brief-notice")).toHaveCount(0);
  expect(await calls("automations.add")).toEqual([]);
});

test("a brief answer's line says Brief and keeps Not useful", async ({ page }) => {
  await open(page);
  await mock("mock.watchRun", { bot: "kami", name: "omher-brief", kind: "hit", text: "Bob asked about the deploy and is waiting." });
  const line = page.getByTestId("watch-line").last();
  await expect(line).toContainText("Brief · omher-brief");
  await expect(line.getByTestId("watch-not-useful")).toBeVisible();
  expect(await calls("automations.add")).toEqual([]);
});

test("Automations shows the briefing by when it speaks, not its interval", async ({ page }) => {
  await open(page);
  const { id } = await mock("mock.brief", { bot: "kami" });
  await page.getByTestId("nav-automations").click();
  const row = page.getByTestId(`auto-row-${id}`);
  await expect(row).toBeVisible();
  await expect(row.getByTestId("watch-tag")).toHaveText("Brief");
  await expect(page.getByTestId(`auto-sched-${id}`)).toHaveText("When something needs you");
  await expect(row).not.toContainText("every 15");
  expect(await calls("automations.add")).toEqual([]);
});
