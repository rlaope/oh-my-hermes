// A routine that keeps failing folds into one timeline line that counts its runs (khope: the routine history kept
// piling up in the bot's chat, one line every 30 minutes).
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
      if (msg.id === "rf1") res(msg);
    };
    ws.send(JSON.stringify({ id: "rf1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
const emit = (...events: Record<string, unknown>[]) => mock("mock.emit", { events });

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("twelve failed runs of one routine read as one line: ×12 and the time range", async ({ page }) => {
  await open(page);
  const t0 = Math.floor(new Date(2026, 10, 17, 3, 56).getTime() / 1000);
  const fail = (n: number, id = "job-sso") => ({ event: "routine.ran", bot: "kami", routine_id: id, name: "sionic-kami-sso-refresh", status: "delivery_failed", ts: t0 + n * 1860 });
  for (let n = 0; n < 12; n++) await emit(fail(n));
  const lines = page.getByTestId("routine-line");
  await expect(lines).toHaveCount(1);
  await expect(lines.first()).toContainText("sionic-kami-sso-refresh");
  await expect(lines.first().getByTestId("routine-when")).toHaveText("×12 · 03:56–09:37");
  // Hermes' delivery_failed reads as a failure in words, in the danger colour
  const word = lines.first().locator(".routine-bad");
  await expect(word).toHaveText("not delivered");
  // a run that went fine adds nothing; another routine starts its own line
  await emit({ ...fail(12), status: "ok" }, fail(13, "job-other"));
  await expect(lines).toHaveCount(2);
  await expect(lines.nth(1).getByTestId("routine-when")).toHaveText(/^\d\d:\d\d$/);
});
