// Sounds (Settings › General): four short Web Audio sounds. AudioContext is a counting fake here, so nothing plays
// on the machine's speakers; the tests count the contexts made and the oscillators started.
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (SOUNDS_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.SOUNDS_SHOTS || "test-results";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "s1") res(msg);
    };
    ws.send(JSON.stringify({ id: "s1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

/** A counting AudioContext (and webkitAudioContext); `sounds` presets the switch. The window is out of sight. */
async function fakeAudio(page: Page, sounds?: "on" | "off") {
  await page.addInitScript((pref) => {
    const w = window as any;
    w.__audio = { made: 0, started: 0 };
    const param = { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} };
    class FakeAudioContext {
      state = "running";
      currentTime = 0;
      destination = {};
      constructor() {
        w.__audio.made += 1;
      }
      createOscillator() {
        return { type: "sine", frequency: param, connect() {}, start: () => (w.__audio.started += 1), stop() {} };
      }
      createGain() {
        return { gain: param, connect() {} };
      }
      resume() {
        return Promise.resolve();
      }
    }
    w.AudioContext = FakeAudioContext;
    w.webkitAudioContext = FakeAudioContext;
    if (pref) localStorage.setItem("omher.sounds", pref);
    document.hasFocus = () => false;
  }, sounds ?? null);
}

const audio = (page: Page) => page.evaluate(() => (window as any).__audio as { made: number; started: number });

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

async function send(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}

const errorEnd = (bot: string) => mock("mock.emit", { events: [{ event: "turn.end", bot, outcome: "error", error: "boom" }] });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Settings › General: Sounds is on, Play previews the chime, Off disables Play and stays off", async ({ page }) => {
  await fakeAudio(page);
  await open(page);
  await page.getByTestId("nav-settings").click();
  const seg = page.getByTestId("sounds-seg");
  const play = page.getByTestId("sounds-play");
  await expect(seg.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  expect(await audio(page)).toEqual({ made: 0, started: 0 });

  await play.click();
  await expect.poll(() => audio(page)).toEqual({ made: 1, started: 2 });

  await seg.getByRole("radio", { name: "Off" }).click();
  await expect(play).toBeDisabled();
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("sounds-seg").getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("sounds-play")).toBeDisabled();
  expect(await audio(page)).toEqual({ made: 0, started: 0 });
});

test("off: a send, a reply, an approval and an error make no AudioContext", async ({ page }) => {
  await fakeAudio(page, "off");
  await open(page);
  await send(page, "check the 502s");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "keep-alive" }).first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(1600);
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await expect(page.getByTestId("bot-friren").getByTestId("needs")).toBeVisible();
  await page.waitForTimeout(1600);
  await errorEnd("friren");
  await page.waitForTimeout(500);
  expect(await audio(page)).toEqual({ made: 0, started: 0 });
});

test("on: a send ticks, a reply out of sight pops, a new ask chimes, an error sounds its note", async ({ page }) => {
  await fakeAudio(page);
  await open(page);
  await send(page, "check the 502s");
  // one context, one oscillator: the tick
  await expect.poll(() => audio(page)).toEqual({ made: 1, started: 1 });
  // the answer lands ~2.5 s later while the window is out of sight: the two-note pop
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "keep-alive" }).first()).toBeVisible({ timeout: 10_000 });
  await expect.poll(async () => (await audio(page)).started).toBe(3);
  await page.waitForTimeout(1600);

  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await expect.poll(async () => (await audio(page)).started).toBe(5);
  await page.waitForTimeout(1600);
  await errorEnd("friren");
  await expect.poll(async () => (await audio(page)).started).toBe(6);
  expect((await audio(page)).made).toBe(1);
});

test("first load with an ask already waiting is silent", async ({ page }) => {
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await fakeAudio(page);
  await open(page);
  // the ask came back with the chat (the bridge's replay) ...
  await expect(page.getByTestId("bot-friren").getByTestId("needs")).toBeVisible();
  await page.waitForTimeout(2000);
  // ... and made no sound
  expect(await audio(page)).toEqual({ made: 0, started: 0 });
});

test("screenshots: the Sounds row in Settings › General, dark and light", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fakeAudio(page);
  for (const theme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await open(page);
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("sounds-seg").scrollIntoViewIfNeeded();
    await page.mouse.move(700, 880);
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, `settings-sounds-${theme}-after.png`) });
  }
});
