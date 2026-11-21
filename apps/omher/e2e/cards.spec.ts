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

test("approval: card with mono command, coloured buttons of one weight; Deny collapses it and stops the turn", async ({ page }) => {
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
  // no brand gradient on any button; every answer carries the same weight and size, each in its own colour (Deny
  // red, Allow once violet, Allow for session amber); Deny comes first
  for (const name of ["Allow once", "Allow for session", "Deny"]) {
    const bgImage = await btn(name).evaluate((el) => getComputedStyle(el).backgroundImage);
    expect(bgImage).toBe("none");
  }
  const looks = await Promise.all(
    ["Deny", "Allow once", "Allow for session"].map((n) =>
      btn(n).evaluate((el) => {
        const cs = getComputedStyle(el);
        return { weight: cs.fontWeight, height: el.getBoundingClientRect().height, color: cs.color, bg: cs.backgroundColor };
      }),
    ),
  );
  expect(new Set(looks.map((l) => `${l.weight}|${l.height}`)).size).toBe(1);
  expect(new Set(looks.map((l) => l.color)).size).toBe(3);
  expect(new Set(looks.map((l) => l.bg)).size).toBe(3);
  const order = await card.getByRole("button").allTextContents();
  expect(order.slice(0, 3)).toEqual(["Deny", "Allow once", "Allow for session"]);
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

const LONG_CHOICE =
  "Slack 실패 스레드에 남기기 — 원인 요약(11-19부터 같은 모델 실패, #1188 무관)을 #deploy-common 스레드에 카미가 답글로 (Recommended)";

/** Rewrites the mock's clarify.request on its way into the page. */
async function rewriteClarify(page: Page, fn: (msg: any) => void) {
  await page.routeWebSocket(new RegExp(`127\\.0\\.0\\.1:${MOCK}`), (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((m) => server.send(m));
    server.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg.event === "clarify.request") fn(msg);
      ws.send(JSON.stringify(msg));
    });
  });
}

test("clarify: numbered rows, long text wraps inside the card, a digit picks, the answer is the original string", async ({ page }) => {
  await rewriteClarify(page, (m) => {
    m.choices = [LONG_CHOICE, "재시도", "건너뛰기"];
  });
  await open(page);
  await send(page, "/clarify");
  const card = page.getByTestId("card-clarify");
  await expect(card).toBeVisible();
  const rows = card.locator(".iv-chip");
  await expect(rows).toHaveCount(4); // three choices and Other…
  await expect(rows.nth(0).locator(".iv-num")).toHaveText("1");
  await expect(rows.nth(3).locator(".iv-num")).toHaveText("4");
  await expect(rows.nth(0).locator(".iv-title")).toContainText("Slack 실패 스레드에 남기기");
  await expect(rows.nth(0).locator(".iv-title")).not.toContainText("(Recommended)");
  await expect(rows.nth(0)).toHaveAccessibleName(/^Slack 실패 스레드에 남기기 Recommended 원인 요약/);
  await expect(rows.nth(0).locator(".iv-badge")).toHaveText("Recommended");
  await expect(rows.nth(0).locator(".iv-desc")).toContainText("원인 요약(11-19부터");
  // one row per line, nothing past the card's right edge
  const cardBox = (await card.boundingBox())!;
  let prevBottom = -1;
  for (let i = 0; i < 4; i++) {
    const b = (await rows.nth(i).boundingBox())!;
    expect(b.x + b.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 0.5);
    expect(b.y).toBeGreaterThanOrEqual(prevBottom);
    prevBottom = b.y + b.height;
  }
  expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  // a digit typed in the composer is text there and picks nothing
  await page.getByTestId("composer").click();
  await page.keyboard.press("1");
  await expect(page.getByTestId("composer")).toHaveValue("1");
  await expect(card).toBeVisible();
  expect(await calls("clarify.respond")).toEqual([]);
  await page.getByTestId("composer").fill("");
  // a click on the card (its title) gives it focus; then the digit picks that row
  await card.locator(".card-title").click();
  await page.keyboard.press("1");
  await expect(page.getByTestId("card-line")).toContainText("Slack 실패 스레드에 남기기");
  expect(await calls("clarify.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "kami", answer: LONG_CHOICE }) }),
  ]);
});

test("clarify: the last number opens Other…, digits typed in its field stay text", async ({ page }) => {
  await open(page);
  await send(page, "/clarify");
  const card = page.getByTestId("card-clarify");
  await card.locator(".card-title").click();
  await page.keyboard.press("3"); // staging, production, Other…
  const field = card.getByLabel("Other answer 1");
  await expect(field).toBeFocused();
  await page.keyboard.type("v2 on 3");
  await expect(field).toHaveValue("v2 on 3");
  await field.press("Enter");
  await expect(page.getByTestId("card-line")).toHaveText(/Answered: v2 on 3/);
  expect(await calls("clarify.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ answer: "v2 on 3" }) }),
  ]);
});

test("interview: a digit picks within the focused question only", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "interview" });
  await page.getByTestId("needs-strip").click();
  await page.getByTestId("needs-item").first().click();
  const card = page.getByTestId("card-interview");
  await expect(card).toBeFocused();
  await page.keyboard.press("2"); // the card itself is focused, no question: nothing picked
  await expect(card.getByTestId("iv-count")).toHaveText(/^0 of 3/);
  const q1 = card.getByRole("radiogroup", { name: "Who is the release note for?" });
  const q2 = card.getByRole("group", { name: "Which sections should it have?" });
  // clicking a row (focus must follow the click in WebKit too), then a digit picks within that question
  await q1.getByRole("radio", { name: "Users" }).click();
  await page.keyboard.press("2");
  await expect(q1.getByRole("radio", { name: "Developers" })).toHaveAttribute("aria-checked", "true");
  await q2.getByRole("checkbox", { name: "Fixes" }).click();
  await page.keyboard.press("1");
  await page.keyboard.press("4");
  await expect(q2.getByRole("checkbox", { name: "Highlights" })).toHaveAttribute("aria-checked", "true");
  await expect(q2.getByRole("checkbox", { name: "Thanks" })).toHaveAttribute("aria-checked", "true");
  await expect(q2.getByRole("checkbox", { name: "Fixes" })).toHaveAttribute("aria-checked", "true"); // the click
  await expect(q1.getByRole("radio", { name: "Developers" })).toHaveAttribute("aria-checked", "true");
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
