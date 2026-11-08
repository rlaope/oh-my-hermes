// Cards: approval (Allow once / Allow for session / Deny) and clarify (choices or a small input). Answered cards
// collapse to one gray line.
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (CARDS_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.CARDS_SHOTS || "test-results";

test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls). */
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

/** Every bridge event the page receives, in order. */
function recordEvents(page: Page): any[] {
  const events: any[] = [];
  page.on("websocket", (ws) => {
    ws.on("framereceived", (f) => {
      try {
        const m = JSON.parse(String(f.payload));
        if (m && typeof m.event === "string") events.push(m);
      } catch {
        /* not JSON */
      }
    });
  });
  return events;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

async function send(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}

const calls = async (op: string) => (await mock("mock.calls")).calls.filter((c: any) => c.op === op);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("approval: card with mono command, neutral buttons; Deny collapses it and stops the turn", async ({ page }) => {
  const events = recordEvents(page);
  await open(page);
  await send(page, "/approve clean the build");
  const tl = page.getByTestId("timeline");
  const card = tl.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Run shell command");
  const cmd = card.locator(".card-cmd");
  await expect(cmd).toHaveText("rm -rf ./build");
  expect(await cmd.evaluate((el) => getComputedStyle(el).fontFamily)).toMatch(/mono|Menlo/i);
  const btn = (name: string) => card.getByRole("button", { name, exact: true });
  for (const name of ["Allow once", "Allow for session", "Deny"]) await expect(btn(name)).toBeVisible();
  // no pink / brand gradient on any button; Deny is gray (no fill), Allow once is a filled neutral
  for (const name of ["Allow once", "Allow for session", "Deny"]) {
    const bgImage = await btn(name).evaluate((el) => getComputedStyle(el).backgroundImage);
    expect(bgImage).toBe("none");
  }
  const colors = await Promise.all(
    ["Allow once", "Deny"].map((n) =>
      btn(n).evaluate((el) => {
        const cs = getComputedStyle(el);
        return { bg: cs.backgroundColor, fg: cs.color };
      }),
    ),
  );
  const rgb = (s: string) => (s.match(/[\d.]+/g) ?? []).map(Number);
  const [r, g, b] = rgb(colors[0].bg);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24); // neutral, not pink
  expect(rgb(colors[1].bg)[3] ?? 1).toBe(0); // Deny: transparent
  await page.screenshot({ path: join(SHOTS, "cards-approval-dark.png") });

  const before = events.length;
  await btn("Deny").click();
  const line = tl.getByTestId("card-line");
  await expect(line).toHaveText(/Denied/);
  await expect(tl.getByTestId("card-approval")).toHaveCount(0);
  await expect(line.locator("button")).toHaveCount(0);
  expect(await line.evaluate((el) => el.getBoundingClientRect().height)).toBeLessThanOrEqual(26);

  const responds = await calls("approval.respond");
  expect(responds).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "kami", choice: "deny" }) }),
  ]);
  // the turn ends interrupted -> activity line says Stopped
  await expect(tl.locator('[data-kind="activity"]').last()).toContainText("Stopped");
  await expect(page.getByTestId("stop")).toHaveCount(0);
  await page.waitForTimeout(1200); // an allowed run would have sent tool.end by now
  const after = events.slice(before);
  expect(after.some((e) => e.event === "turn.end" && e.outcome === "interrupted")).toBe(true);
  expect(after.filter((e) => e.event === "tool.end")).toEqual([]);
  await page.screenshot({ path: join(SHOTS, "cards-denied-dark.png") });
});

test("approval: Allow once runs it and collapses to 'Allowed once'", async ({ page }) => {
  await open(page);
  await send(page, "/approve");
  const tl = page.getByTestId("timeline");
  await tl.getByTestId("card-approval").getByRole("button", { name: "Allow once", exact: true }).click();
  await expect(tl.getByTestId("card-line")).toHaveText(/Allowed once/);
  await expect(tl.getByTestId("bubble-bot").filter({ hasText: "approved: once" })).toBeVisible();
  expect(await calls("approval.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ choice: "once" }) }),
  ]);
});

test("clarify: choose an answer -> clarify.respond sent, card collapses to 'Answered: …'", async ({ page }) => {
  await open(page);
  await send(page, "/clarify");
  const tl = page.getByTestId("timeline");
  const card = tl.getByTestId("card-clarify");
  await expect(card).toContainText("Which environment should I deploy to?");
  await expect(card.getByRole("button", { name: "production" })).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "cards-clarify-dark.png") });
  await card.getByRole("button", { name: "staging" }).click();
  await expect(tl.getByTestId("card-line")).toHaveText(/Answered: staging/);
  await expect(tl.getByTestId("card-clarify")).toHaveCount(0);
  expect(await calls("clarify.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "kami", answer: "staging" }) }),
  ]);
  await expect(tl.getByTestId("bubble-bot").filter({ hasText: "Got it, using staging." })).toBeVisible();
});

test("clarify without choices: small input answers it", async ({ page }) => {
  // The mock always offers choices; drop them on the way in so the card shows its input.
  await page.routeWebSocket(new RegExp(`127\\.0\\.0\\.1:${MOCK}`), (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((m) => server.send(m));
    server.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg.event === "clarify.request") {
        delete msg.choices;
        msg.question = "Which branch name?";
      }
      ws.send(JSON.stringify(msg));
    });
  });
  await open(page);
  await send(page, "/clarify");
  const tl = page.getByTestId("timeline");
  const card = tl.getByTestId("card-clarify");
  await expect(card).toContainText("Which branch name?");
  await expect(card.getByRole("button", { name: "staging" })).toHaveCount(0);
  await card.getByLabel("Your answer").fill("release/0.1");
  await card.getByLabel("Your answer").press("Enter");
  await expect(tl.getByTestId("card-line")).toHaveText(/Answered: release\/0\.1/);
  expect(await calls("clarify.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "kami", answer: "release/0.1" }) }),
  ]);
});

test("a card left open when the turn is stopped collapses to one line", async ({ page }) => {
  await open(page);
  await send(page, "/approve");
  const tl = page.getByTestId("timeline");
  await expect(tl.getByTestId("card-approval")).toBeVisible();
  await page.getByTestId("stop").click();
  await expect(tl.getByTestId("card-line")).toHaveText(/Not answered/);
  await expect(tl.getByTestId("card-approval")).toHaveCount(0);
  expect(await calls("approval.respond")).toEqual([]);
});

test("light theme: card stays neutral", async ({ page }) => {
  await open(page);
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await send(page, "/approve");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({ path: join(SHOTS, "cards-approval-light.png") });
  await card.getByRole("button", { name: "Deny", exact: true }).click();
  await expect(page.getByTestId("card-line")).toHaveText(/Denied/);
});
