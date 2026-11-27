// What the person does in a thread acts on that thread: Esc stops the open thread's turn (chat.interrupt with its
// session) and never the bot's main chat; a slow press on a thread row or its × does not lift the bot row it sits
// in, and ⌥↓ on a focused thread row does not reorder the bots. Unread and notifications: store.threadScope.test.ts.
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
      if (msg.id === "g2") res(msg);
    };
    ws.send(JSON.stringify({ id: "g2", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
const interrupts = async () =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === "chat.interrupt").map((c) => c.params);
const listed = (page: Page) =>
  page.locator(".bot-list button.bot").evaluateAll((els) => els.map((e) => (e.getAttribute("data-testid") ?? "").replace(/^bot-/, "")));

/** Kami with one thread, turns driven by hand; the page reloaded so the thread row shows. */
async function withThread(page: Page): Promise<string> {
  await mock("mock.reset");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "Scoped work", cwd: "/work/scope", ago: 1 }] });
  await page.reload();
  await expect(page.getByTestId(`thread-row-${threads[0]}`)).toBeVisible();
  return threads[0] as string;
}
async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}

test("Esc in an open thread stops that thread's turn, not the bot's main chat", async ({ page }) => {
  const id = await withThread(page);
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
  await say(page, "a long thread task");
  await expect(page.getByTestId("stop")).toBeVisible();
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").focus();
  await page.keyboard.press("Escape");
  await expect.poll(interrupts).toEqual([{ bot: "kami", session: id }]);
  await expect(page.getByTestId("stop")).toHaveCount(0);
});

test("Esc in an idle thread leaves the bot's running main chat alone", async ({ page }) => {
  const id = await withThread(page);
  await say(page, "a long main-chat task");
  await expect(page.getByTestId("stop")).toBeVisible();
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
  await expect(page.getByTestId("stop")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  expect(await interrupts()).toEqual([]);
  // the main chat still runs
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("stop")).toBeVisible();
});

for (const part of ["thread-open", "thread-x"]) {
  test(`a slow press on a thread row's ${part} does not lift its bot`, async ({ page }) => {
    const id = await withThread(page);
    const before = await listed(page);
    await page.getByTestId(`thread-row-${id}`).hover(); // the × shows on hover
    const box = (await page.getByTestId(`thread-row-${id}`).getByTestId(part).boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(450);
    await expect(page.getByTestId("bot-row-kami")).not.toHaveClass(/lifted/);
    await expect(page.locator("body")).not.toHaveClass(/row-dragging/);
    const below = (await page.getByTestId("bot-row-friren").boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, below.y + below.height / 2 + 6, { steps: 8 });
    await page.mouse.up();
    expect(await listed(page)).toEqual(before);
  });
}

test("⌥↓ on a focused thread row does not reorder the bots", async ({ page }) => {
  const id = await withThread(page);
  const before = await listed(page);
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").focus();
  await page.keyboard.press("Alt+ArrowDown");
  await page.waitForTimeout(200);
  expect(await listed(page)).toEqual(before);
});
