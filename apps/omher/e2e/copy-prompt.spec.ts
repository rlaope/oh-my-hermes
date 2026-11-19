// Copy on the person's own messages, against the mock bridge: a prompt carries the same quiet control an
// answer does (testId copy-prompt), it puts exactly the typed text on the clipboard, an answer's copy-answer
// still works beside it, and a thread's prompt (the same Bubble) has it too. A held prompt (not sent yet) has none.
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

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** Past the onboarding cards, on Kami's main chat. */
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** Chromium on Windows stores clipboard text with the engine's CRLF; every other character must match. */
async function copied(page: Page): Promise<string> {
  return (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n");
}

const PROMPT = "복사해 둘 프롬프트: v1.2 릴리스 노트 정리";

test("a sent prompt has a copy control that puts exactly that text on the clipboard", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  await page.getByTestId("composer").fill(PROMPT);
  await page.keyboard.press("Enter");

  const user = page.getByTestId("bubble-user").last();
  await expect(user.locator(".b")).toHaveText(PROMPT);
  const copy = user.getByTestId("copy-prompt");
  await expect(copy).toHaveCount(1);
  // quiet at rest, shown on hover of the message, like the answer's
  expect(await copy.evaluate((el) => getComputedStyle(el).opacity)).toBe("0");
  await user.hover();
  await expect.poll(() => copy.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");

  await copy.click();
  await expect(copy).toHaveAttribute("aria-label", "Copied");
  expect(await copied(page)).toBe(PROMPT);
});

test("an answer's copy-answer still works beside the prompt's control", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const ANSWER = "릴리스 노트는 이미 정리해 두었어요.";
  await mock("mock.answer", { bot: "kami", text: ANSWER });
  await open(page);
  await page.getByTestId("composer").fill("릴리스 노트 정리됐어?");
  await page.keyboard.press("Enter");

  const answer = page.getByTestId("bubble-bot").last();
  await expect(answer.locator(".b")).toContainText(ANSWER);
  const copy = answer.getByTestId("copy-answer");
  await expect(copy).toHaveCount(1);
  await answer.hover();
  await copy.click();
  await expect(copy).toHaveAttribute("aria-label", "Copied");
  expect(await copied(page)).toBe(ANSWER);
  // the prompt above it keeps its own, untouched
  await expect(page.getByTestId("bubble-user").last().getByTestId("copy-prompt")).toHaveCount(1);
});

test("a thread's prompt carries the same control", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  const TEXT = "릴리스 노트 초안 정리해줘";
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "릴리스 노트", ago: 60, messages: [["user", TEXT]] }] });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const [id] = threads as string[];
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
  const user = page.getByTestId("thread-chat").getByTestId("bubble-user").last();
  await expect(user.locator(".b")).toHaveText(TEXT);
  await user.hover();
  await user.getByTestId("copy-prompt").click();
  expect(await copied(page)).toBe(TEXT);
});

test("a held prompt has no copy control; one whose steer never answered has it, before its marks", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mock("mock.manual", { bot: "kami" });
  // Hermes answers the steer with "uncertain": the row stays marked (↵ Send, × Delete) and may have reached the bot
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
      if (ops.get(msg.id) === "chat.steer" && msg.ok) return ws.send(JSON.stringify({ ...msg, result: { status: "uncertain" } }));
      ws.send(raw);
    });
  });
  await open(page);
  const box = page.getByTestId("composer");
  await box.fill("Refactor the gateway retry code");
  await box.press("Enter");
  await expect(page.getByTestId("stop")).toBeVisible();
  const TEXT = "also keep the old timeout";
  await box.fill(TEXT);
  await box.press("Enter");
  const row = page.getByTestId("bubble-user").filter({ hasText: TEXT });
  await expect(row).toHaveAttribute("data-held", "true");
  // not sent yet: its ↓ puts it back in the box, there is nothing to copy
  await expect(row.getByTestId("copy-prompt")).toHaveCount(0);

  await row.getByTestId("queue-mark").click();
  await expect(row.getByTestId("bubble-steer-unknown")).toBeVisible();
  const copy = row.getByTestId("copy-prompt");
  await expect(copy).toHaveCount(1);
  await row.hover();
  await expect.poll(() => copy.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
  // before the marks, on their line: never on top of them
  const c = (await copy.boundingBox())!;
  const acts = (await row.getByTestId("queue-acts").boundingBox())!;
  expect(c.x + c.width).toBeLessThanOrEqual(acts.x);
  expect(Math.abs(c.y + c.height / 2 - (acts.y + acts.height / 2))).toBeLessThanOrEqual(2);
  await copy.click();
  expect(await copied(page)).toBe(TEXT);
});
