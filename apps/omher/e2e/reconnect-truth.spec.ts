// The link to the bridge drops while a bot waits on an approval (sleep/wake, a bridge restart). Hermes still waits:
// after the reconnect the bridge says the turn runs and sends the same ask again, and the ask is back in Needs you
// and answerable. It used to read "Not answered" for good: the replayed ask was dropped as a duplicate of the card
// the outage had closed.
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
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
const calls = async (op: string) => (await mock("mock.calls")).calls.filter((c: any) => c.op === op);

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toContainText("updater");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("an approval still waiting after the bridge comes back is in Needs you again and can be answered", async ({ page }) => {
  let drop: (() => void) | null = null;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => server.send(raw));
    drop = () => ws.close({ code: 1011, reason: "bridge went away" });
  });
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  const dot = page.getByTestId("bot-friren").getByTestId("needs");
  await expect(dot).toBeVisible();

  const reads = async () => (await calls("chat.open")).filter((c: any) => c.params.bot === "friren").length;
  const before = await reads();
  drop!();
  // the outage closes the turn here; the reconnect reads the chat again and the bridge replays the ask
  await expect.poll(reads, { timeout: 10_000 }).toBeGreaterThan(before);
  await expect(page.getByTestId("needs-strip")).toBeVisible();
  await expect(dot).toBeVisible();

  await page.getByTestId("bot-friren").click();
  const cards = page.getByTestId("timeline").getByTestId("card-approval");
  await expect(cards).toHaveCount(1);
  await cards.focus();
  await page.keyboard.press("2"); // Allow once
  await expect(page.getByTestId("timeline").getByTestId("card-line")).toHaveText(/Allowed once/);
  expect(await calls("approval.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "friren", choice: "once" }) }),
  ]);
  await expect(dot).toHaveCount(0);
});
