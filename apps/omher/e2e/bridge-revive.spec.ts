// The bridge dies after the app was up. The shell starts it again on a new port with a new token; the page asks for the
// URL again and the open chat works without restarting omher. When the shell gives up (a crash loop), a bar says so with
// Retry and covers nothing else: the app, terminals included, stays visible and takes typing.
// `window.__OMHER_BRIDGE_URL__` stands in for the shell's `bridge_url` command and `mock.move` for the bridge coming
// back elsewhere; `window.__OMHER_GATE__` stands in for `bridge_status` / `bridge_retry`.
import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./term-find-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
type Call = { op: string; id?: number; data?: string };
/** Everything the program on pty `pty` was sent. */
const writesTo = (page: Page, pty: number) =>
  page.evaluate(
    (p) =>
      [...((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []), ...((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? [])]
        .filter((c) => c.op === "write" && c.id === p)
        .map((c) => c.data ?? "")
        .join(""),
    pty,
  );

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

test("a crash loop shows a bar with Retry; the app, a TERMINALS session included, stays visible and takes typing", async ({ page }) => {
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
  await openApp(page);

  // a shell in TERMINALS, the keyboard in it
  const id = await page.evaluate(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", "/w/revive"));
  const term = page.locator(`[data-testid="terminal"][data-session="${id}"]`);
  await expect(term.locator(".xterm-rows")).toContainText("(mock)");
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  const pty = (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
  await term.locator(".xterm-helper-textarea").focus();

  // the shell is starting a bridge that died: nothing shows over the app
  await setState({ state: "starting" });
  await page.waitForTimeout(2500);
  await expect(page.getByTestId("bridge-gate")).toHaveCount(0);
  await expect(page.getByTestId("bridge-bar")).toHaveCount(0);

  // it gave up: a bar says so, with Retry; no screen covers the app
  const error = "the bridge stopped unexpectedly (exit status: 1); it stopped 6 times in a row, so omher stopped starting it";
  await setState({ state: "failed", error });
  await expect(page.getByTestId("bridge-bar")).toHaveAttribute("data-state", "failed", { timeout: 5000 });
  await expect(page.getByTestId("bridge-error")).toHaveText(error);
  await expect(page.getByTestId("bridge-gate")).toHaveCount(0);
  // the terminal is what sits at its own middle (not under a cover), and it still has the keyboard
  await expect(term).toBeVisible();
  const box = (await term.boundingBox())!;
  const onTop = await page.evaluate(
    ([x, y, i]) => document.elementFromPoint(x as number, y as number)?.closest('[data-testid="terminal"]')?.getAttribute("data-session") === i,
    [box.x + box.width / 2, box.y + box.height / 2, id] as const,
  );
  expect(onTop).toBe(true);
  expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="terminal"]')?.getAttribute("data-session") ?? null)).toBe(id);
  await page.keyboard.type("echo still-typing");
  await expect.poll(() => writesTo(page, pty)).toContain("echo still-typing");

  await page.getByTestId("bridge-retry").click();
  await expect(page.getByTestId("bridge-bar")).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(term).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __gateCalls: string[] }).__gateCalls)).toEqual(["retry"]);
});

test("once the app is up, one refused status ask (a webview reload, say) shows nothing", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, any>;
    w.__refuse = 0;
    w.__asks = 0;
    // anything the gate ever shows, however briefly
    w.__shown = [];
    new MutationObserver(() => {
      for (const id of ["bridge-bar", "bridge-gate"]) if (document.querySelector(`[data-testid="${id}"]`) && !w.__shown.includes(id)) w.__shown.push(id);
    }).observe(document, { childList: true, subtree: true });
    w.__OMHER_GATE__ = {
      status: async () => {
        w.__asks += 1;
        if (w.__refuse > 0) {
          w.__refuse -= 1;
          throw new Error("ipc unavailable");
        }
        return { state: "ready" };
      },
      retry: async () => {},
      installCommand: async () => "",
      install: async () => 0,
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  const asks = await page.evaluate(() => (window as unknown as { __asks: number }).__asks);
  await page.evaluate(() => {
    const w = window as unknown as { __refuse: number; __shown: string[] };
    w.__shown = []; // the boot screen before the first answer is not this test's business
    w.__refuse = 1;
  });
  // the refused ask and the next (ready) one both happen; neither shows the bar or the screen
  await expect.poll(() => page.evaluate(() => (window as unknown as { __asks: number }).__asks), { timeout: 6000 }).toBeGreaterThan(asks + 1);
  expect(await page.evaluate(() => (window as unknown as { __shown: string[] }).__shown)).toEqual([]);
  await expect(page.getByTestId("bot-kami")).toBeVisible();
});
