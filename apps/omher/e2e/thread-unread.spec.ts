// A thread's unread answers show where the person can find them, against the mock bridge: a thread that answered while
// it was not open carries a count on its row (the bot row's unread badge style) and keeps the Dock / taskbar count up;
// opening it clears the mark and brings the count back to 0. A thread past "Show N more" counts on the bot row and on
// the "Show N more" line until its row shows.
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

const badge = (page: Page) => page.evaluate(() => (window as unknown as { __omherBadge?: number }).__omherBadge ?? 0);

/** Kami with `n` threads, newest first; the page reads them fresh. */
async function seed(page: Page, n: number): Promise<string[]> {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const { threads } = await mock("mock.threads", { bot: "kami", threads: Array.from({ length: n }, (_, i) => ({ title: `Thread ${i + 1}`, ago: (i + 1) * 3600 })) });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("threads-kami").getByRole("treeitem").first()).toBeVisible();
  return threads as string[];
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a thread that finished while not open shows a count; opening it clears the count and the Dock total", async ({ page }) => {
  const [done, other] = await seed(page, 2);
  await expect.poll(() => badge(page)).toBe(0);
  await mock("mock.threadAnswer", { bot: "kami", thread: done, text: "The release notes are ready." });
  const row = page.getByTestId(`thread-row-${done}`);
  await expect(row).toHaveAttribute("data-state", "done");
  await expect(row.getByTestId("thread-unread")).toHaveText("1");
  await expect(row.getByTestId("thread-open")).toHaveAttribute("aria-label", "Open thread Thread 1 · 1 unread");
  await expect(page.getByTestId(`thread-row-${other}`).getByTestId("thread-unread")).toHaveCount(0);
  // the thread is in view: the bot row does not count it a second time
  await expect(page.getByTestId("bot-kami").getByTestId("unread")).toHaveCount(0);
  await expect.poll(() => badge(page)).toBe(1);

  await row.getByTestId("thread-open").click();
  await expect(row).toHaveAttribute("aria-selected", "true");
  await expect(row.getByTestId("thread-unread")).toHaveCount(0);
  await expect.poll(() => badge(page)).toBe(0);
});

test("a thread past 'Show N more' counts on the bot row and the more line until it shows", async ({ page }) => {
  const ids = await seed(page, 7);
  const tree = page.getByTestId("threads-kami");
  const shown = await tree.locator("[data-thread]").evaluateAll((els) => els.map((e) => e.getAttribute("data-thread")));
  const hidden = ids.find((id) => !shown.includes(id))!;
  expect(hidden).toBeTruthy();
  await mock("mock.threadAnswer", { bot: "kami", thread: hidden, text: "Found the cause." });
  await expect(page.getByTestId("bot-kami").getByTestId("unread")).toHaveText("1");
  await expect(page.getByTestId("thread-more-unread")).toHaveText("1");
  await expect.poll(() => badge(page)).toBe(1);

  await page.getByTestId("thread-more").click();
  const row = page.getByTestId(`thread-row-${hidden}`);
  await expect(row.getByTestId("thread-unread")).toHaveText("1");
  await expect(page.getByTestId("bot-kami").getByTestId("unread")).toHaveCount(0);
  await expect(page.getByTestId("thread-more-unread")).toHaveCount(0);

  await row.getByTestId("thread-open").click();
  await expect(row.getByTestId("thread-unread")).toHaveCount(0);
  await expect.poll(() => badge(page)).toBe(0);
});
