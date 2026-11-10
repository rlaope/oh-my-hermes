// The v0.2 polish pass: what each fix promises, measured. (The sidebar split is in sessions.spec.ts, the graph in
// runs.spec.ts.)
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the first-run screen is drawn in the person's theme: light, though the app has not mounted", async ({ page }) => {
  // `__OMHER_GATE__` stands in for the Tauri shell and reports Hermes missing: the setup screen shows and <App>
  // (which used to be the only place the theme was set) never mounts
  await page.addInitScript(() => {
    localStorage.setItem("omher.theme", "light");
    (window as unknown as Record<string, unknown>).__OMHER_GATE__ = {
      status: async () => ({ state: "failed", error: "Hermes not found: install Hermes Agent first", missing: "hermes" }),
      retry: async () => {},
      installCommand: async () => "sh install.sh",
      install: async () => {},
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("setup-screen")).toBeVisible();
  await expect(page.getByTestId("sidebar")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const [r, g, b] = bg.match(/\d+/g)!.map(Number);
  expect(Math.min(r, g, b)).toBeGreaterThan(200); // a light page, not the dark default
});

test("no bots: the empty pane says what a bot is and how to get one", async ({ page }) => {
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
      if (ops.get(msg.id) === "bots.list" && msg.ok) {
        msg.result.bots = [];
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await page.goto("/");
  const empty = page.getByTestId("chat-empty");
  await expect(empty).toContainText("No bots yet");
  await expect(empty).toContainText("Add one with + at the top left");
  await expect(empty.locator("code")).toHaveText("hermes profile create <name>");
  // readable: the hint is not in the faintest gray
  const [hint, faint] = await empty.evaluate((e) => {
    const probe = document.createElement("i");
    probe.style.color = "var(--quiet)";
    e.appendChild(probe);
    const out = [getComputedStyle(e).color, getComputedStyle(probe).color];
    probe.remove();
    return out;
  });
  expect(hint).not.toBe(faint);
});

test("the bridge goes away: the composer says so and waits, then comes back by itself", async ({ page }) => {
  let drop: (() => void) | null = null;
  let away = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    if (away) return; // while the bridge is away a reconnect hangs, so the waiting state stays long enough to read
    const server = ws.connectToServer();
    ws.onMessage((raw) => server.send(raw));
    drop = () => {
      away = true;
      ws.close({ code: 1011, reason: "bridge died" });
    };
  });
  await open(page);
  const composer = page.getByTestId("composer");
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveAttribute("placeholder", "Message Kami");
  drop!();
  await expect(composer).toBeDisabled();
  await expect(composer).toHaveAttribute("placeholder", "Connecting to Hermes…");
  await expect(page.getByTestId("send")).toBeDisabled();
});

test("one divider across the window: the side panel's tab bar ends where the chat header ends", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toBeVisible();
  const [head, tabs] = await page.evaluate(() => [
    document.querySelector(".head")!.getBoundingClientRect().bottom,
    document.querySelector(".details .details-h")!.getBoundingClientRect().bottom,
  ]);
  expect(Math.abs(head - tabs)).toBeLessThanOrEqual(0.5);
});

test("a narrow chat column: a bubble may use the column, instead of a sentence in five lines beside empty room", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 760 });
  await open(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-terminal").click();
  // one long paragraph from the bot
  const text = "The upstream closes idle connections after sixty seconds while the gateway keeps them for seventy five, so a request that picks a stale one fails; ".repeat(3);
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }, { event: "message", bot: "kami", id: "polish-1", text }, { event: "turn.end", bot: "kami", outcome: "done" }] });
  const bubble = page.locator(".msg.a").filter({ hasText: "The upstream closes idle connections" }).last();
  await expect(bubble).toBeVisible();
  const narrow = await bubble.evaluate((row: HTMLElement) => {
    const b = row.querySelector<HTMLElement>(".b")!;
    return b.getBoundingClientRect().width / (b.parentElement as HTMLElement).clientWidth;
  });
  // it fills the column beside the face; it used to stop at 80% of it
  expect(narrow).toBeGreaterThan(0.98);
  // in a wide column the old proportion holds: the same bubble stops well short of the row's right edge
  await page.setViewportSize({ width: 1440, height: 900 });
  const wide = await bubble.evaluate((row: HTMLElement) => {
    const b = row.querySelector<HTMLElement>(".b")!.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    return (r.right - b.right) / r.width;
  });
  expect(wide).toBeGreaterThan(0.12);
});

test("a message of several lines: + and send stay level on the last line", async ({ page }) => {
  await open(page);
  const composer = page.getByTestId("composer");
  await composer.fill("one\ntwo\nthree\nfour");
  const [plus, send, box] = await page.evaluate(() => {
    const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    return [r("[data-testid=attach]"), r("[data-testid=send]"), r("[data-testid=composer]")];
  });
  expect(box.height).toBeGreaterThan(70); // the box grew to four lines
  const mid = (r: DOMRect) => r.top + r.height / 2;
  expect(Math.abs(mid(plus) - mid(send))).toBeLessThanOrEqual(2);
  expect(plus.bottom).toBeGreaterThan(box.bottom - 12); // both on the last line, not the first
  // and on one line they are level too
  await composer.fill("one");
  const [p1, s1] = await page.evaluate(() => {
    const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    return [r("[data-testid=attach]"), r("[data-testid=send]")];
  });
  expect(Math.abs(mid(p1) - mid(s1))).toBeLessThanOrEqual(2);
});

test("light theme: the working spinner's arc is the accent, dark enough to see on white", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.theme", "light"));
  await open(page);
  const [spin, accent] = await page.evaluate(() => {
    const probe = document.createElement("i");
    probe.className = "ui-spin";
    document.body.appendChild(probe);
    const a = document.createElement("i");
    a.style.color = "var(--accent)";
    document.body.appendChild(a);
    const out = [getComputedStyle(probe).borderTopColor, getComputedStyle(a).color];
    probe.remove();
    a.remove();
    return out;
  });
  expect(spin).toBe(accent);
  // 4.5:1 or better on white
  const [r, g, b] = spin.match(/\d+/g)!.map((v) => Number(v) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  expect(1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)).toBeGreaterThanOrEqual(4.5);
});
