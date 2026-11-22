// The bridge dies after the app was up. The shell starts it again on a new port with a new token; the page asks for the
// URL again and the open chat works without restarting omher. When the shell gives up (a crash loop), the gate's
// failure covers the app, which stays mounted, and Retry brings it back.
// `window.__OMHER_BRIDGE_URL__` stands in for the shell's `bridge_url` command and `mock.move` for the bridge coming
// back elsewhere; `window.__OMHER_GATE__` stands in for `bridge_status` / `bridge_retry`.
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const url = (port: number) => `ws://127.0.0.1:${port}/?token=e2e`;
/** The port the mock serves on now (`mock.move` changes it). */
let live = MOCK;

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(url(live));
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

test.beforeEach(async () => {
  live = MOCK;
  await mock("mock.reset");
});

test.afterEach(async () => {
  // the first port serves again for the specs after this one
  await mock("mock.reset");
  live = MOCK;
});

test("an open chat works again after the bridge comes back on a new port", async ({ page }) => {
  await page.addInitScript((first) => {
    const w = window as unknown as Record<string, unknown>;
    w.__omherBridgeUrl = first;
    w.__OMHER_BRIDGE_URL__ = async () => w.__omherBridgeUrl;
  }, url(MOCK));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const composer = page.getByTestId("composer");
  await expect(composer).toBeEnabled();

  // the bridge dies: the old port takes no connection, the chat says it is reconnecting
  const { port } = await mock("mock.move", { on: true });
  live = port;
  await expect(composer).toBeDisabled();
  await expect(composer).toHaveAttribute("placeholder", "Connecting to Hermes…");

  // the shell started it again elsewhere: the next dial asks for the URL and finds it
  await page.evaluate((next) => {
    (window as unknown as Record<string, unknown>).__omherBridgeUrl = next;
  }, url(port));
  await expect(composer).toBeEnabled({ timeout: 10_000 });
  await composer.fill("still there after the bridge came back?");
  await page.keyboard.press("Enter");
  await expect
    .poll(async () => (await mock("mock.submits")).submits.map((s: { text: string }) => s.text))
    .toContain("still there after the bridge came back?");
  await expect(page.getByTestId("timeline").getByTestId("bubble-user").last()).toContainText("still there after the bridge came back?");
});

test("a crash loop covers the app with the failure; Retry brings it back with the app still there", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, any>;
    w.__gateState = { state: "ready" };
    w.__gateCalls = [];
    w.__OMHER_GATE__ = {
      status: async () => w.__gateState,
      retry: async () => {
        w.__gateCalls.push("retry");
        w.__gateState = { state: "ready" };
      },
      installCommand: async () => "",
      install: async () => 0,
    };
  });
  const setState = (s: Record<string, unknown>) =>
    page.evaluate((st) => {
      (window as unknown as Record<string, unknown>).__gateState = st;
    }, s);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();

  // the shell is starting a bridge that died: the app stays, no screen covers it
  await setState({ state: "starting" });
  await page.waitForTimeout(2500);
  await expect(page.getByTestId("bridge-gate")).toHaveCount(0);
  await expect(page.getByTestId("bot-kami")).toBeVisible();

  // it gave up: the failure shows over the app, which is still mounted underneath
  const error = "the bridge stopped unexpectedly (exit status: 1); it stopped 6 times in a row, so omher stopped starting it";
  await setState({ state: "failed", error });
  await expect(page.getByTestId("bridge-error")).toHaveText(error, { timeout: 5000 });
  await expect(page.getByTestId("bridge-gate")).toHaveClass(/gate--over/);
  await expect(page.getByTestId("bot-kami")).toBeAttached();

  await page.getByTestId("bridge-retry").click();
  await expect(page.getByTestId("bridge-gate")).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __gateCalls: string[] }).__gateCalls)).toEqual(["retry"]);
});
