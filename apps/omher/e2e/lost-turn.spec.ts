// #3123: Hermes' gateway was killed in the middle of a main-chat turn (a crash). Hermes then holds that turn as lost
// and every later message of the chat in its own queue until someone acknowledges the lost turn. Before the fix the
// chat sat silent: "Read" under the new message, no answer, and the message gone from view after a restart.
// 1. the chat says it is paused, quotes the lost turn, and offers Discard; the composer stays usable;
// 2. a message sent meanwhile reads "Waiting", never "Read", and is still there (waiting) after a reload;
// 3. Discard lets it run: the block goes and the bot answers it;
// 4. a thread whose turn Hermes lost: the same note in that thread only, and Discard runs what waited there;
// 5. ko: no raw keys.
// Shots: OMHER_SHOTS=<dir> (lost-turn-<what>-<theme>.png).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

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

async function setup(page: Page, theme: "dark" | "light" = "dark", lang = "en") {
  await page.addInitScript(
    ([t, l]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.setItem("omher.lang", l as string);
    },
    [theme, lang] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function shot(page: Page, what: string, theme: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `lost-turn-${what}-${theme}.png`), animations: "disabled", caret: "initial" });
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.lostTurn", { bot: "kami", text: "hello" });
});

for (const theme of ["dark", "light"] as const) {
  test(`a chat whose turn Hermes lost says so, keeps what is sent, and Discard lets it run (${theme})`, async ({ page }) => {
    await setup(page, theme);
    const block = page.getByTestId("lost-turn");
    await expect(block).toBeVisible();
    await expect(page.getByTestId("lost-turn-text")).toContainText("this chat is paused");
    await expect(page.getByTestId("lost-turn-quote")).toHaveText("Lost turn: “hello”");

    const box = page.getByTestId("composer");
    await expect(box).toBeEnabled();
    await box.fill("you there?");
    await box.press("Enter");
    const sent = page.getByTestId("bubble-user").filter({ hasText: "you there?" });
    await expect(sent.getByTestId("bubble-waiting")).toHaveText("Waiting · runs after the lost turn is discarded");
    await expect(sent.getByTestId("bubble-read")).toHaveCount(0);
    await shot(page, "paused", theme);

    // omher closed and opened again: the message is not in Hermes' transcript yet, and is still shown, waiting
    await page.reload();
    await expect(block).toBeVisible();
    await expect(page.getByTestId("bubble-user").filter({ hasText: "you there?" })).toHaveCount(1);
    await expect(sent.getByTestId("bubble-waiting")).toBeVisible();

    await page.getByTestId("lost-turn-discard").click();
    await expect(block).toHaveCount(0);
    await expect(sent.getByTestId("bubble-waiting")).toHaveCount(0);
    await expect(page.getByTestId("bubble-bot").last()).toContainText("expired keep-alive connections", { timeout: 10_000 });
    // it ran once and shows once (Hermes' transcript row replaced the waiting copy)
    await expect(page.getByTestId("bubble-user").filter({ hasText: "you there?" })).toHaveCount(1);
    await shot(page, "discarded", theme);
  });
}

test("Korean shows no raw keys", async ({ page }) => {
  await setup(page, "dark", "ko");
  await expect(page.getByTestId("lost-turn")).toBeVisible();
  await expect(page.getByTestId("lost-turn")).not.toContainText("lost.");
  await expect(page.getByTestId("lost-turn-discard")).toHaveText("버리고 계속하기");
  // polite 해요 style, the bot's name without a 이(가) fallback particle
  const note = page.getByTestId("lost-turn");
  await expect(page.getByTestId("lost-turn-text")).toHaveText(/^Kami의 턴이 도중에 끊겨서/);
  await expect(note).not.toContainText("(가)");
  await expect(note).not.toContainText("니다");
});

test("a thread whose turn Hermes lost is paused there only, and Discard runs the message that waited", async ({ page }) => {
  await mock("mock.reset"); // no lost main-chat turn this time
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "Build", cwd: "/work/build", ago: 1 }] });
  const id = threads[0] as string;
  await mock("mock.lostTurn", { bot: "kami", session: id, text: "build it" });
  await setup(page);
  await expect(page.getByTestId("lost-turn")).toHaveCount(0); // the main chat is not paused
  await page.getByTestId(`thread-row-${id}`).getByTestId("thread-open").click();
  await expect(page.getByTestId("thread-chat")).toBeVisible();
  await expect(page.getByTestId("lost-turn-quote")).toHaveText("Lost turn: “build it”");
  const box = page.getByTestId("composer");
  await box.fill("still there?");
  await box.press("Enter");
  const sent = page.getByTestId("bubble-user").filter({ hasText: "still there?" });
  await expect(sent.getByTestId("bubble-waiting")).toHaveText("Waiting · runs after the lost turn is discarded");
  await page.getByTestId("lost-turn-discard").click();
  await expect(page.getByTestId("lost-turn")).toHaveCount(0);
  await expect(page.getByTestId("bubble-bot").last()).toContainText("Working in /work/build: still there?", { timeout: 10_000 });
  await expect(page.getByTestId("bubble-user").filter({ hasText: "still there?" })).toHaveCount(1);
});
