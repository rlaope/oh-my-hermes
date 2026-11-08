// Inputs the closing verify broke (D2–D4): an offline bot, a blank away label, the bridge dying mid-turn.
import { expect, test, type Page } from "@playwright/test";

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

test("an offline bot shows why instead of Loading… forever", async ({ page }) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.op === "chat.open" && msg.bot === "friren") {
        ws.send(JSON.stringify({ id: msg.id, ok: false, error: { code: "bot_offline", message: "gateway could not start" } }));
        return;
      }
      server.send(raw);
    });
  });
  await open(page);
  await page.getByTestId("bot-friren").click();
  const err = page.getByTestId("chat-error");
  await expect(err).toBeVisible();
  await expect(err).toContainText("gateway could not start");
  await expect(page.getByTestId("timeline").getByText("Loading…")).toHaveCount(0);
});

test("an away session with a blank label still gets a title", async ({ page }) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "elsewhere.list" && msg.ok) {
        for (const s of msg.result.sessions) if (s.source === "slack") { s.label = ""; s.title = ""; }
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const titles = await page.locator(".ew-ttl").allTextContents();
  expect(titles.length).toBeGreaterThan(0);
  for (const t of titles) expect(t.trim()).not.toBe("");
  expect(titles).toContain("Slack session");
});

test("bridge lost mid-turn: activity ends Stopped, Stop goes away, nothing is resent", async ({ page }) => {
  let sends = 0;
  let drop: (() => void) | null = null;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.op === "chat.send") sends++;
      server.send(raw);
    });
    drop = () => ws.close({ code: 1011, reason: "bridge died" });
  });
  await open(page);
  await page.getByTestId("composer").fill("run something long");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("stop")).toBeVisible();
  drop!();
  // Checked before the client reconnects: the lost turn is closed as stopped, not left live.
  await expect(page.getByTestId("stop")).toHaveCount(0, { timeout: 1000 });
  await expect(page.getByTestId("timeline")).toContainText(/Stopped after/);
  await page.waitForTimeout(2500); // reconnect window
  expect(sends).toBe(1);
});
