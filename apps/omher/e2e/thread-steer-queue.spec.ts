// Steer queue in a thread: a message typed in a thread while its turn runs is held like the main chat's (a bubble
// with the ↵ mark, never "Not sent · a turn is running"), goes out after that turn with `chat.send {session, queued}`,
// and Steer hands it to that thread's running turn (`chat.steer {session}`). Main-chat cases: steer-queue.spec.ts.
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
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
type Call = { op: string; params: Record<string, any> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);

/** Kami with one thread, its turns driven by hand; the thread is open and its first turn runs. */
async function runningThread(page: Page): Promise<string> {
  await mock("mock.reset");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "Steer neighbour", cwd: "/work/steer", ago: 1 }] });
  const id = threads[0] as string;
  await page.reload();
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
  await say(page, "first running task");
  await expect(page.getByTestId("stop")).toBeVisible();
  return id;
}
async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}

test("a follow-up typed during a thread's turn is held with ↵ and goes out after turn.end, never an error", async ({ page }) => {
  const id = await runningThread(page);
  await say(page, "keep the old timeout");
  const b = page.locator("[data-testid=bubble-user][data-held]", { hasText: "keep the old timeout" });
  await expect(b).toBeVisible();
  await expect(b.getByTestId("queue-mark")).toHaveText("↵");
  await expect(b.getByTestId("bubble-held")).toHaveText("Waiting");
  await expect(b.locator(".msg-err")).toHaveCount(0);
  // held in omher: only the first message went to the thread
  expect((await calls("chat.send")).map((c) => c.params.text)).toEqual(["first running task"]);
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: id, outcome: "done" }] });
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params)).toEqual([
    { bot: "kami", session: id, text: "first running task" },
    { bot: "kami", session: id, text: "keep the old timeout", queued: true },
  ]);
  const row = page.getByTestId("bubble-user").filter({ hasText: "keep the old timeout" });
  await expect(row).not.toHaveAttribute("data-held", /.*/);
  await expect(row.locator(".msg-err")).toHaveCount(0);
  expect(await calls("chat.steer")).toEqual([]);
});

test("Steer in a thread goes to that thread's running turn (chat.steer with its session)", async ({ page }) => {
  const id = await runningThread(page);
  await say(page, "also check the retry policy");
  const b = page.locator("[data-testid=bubble-user][data-held]", { hasText: "also check the retry policy" });
  await b.getByTestId("queue-mark").click();
  await page.getByTestId("queue-steer").click();
  await expect.poll(async () => (await calls("chat.steer")).map((c) => c.params)).toEqual([{ bot: "kami", session: id, text: "also check the retry policy" }]);
  expect((await mock("mock.steers")).steers).toEqual([{ bot: "kami", session: id, text: "also check the retry policy" }]);
  const row = page.getByTestId("bubble-user").filter({ hasText: "also check the retry policy" });
  await expect(row.getByTestId("queue-mark")).toHaveCount(0);
  await expect(row.locator(".msg-err")).toHaveCount(0);
  // steered in, never sent again as a message after the turn
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: id, outcome: "done" }] });
  await page.waitForTimeout(400);
  expect((await calls("chat.send")).map((c) => c.params.text)).toEqual(["first running task"]);
});

test("Send now in a thread stops that thread's turn (chat.interrupt with its session), then sends it first", async ({ page }) => {
  const id = await runningThread(page);
  await say(page, "b goes first");
  const b = page.locator("[data-testid=bubble-user][data-held]", { hasText: "b goes first" });
  await b.getByTestId("queue-mark").click();
  await page.getByTestId("queue-now").click();
  await expect.poll(async () => (await calls("chat.interrupt")).map((c) => c.params)).toEqual([{ bot: "kami", session: id }]);
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params.text)).toEqual(["first running task", "b goes first"]);
});
