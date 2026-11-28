// The queue bar above the composer: while messages wait in omher (a steer Hermes refused, mock.steerMode reject) it
// says how many, and Pause keeps them from going out when the turn ends until Resume; Clear deletes them all on a
// second press. One line at the app's narrowest window, in every language.
// Shots (the bar with three waiting, then paused): OMHER_SHOTS=<dir>.
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
  // the mock also broadcasts events to this socket: wait for the reply to this request
  const out = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out.result;
}
const submitted = async () => ((await mock("mock.submits")).submits as { bot: string; text: string }[]).filter((x) => x.bot === "kami").map((x) => x.text);
const endTurn = () => mock("mock.endTurn", { bot: "kami", outcome: "done" });

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.manual", { bot: "kami" });
  // Hermes refuses steers: what is typed mid-answer waits in omher
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
});

async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}
/** kami's chat with a turn running and three messages waiting behind it. */
async function threeWaiting(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await say(page, "Refactor the gateway retry code");
  await expect(page.getByTestId("stop")).toBeVisible();
  await expect(page.getByTestId("queue-bar")).toHaveCount(0);
  for (const text of ["first after", "second after", "third after"]) await say(page, text);
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(3);
}

test("Pause keeps three waiting messages from going out at the turn's end; Resume sends them in order", async ({ page }) => {
  await threeWaiting(page);
  const bar = page.getByTestId("queue-bar");
  await expect(bar).toHaveAttribute("role", "group");
  await expect(bar).toHaveAttribute("aria-label", "Waiting messages");
  await expect(page.getByTestId("queue-bar-count")).toHaveText("3 waiting");
  await expect(page.getByTestId("queue-bar-count")).toHaveAttribute("aria-live", "polite");
  await expect(page.getByTestId("queue-pause")).toHaveText("Pause");
  // right above the composer
  const [b, box] = await Promise.all([bar.boundingBox(), page.getByTestId("composer-box").boundingBox()]);
  expect(b!.y + b!.height).toBeLessThanOrEqual(box!.y);
  expect(box!.y - (b!.y + b!.height)).toBeLessThanOrEqual(8);
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, "queue-bar-three-waiting.png"), animations: "disabled" });
  }

  await page.getByTestId("queue-pause").click();
  await expect(bar).toHaveAttribute("data-paused", "true");
  await expect(page.getByTestId("queue-bar-count")).toHaveText("Paused · 3 waiting");
  await expect(page.getByTestId("queue-pause")).toHaveText("Resume");
  await expect(page.locator("[data-testid=bubble-user][data-queue-paused]")).toHaveCount(3);
  // a message typed while paused joins behind them
  await say(page, "fourth after");
  await expect(page.getByTestId("queue-bar-count")).toHaveText("Paused · 4 waiting");
  await endTurn();
  await expect(page.getByTestId("stop")).toHaveCount(0);
  await page.waitForTimeout(400);
  expect(await submitted()).toEqual(["Refactor the gateway retry code"]);
  await expect(page.getByTestId("queue-bar-count")).toHaveText("Paused · 4 waiting");
  if (SHOTS) await page.screenshot({ path: join(SHOTS, "queue-bar-paused.png"), animations: "disabled" });

  await page.getByTestId("queue-pause").click();
  await expect(bar).not.toHaveAttribute("data-paused", "true");
  await expect.poll(submitted).toEqual(["Refactor the gateway retry code", "first after"]);
  for (const next of ["second after", "third after", "fourth after"]) {
    await endTurn();
    await expect.poll(async () => (await submitted()).at(-1)).toBe(next);
  }
  expect(await submitted()).toEqual(["Refactor the gateway retry code", "first after", "second after", "third after", "fourth after"]);
  await expect(page.getByTestId("queue-bar")).toHaveCount(0);
});

test("Clear asks once more (Clear 3?), Escape and the wait take it back, a second press deletes them all", async ({ page }) => {
  await threeWaiting(page);
  const clear = page.getByTestId("queue-clear");
  await expect(clear).toHaveText("Clear");
  await clear.click();
  await expect(clear).toHaveText("Clear 3?");
  await expect(clear).toHaveAttribute("data-confirm", "true");
  // Escape takes it back, and does not stop the running answer
  await clear.press("Escape");
  await expect(clear).toHaveText("Clear");
  await expect(page.getByTestId("stop")).toBeVisible();
  // so does the wait
  await clear.click();
  await expect(clear).toHaveText("Clear 3?");
  await expect(clear).toHaveText("Clear", { timeout: 6000 });
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(3);
  // two presses: every waiting message is gone, the bar too, and nothing goes out at the turn's end
  await clear.click();
  await clear.click();
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(0);
  await expect(page.getByTestId("queue-bar")).toHaveCount(0);
  await endTurn();
  await page.waitForTimeout(400);
  expect(await submitted()).toEqual(["Refactor the gateway retry code"]);
});

test("at the app's narrowest window the bar stays one line, paused or confirming, in every language", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 600 });
  for (const lang of ["en", "ko", "ja", "zh"] as const) {
    await mock("mock.reset");
    await mock("mock.manual", { bot: "kami" });
    await mock("mock.steerMode", { bot: "kami", mode: "reject" });
    await page.addInitScript((l) => localStorage.setItem("omher.lang", l), lang);
    await threeWaiting(page);
    await page.getByTestId("queue-pause").click();
    await page.getByTestId("queue-clear").click();
    await expect(page.getByTestId("queue-clear")).toHaveAttribute("data-confirm", "true");
    const bar = (await page.getByTestId("queue-bar").boundingBox())!;
    const buttons = await Promise.all(["queue-bar-count", "queue-pause", "queue-clear"].map((id) => page.getByTestId(id).boundingBox()));
    expect(bar.height, lang).toBeLessThanOrEqual(26);
    for (const r of buttons) expect(Math.abs(r!.y + r!.height / 2 - (bar.y + bar.height / 2)), lang).toBeLessThanOrEqual(2);
    // nothing spills past the composer's edge
    const box = (await page.getByTestId("composer-box").boundingBox())!;
    expect(buttons[2]!.x + buttons[2]!.width, lang).toBeLessThanOrEqual(box.x + box.width + 1);
  }
});
