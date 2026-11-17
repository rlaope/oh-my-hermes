// "Reply there": a row in the side panel's "Where Kami is" puts a thread reference in the composer; the bot gets it as context in an
// ordinary turn and posts with its own tools. omher itself never writes to Slack or Discord.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-v02");
const BLOCK = "[omher] Reply target:";

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls, mock.submits). */
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
const calls = async (): Promise<{ op: string; params: Record<string, unknown> }[]> => (await mock("mock.calls")).calls;
const submits = async (): Promise<{ bot: string; session_id: string; text: string }[]> => (await mock("mock.submits")).submits;

/** Every op the app may call: reads, plus chat.send to the main chat. Nothing here writes to a messenger. */
const ALLOWED = new Set([
  "hello",
  // the sidebar reads each listed bot's threads (a read)
  "thread.list",
  // every bot's automations, read from files (no gateway)
  "automations.list",
  "bots.list",
  "bots.avatar",
  "bots.info",
  // Hermes' read-only readiness probe for the bot in view (setup.runtime_check)
  "bots.ready",
  "chat.open",
  "chat.send",
  "elsewhere.list",
  "routines.list",
  "models.options",
  // the sidebar's usage ring and the accounts behind it: read on boot, never written here
  "usage.read",
  "accounts.list",
  // channel names for Slack / Discord link chips: a read of the bot's own sessions
  "links.places",
  // the bot's own plans, for the header's panel button (a read of its dag runs)
  "runs.list",
  // a remote machine saved in ~/.omher/peers.json comes back on boot: its bots join the list (rule 31)
  "peers.attach",
  "peers.detach",
]);

/** Screenshot after every running animation (chip / menu `pop`) has finished; under load they start late. */
async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.evaluate(() =>
    Promise.allSettled(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity) // spinners never finish
        .map((a) => a.finished), // an animation on a removed element rejects; that is fine
    ),
  );
  await page.screenshot({ path: join(SHOTS, name) });
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel").getByTestId("where-row")).toHaveCount(4);
}
/** The panel row for one of the bot's sessions elsewhere. */
const row = (page: Page, session: string) => page.getByTestId("details-panel").locator(`[data-testid=where-row][data-session=${session}]`);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("hover Reply there → chip → send: the submitted text carries the target block once", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await open(page);
  const slack = row(page, "slack-og-dev-502");
  const action = slack.getByTestId("where-reply");
  await expect(action).toHaveCSS("opacity", "0"); // hidden until hover
  await slack.hover();
  await expect(action).toHaveCSS("opacity", "1");
  await expect(action).toHaveText("Reply there");
  await action.click();

  const chip = page.getByTestId("reply-chip");
  await expect(chip).toHaveText("#og-dev · thread");
  await expect(chip.locator("svg.src-ic-slack")).toBeVisible();
  await expect(page.getByTestId("composer")).toBeFocused();
  await expect(page.getByTestId("composer")).toHaveAttribute("placeholder", "Tell Kami what to post there");
  expect((await calls()).filter((c) => c.op === "chat.send")).toEqual([]); // the chip alone sends nothing

  await page.getByTestId("composer").fill("결과 요약해서 남겨줘");
  await shot(page, "T15-chip-dark.png");
  await page.getByTestId("send").click();

  await expect(page.getByTestId("reply-chip")).toHaveCount(0); // used once, then gone
  const user = page.getByTestId("bubble-user").last();
  await expect(user.locator(".b")).toHaveText("결과 요약해서 남겨줘"); // the block is not shown as typed text
  await expect(user.getByTestId("bubble-reply")).toHaveText("Reply target #og-dev");

  const send = (await calls()).filter((c) => c.op === "chat.send");
  expect(send.map((c) => c.params)).toEqual([{ bot: "kami", text: "결과 요약해서 남겨줘", reply_to: "slack-og-dev-502" }]);
  const sub = await submits();
  expect(sub).toHaveLength(1);
  expect(sub[0].session_id).toBe("main-kami");
  expect(sub[0].text.split(BLOCK).length - 1).toBe(1);
  expect(sub[0].text).toBe(
    "결과 요약해서 남겨줘\n\n[omher] Reply target: slack:C0123ABCD:1794186944.520669 (thread \"#og-dev\"). Post there only if " +
      "the user asked; use your own messaging tool or `hermes send --to slack:C0123ABCD:1794186944.520669`.",
  );
  await shot(page, "T15-sent-dark.png");

  // no op in the log writes anywhere but the main chat
  const ops = (await calls()).map((c) => c.op);
  expect(ops.filter((op) => !ALLOWED.has(op))).toEqual([]);
  expect(ops.some((op) => /send_message|post|slack|discord|telegram/i.test(op))).toBe(false);
});

test("Reply there on a Discord row; the chip is removable (× and Backspace)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await open(page);
  const discord = row(page, "discord-cron-openmaus");
  await discord.hover();
  await discord.getByTestId("where-reply").click();
  const chip = page.getByTestId("reply-chip");
  await expect(chip).toHaveText("#cron · thread");
  await expect(chip.locator("svg.src-ic-discord")).toBeVisible();
  await page.getByTestId("composer").fill("여기 정리해서 남겨줘");
  await shot(page, "T15-chip-light.png");

  await page.getByTestId("reply-chip-remove").click();
  await expect(chip).toHaveCount(0);
  await expect(page.getByTestId("composer")).toBeFocused();

  // Backspace in an empty composer removes the chip as well
  await discord.hover();
  await discord.getByTestId("where-reply").click();
  await page.getByTestId("composer").fill("");
  await page.getByTestId("composer").press("Backspace");
  await expect(chip).toHaveCount(0);

  // a removed chip sends a plain turn
  await page.getByTestId("composer").fill("status?");
  await page.getByTestId("composer").press("Enter");
  await expect.poll(async () => (await submits()).length).toBe(1);
  const sub = await submits();
  expect(sub[0].text).toBe("status?");
  expect((await calls()).filter((c) => c.op === "chat.send").map((c) => c.params)).toEqual([{ bot: "kami", text: "status?" }]);
});

test("'there' without a chip is an ordinary turn: nothing is guessed", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await open(page);
  await page.getByTestId("composer").fill("거기 슬랙에 남겨줘");
  await page.getByTestId("composer").press("Enter");
  await expect.poll(async () => (await submits()).length).toBe(1);
  expect((await submits())[0].text).toBe("거기 슬랙에 남겨줘");
  expect((await calls()).filter((c) => c.op === "chat.send")[0].params).toEqual({ bot: "kami", text: "거기 슬랙에 남겨줘" });
  await expect(page.getByTestId("bubble-user").last().getByTestId("bubble-reply")).toHaveCount(0);
});

test("a session with no thread offers no Reply there", async ({ page }) => {
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
        for (const s of msg.result.sessions) s.reply_target = null;
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const slack = row(page, "slack-og-dev-502");
  await slack.hover();
  await expect(slack.getByTestId("where-reply")).toHaveCount(0);
  await expect(slack.locator("a.ew-ss")).toBeVisible(); // it still opens in Slack
});
