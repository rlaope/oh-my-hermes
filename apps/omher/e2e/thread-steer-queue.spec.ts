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

test("a follow-up whose steer the thread refuses is held with ↵ and goes out after turn.end, never an error", async ({ page }) => {
  const id = await runningThread(page); // resets the mock: refuse steers after it
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
  await say(page, "keep the old timeout");
  const b = page.locator("[data-testid=bubble-user][data-held]", { hasText: "keep the old timeout" });
  await expect(b).toBeVisible();
  await expect(b.getByTestId("queue-mark")).toHaveText("↵");
  await expect(b.locator(".msg-wait")).toHaveCount(0);
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
  expect((await calls("chat.steer")).map((c) => c.params)).toEqual([{ bot: "kami", session: id, text: "keep the old timeout" }]);
});

test("typed during a thread's turn it is steered into that turn at once (chat.steer with its session)", async ({ page }) => {
  const id = await runningThread(page);
  await say(page, "also check the retry policy");
  await expect.poll(async () => (await calls("chat.steer")).map((c) => c.params)).toEqual([{ bot: "kami", session: id, text: "also check the retry policy" }]);
  expect((await mock("mock.steers")).steers).toEqual([{ bot: "kami", session: id, text: "also check the retry policy" }]);
  const row = page.getByTestId("bubble-user").filter({ hasText: "also check the retry policy" });
  await expect(row.getByTestId("queue-mark")).toHaveCount(0);
  await expect(row.locator(".msg-err")).toHaveCount(0);
  await expect(row.getByTestId("bubble-read")).toBeVisible();
  // steered in, never sent again as a message after the turn
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: id, outcome: "done" }] });
  await page.waitForTimeout(400);
  expect((await calls("chat.send")).map((c) => c.params.text)).toEqual(["first running task"]);
});

test("a Steer the thread's bot refuses: the message waits and goes out after that thread's turn", async ({ page }) => {
  const id = await runningThread(page); // resets the mock: refuse steers after it
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
  await say(page, "b goes first");
  const b = page.locator("[data-testid=bubble-user][data-held]", { hasText: "b goes first" });
  await expect.poll(async () => (await calls("chat.steer")).length).toBe(1);
  await b.getByTestId("queue-mark").click();
  await expect.poll(async () => (await calls("chat.steer")).map((c) => c.params)).toEqual([
    { bot: "kami", session: id, text: "b goes first" },
    { bot: "kami", session: id, text: "b goes first" },
  ]);
  await expect(b).toBeVisible();
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: id, outcome: "done" }] });
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params.text)).toEqual(["first running task", "b goes first"]);
  expect((await calls("chat.interrupt")).length).toBe(0);
});

// x -> confirm on a thread that holds messages: they are dropped, never sent to the archived session (the archive
// ends its turn, and that turn's end must not drain them), and no blank chat stays behind. The main chat and another
// thread still drain theirs. Asserted on the request log the mock keeps, in order.
test("removing a thread that holds messages never sends them; the main chat and another thread still drain", async ({ page }) => {
  await mock("mock.reset");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", {
    bot: "kami",
    threads: [
      { title: "Removed", cwd: "/work/a", ago: 1 },
      { title: "Kept", cwd: "/work/b", ago: 2 },
    ],
  });
  const [a, b] = threads as string[];
  // held messages: Hermes refuses the steers, so each waits for its turn to end
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
  await page.reload();
  const open = async (id: string) => {
    await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
    await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", id);
  };
  const heldRow = (text: string) => page.locator("[data-testid=bubble-user][data-held]", { hasText: text });
  await open(b);
  await say(page, "B running");
  await expect(page.getByTestId("stop")).toBeVisible();
  await say(page, "B held");
  await page.getByTestId("bot-kami").click();
  await say(page, "main running");
  await expect(page.getByTestId("stop")).toBeVisible();
  await say(page, "main held");
  await open(a);
  await say(page, "first running task");
  await expect(page.getByTestId("stop")).toBeVisible();
  await say(page, "do not send after archive");
  await expect(heldRow("do not send after archive")).toBeVisible();

  const row = page.getByTestId(`thread-row-${a}`);
  await row.hover();
  await row.getByTestId("thread-x").click();
  await page.getByTestId("thread-confirm-remove").click();
  await expect(row).toHaveCount(0);
  await page.waitForTimeout(750);
  // the other thread's and the main chat's turns end: theirs go out, the removed thread's never
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: b, outcome: "done" }] });
  await mock("mock.endTurn", { bot: "kami" });
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params.text)).toEqual([
    "B running",
    "main running",
    "first running task",
    "B held",
    "main held",
  ]);
  await page.waitForTimeout(400);
  const log = ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === "thread.remove" || c.op === "chat.send");
  const removed = log.findIndex((c) => c.op === "thread.remove");
  expect(removed, JSON.stringify(log)).toBeGreaterThanOrEqual(0);
  expect(log.slice(removed).filter((c) => c.op === "chat.send" && c.params.session === a), JSON.stringify(log)).toEqual([]);
  expect(log.filter((c) => c.op === "chat.send" && c.params.text === "do not send after archive")).toEqual([]);
  const sends = (await calls("chat.send")).map((c) => c.params);
  expect(sends).toContainEqual({ bot: "kami", session: b, text: "B held", queued: true });
  expect(sends).toContainEqual({ bot: "kami", text: "main held", queued: true });
  // no blank chat of the removed thread is left in the store
  const left = await page.evaluate(async (id) => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    return Object.keys(m.getStore().getState().chats).filter((k) => k.endsWith(`:${id}`));
  }, a);
  expect(left).toEqual([]);
});
