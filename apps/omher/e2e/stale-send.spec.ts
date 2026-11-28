// Sleep and wake: the link to the bridge drops and comes back, and the reconnect's first bots.list is lost (the link
// flaps again). The bot's chat was left unread (stale) and held every message typed after it: Enter and Send did
// nothing that went out. A message typed there now reads the chat again itself and goes out.
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res) => (ws.onopen = () => res()));
  const out = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg.result);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out;
}
const sends = async () =>
  (await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.send" && c.params.bot === "kami").map((c: any) => c.params.text);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("after a wake whose re-read was lost, Enter sends the typed message", async ({ page }) => {
  let drop: (() => void) | null = null;
  let loseBots = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (loseBots && msg.op === "bots.list") {
        loseBots = false;
        ws.send(JSON.stringify({ id: msg.id, ok: false, error: { code: "disconnected", message: "bridge connection lost" } }));
        return;
      }
      server.send(raw);
    });
    drop = () => ws.close({ code: 1011, reason: "bridge went away" });
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("composer")).toBeEnabled();

  loseBots = true;
  drop!();
  await expect(page.getByTestId("composer")).toHaveAttribute("placeholder", /Kami/);
  await expect.poll(() => loseBots, { timeout: 10_000 }).toBe(false);
  await expect(page.getByTestId("composer")).toBeEnabled();

  await page.getByTestId("composer").fill("are you there");
  await page.getByTestId("composer").press("Enter");
  await expect.poll(sends, { timeout: 5_000 }).toEqual(["are you there"]);
  await expect(page.getByTestId("composer")).toHaveValue("");
  await expect(page.getByTestId("timeline").locator('[data-held="true"]')).toHaveCount(0);
});
