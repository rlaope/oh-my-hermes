// Voice (BOUNDARY rule 54), against the mock bridge. The recording API is faked in the page (an init script provides
// `navigator.mediaDevices.getUserMedia` and `MediaRecorder`; no device is opened) and playback is stubbed (no sound is
// made): a recording's transcript lands in the draft at the caret and nothing is sent; the first-use notice shows once
// per bot; Cancel and Escape discard; no speech, a denied microphone and a missing recording API each say so; read
// aloud plays an answer's parts, Stop stops, and a second answer stops the first; a bot on another computer is off with
// the reason; and the bridge's refusal shows Hermes' own words.
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

type Call = { op: string; params: Record<string, unknown> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);

type Fakes = { deny?: boolean; noApi?: boolean; silent?: boolean; playMs?: number };

/** The page's recording and playback, faked: what was opened, stopped and played is counted on `window.__voice`. */
async function fake(page: Page, opts: Fakes = {}) {
  await page.addInitScript((o: Fakes) => {
    const w = window as unknown as Record<string, any>;
    const v = (w.__voice = { opened: 0, live: 0, recorders: 0, types: [] as string[], plays: [] as string[], pauses: 0 });
    if (o.noApi) {
      Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
      w.MediaRecorder = undefined;
    } else {
      class Track {
        stopped = false;
        stop() {
          if (this.stopped) return;
          this.stopped = true;
          v.live -= 1;
        }
      }
      class Stream {
        tracks = [new Track()];
        constructor() {
          v.live += 1;
        }
        getTracks() {
          return this.tracks;
        }
      }
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          getUserMedia: async () => {
            v.opened += 1;
            if (o.deny) throw new DOMException("Permission denied", "NotAllowedError");
            return new Stream();
          },
        },
      });
      class Recorder {
        static isTypeSupported(t: string) {
          return t === "audio/mp4"; // as WKWebView answers
        }
        state = "inactive";
        mimeType: string;
        ondataavailable: ((e: { data: Blob }) => void) | null = null;
        onstop: (() => void) | null = null;
        onerror: ((e: Event) => void) | null = null;
        constructor(_s: unknown, opt?: { mimeType?: string }) {
          this.mimeType = opt?.mimeType ?? "";
          v.recorders += 1;
          v.types.push(this.mimeType);
        }
        start() {
          this.state = "recording";
        }
        stop() {
          if (this.state === "inactive") return;
          this.state = "inactive";
          setTimeout(() => {
            this.ondataavailable?.({ data: new Blob(o.silent ? [] : ["fake audio bytes"], { type: this.mimeType }) });
            this.onstop?.();
          }, 10);
        }
      }
      w.MediaRecorder = Recorder;
    }
    // playback makes no sound: play() only records what it was asked to play and ends after playMs unless paused
    const halted = new WeakSet<HTMLMediaElement>();
    HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
      v.plays.push(this.src);
      setTimeout(() => {
        if (!halted.has(this)) this.dispatchEvent(new Event("ended"));
      }, o.playMs ?? 120);
      return Promise.resolve();
    };
    HTMLMediaElement.prototype.pause = function (this: HTMLMediaElement) {
      halted.add(this);
      v.pauses += 1;
    };
  }, opts);
}

const voice = (page: Page) => page.evaluate(() => (window as unknown as { __voice: Record<string, any> }).__voice);

async function open(page: Page, opts: Fakes = {}) {
  await fake(page, opts);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** One answer from Kami in the main chat (the mock answers a sent message with `text`). */
async function answer(page: Page, text: string) {
  await mock("mock.answer", { bot: "kami", text });
  await page.getByTestId("composer").fill(`say: ${text.slice(0, 12)}`);
  await page.keyboard.press("Enter");
  const bubble = page.getByTestId("bubble-bot").filter({ hasText: text.slice(0, 20) }).last();
  await expect(bubble).toBeVisible();
  await expect(page.getByTestId("stop")).toHaveCount(0);
  return bubble;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a recording's transcript lands in the draft at the caret and nothing is sent; the notice shows once per bot", async ({ page }) => {
  await open(page);
  const box = page.getByTestId("composer");
  await box.fill("Please ");
  const mic = page.getByTestId("mic");
  await mic.click();
  // first use for Kami: where the recording goes, before anything opens or is sent
  const notice = page.getByTestId("mic-notice");
  await expect(notice).toContainText("Kami’s Hermes");
  await expect(notice).toContainText("its local model when that is installed, otherwise a cloud provider whose key is set");
  expect((await voice(page)).opened).toBe(0);
  expect(await calls("voice.transcribe")).toEqual([]);
  await page.getByTestId("mic-notice-continue").click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await expect(mic).toHaveAttribute("data-state", "recording");
  await expect(page.getByTestId("mic-elapsed")).toHaveText(/^0:0\d$/);
  expect((await voice(page)).live).toBe(1);
  // the webview's own type, asked for by MediaRecorder.isTypeSupported (audio/mp4 in WKWebView)
  expect((await voice(page)).types).toEqual(["audio/mp4"]);
  await mic.click();
  await expect(box).toHaveValue("Please check the deploy logs");
  await expect(page.getByTestId("mic-done")).toHaveText("Transcribed by local");
  expect((await voice(page)).live).toBe(0);
  // only the bot, the bytes and their type went out; nothing was sent to the chat
  const sent = await calls("voice.transcribe");
  expect(sent).toHaveLength(1);
  expect(Object.keys(sent[0].params).sort()).toEqual(["bot", "data_base64", "mime"]);
  expect(sent[0].params).toMatchObject({ bot: "kami", mime: "audio/mp4" });
  expect(await calls("chat.send")).toEqual([]);
  // it joined the draft as typing does: undo takes it back
  await box.focus();
  await page.keyboard.press("ControlOrMeta+z");
  await expect(box).toHaveValue("Please ");
  // the second time there is no notice; Enter stops the recording instead of sending
  await mic.click();
  await expect(page.getByTestId("mic-notice")).toHaveCount(0);
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await box.focus();
  await page.keyboard.press("Enter");
  await expect(box).toHaveValue("Please check the deploy logs");
  expect(await calls("chat.send")).toEqual([]);
  // another bot asks again
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("mic").click();
  await expect(page.getByTestId("mic-notice")).toContainText("Friren’s Hermes");
  await page.getByTestId("mic-notice-cancel").click();
  await expect(page.getByTestId("mic-notice")).toHaveCount(0);
  expect((await voice(page)).opened).toBe(2);
});

test("Cancel and Escape discard a recording: nothing is transcribed and the microphone closes", async ({ page }) => {
  await open(page);
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami"], read: [] })));
  const mic = page.getByTestId("mic");
  await mic.click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await page.getByTestId("mic-cancel").click();
  await expect(page.getByTestId("mic-recording")).toHaveCount(0);
  expect((await voice(page)).live).toBe(0);
  await mic.click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await page.getByTestId("composer").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("mic-recording")).toHaveCount(0);
  expect((await voice(page)).live).toBe(0);
  await expect(page.getByTestId("composer")).toHaveValue("");
  expect(await calls("voice.transcribe")).toEqual([]);
  // Escape ended the recording, not the bot's answer
  expect(await calls("chat.interrupt")).toEqual([]);
  // a transcription on its way is dropped by Cancel too
  await mock("mock.voice", { ms: 1500 });
  await mic.click();
  await mic.click();
  await expect(page.getByTestId("mic-transcribing")).toBeVisible();
  await page.getByTestId("mic-cancel").click();
  await page.waitForTimeout(1800);
  await expect(page.getByTestId("composer")).toHaveValue("");
});

test("the first-use notice keeps the keyboard, Escape is Cancel, and the keyboard goes where it is needed after", async ({ page }) => {
  await open(page);
  const box = page.getByTestId("composer");
  const mic = page.getByTestId("mic");
  await mic.click();
  const notice = page.getByTestId("mic-notice");
  await expect(page.getByTestId("mic-notice-continue")).toBeFocused();
  // Tab and Shift+Tab go round its two buttons only
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("mic-notice-cancel")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("mic-notice-continue")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByTestId("mic-notice-cancel")).toBeFocused();
  // Escape is Cancel: the notice closes, the keyboard is back on the microphone, and Kami's running answer goes on
  await page.keyboard.press("Escape");
  await expect(notice).toHaveCount(0);
  await expect(mic).toBeFocused();
  expect(await calls("chat.interrupt")).toEqual([]);
  // Cancel does the same
  await mic.click();
  await page.getByTestId("mic-notice-cancel").click();
  await expect(notice).toHaveCount(0);
  await expect(mic).toBeFocused();
  expect((await voice(page)).opened).toBe(0);
  // Continue starts the recording with the keyboard in the text box, so Enter stops it there
  await mic.click();
  await page.getByTestId("mic-notice-continue").click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await expect(box).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(box).toHaveValue("check the deploy logs");
  expect(await calls("chat.send")).toEqual([]);
});

test("the read-aloud notice: Escape is Cancel, and the keyboard is back on its button either way", async ({ page }) => {
  await open(page, { playMs: 4000 });
  const bubble = await answer(page, "Read this answer aloud for the notice test.");
  await bubble.hover();
  const btn = bubble.getByTestId("read-aloud");
  await btn.click();
  await expect(page.getByTestId("read-notice-continue")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("read-notice")).toHaveCount(0);
  await expect(btn).toBeFocused();
  expect(await calls("voice.speak")).toEqual([]);
  await btn.click();
  await page.getByTestId("read-notice-continue").click();
  await expect(btn).toHaveAttribute("data-state", "playing");
  await expect(btn).toBeFocused();
  // the focused button is Stop now
  await page.keyboard.press("Enter");
  await expect(btn).toHaveAttribute("data-state", "idle");
});

test("read aloud is off while the microphone records, and a recording stops what plays", async ({ page }) => {
  await open(page, { playMs: 6000 });
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami"], read: ["kami"] })));
  const bubble = await answer(page, "An answer that would be recorded if it played.");
  const btn = bubble.getByTestId("read-aloud");
  // a recording runs: read aloud is off with the reason, and nothing is asked of Hermes' TTS
  await page.getByTestId("mic").click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  await bubble.hover();
  await expect(btn).toHaveAttribute("aria-disabled", "true");
  await expect(btn).toHaveAttribute("title", "Read aloud waits while the microphone records or its recording is being transcribed.");
  await btn.click({ force: true });
  await expect(page.getByTestId("read-error")).toContainText("Read aloud waits while the microphone records");
  expect(await calls("voice.speak")).toEqual([]);
  await page.getByTestId("mic-cancel").click();
  await expect(btn).not.toHaveAttribute("aria-disabled", "true");
  // the other way: an answer plays, and pressing the microphone stops it before recording
  await bubble.hover();
  await btn.click();
  await expect(btn).toHaveAttribute("data-state", "playing");
  await page.getByTestId("mic").click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  // it stopped playing, and stays off while the recording runs
  await expect(btn).toHaveAttribute("data-state", "off");
  await expect(btn).toHaveAttribute("aria-pressed", "false");
  expect((await voice(page)).pauses).toBeGreaterThan(0);
});

test("a hidden window and a chat switch close the microphone; nothing records in the background", async ({ page }) => {
  await open(page);
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami", "friren"], read: [] })));
  const mic = page.getByTestId("mic");
  await mic.click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  expect((await voice(page)).live).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByTestId("mic-recording")).toHaveCount(0);
  expect((await voice(page)).live).toBe(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await mic.click();
  await expect(page.getByTestId("mic-recording")).toBeVisible();
  expect((await voice(page)).live).toBe(1);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("mic")).toHaveAttribute("data-state", "idle");
  expect((await voice(page)).live).toBe(0);
  expect(await calls("voice.transcribe")).toEqual([]);
});

test("an empty transcript says no speech was heard and adds nothing", async ({ page }) => {
  await mock("mock.voice", { transcript: "" });
  await open(page);
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami"], read: [] })));
  await page.getByTestId("mic").click();
  await page.getByTestId("mic").click();
  await expect(page.getByTestId("mic-silent")).toHaveText("No speech was heard. Nothing was added.");
  await expect(page.getByTestId("composer")).toHaveValue("");
});

test("a denied microphone says so and where to allow it", async ({ page }) => {
  await open(page, { deny: true });
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami"], read: [] })));
  await page.getByTestId("mic").click();
  const err = page.getByTestId("mic-error");
  await expect(err.locator("b")).toHaveText("omher may not use the microphone");
  const ua = await page.evaluate(() => navigator.userAgent);
  const where = /Macintosh/.test(ua) ? "System Settings › Privacy & Security › Microphone" : /Windows/.test(ua) ? "Settings › Privacy & security › Microphone" : "On Linux omher allows the microphone itself";
  await expect(err).toContainText(where);
  expect((await voice(page)).live).toBe(0);
  expect(await calls("voice.transcribe")).toEqual([]);
});

test("a window with no recording API shows the microphone off with the reason", async ({ page }) => {
  await open(page, { noApi: true });
  const mic = page.getByTestId("mic");
  await expect(mic).toHaveAttribute("aria-disabled", "true");
  await expect(mic).toHaveAttribute("title", "This window can’t record: its web view has no microphone recording.");
  // off for a stated reason, still reachable: a press says why (aria-disabled, so Playwright is told to press anyway)
  await mic.click({ force: true });
  await expect(page.getByTestId("mic-error")).toContainText("can’t record");
  expect(await calls("voice.info")).toEqual([]);
});

test("the bridge's refusal shows a short headline over Hermes' own words", async ({ page }) => {
  await mock("mock.voice", { next: { op: "transcribe", code: "voice_no_provider", message: "No STT provider available. Install faster-whisper for free local transcription" } });
  await open(page);
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: ["kami"], read: [] })));
  await page.getByTestId("mic").click();
  await page.getByTestId("mic").click();
  const err = page.getByTestId("mic-error");
  await expect(err.locator("b")).toHaveText("Hermes has no speech provider for this");
  await expect(err).toContainText("No STT provider available. Install faster-whisper for free local transcription");
  await expect(page.getByTestId("composer")).toHaveValue("");
});

test("read aloud plays an answer's parts in order, Stop stops, and a second answer stops the first", async ({ page }) => {
  await open(page, { playMs: 4000 });
  const first = await answer(page, "The deploy finished. All checks passed and the release notes are up.");
  await first.hover();
  await first.getByTestId("read-aloud").click();
  // first use for Kami: the text goes to Hermes' TTS, whose default is Microsoft's online service
  const notice = page.getByTestId("read-notice");
  await expect(notice).toContainText("Microsoft’s online text-to-speech service");
  expect(await calls("voice.speak")).toEqual([]);
  await page.getByTestId("read-notice-continue").click();
  const btn = first.getByTestId("read-aloud");
  await expect(btn).toHaveAttribute("data-state", "playing");
  await expect(btn).toHaveAttribute("aria-label", "Stop reading");
  expect((await voice(page)).plays).toHaveLength(1);
  const spoke = await calls("voice.speak");
  expect(spoke.map((c) => [c.params.bot, c.params.part])).toEqual([["kami", 0]]);
  expect(spoke[0].params.text).toBe("The deploy finished. All checks passed and the release notes are up.");
  await btn.click();
  await expect(btn).toHaveAttribute("data-state", "idle");
  expect((await voice(page)).pauses).toBeGreaterThan(0);

  const second = await answer(page, "Second answer: the staging cluster is healthy again.");
  await first.hover();
  await first.getByTestId("read-aloud").click();
  await expect(first.getByTestId("read-aloud")).toHaveAttribute("data-state", "playing");
  await second.hover();
  await second.getByTestId("read-aloud").click();
  await expect(second.getByTestId("read-aloud")).toHaveAttribute("data-state", "playing");
  await expect(first.getByTestId("read-aloud")).toHaveAttribute("data-state", "idle");
  // a chat switch stops it
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("read-aloud").first()).toHaveAttribute("data-state", "idle");
});

test("a long answer is read in parts, one after another", async ({ page }) => {
  await mock("mock.voice", { parts: 3 });
  await open(page, { playMs: 150 });
  await page.evaluate(() => localStorage.setItem("omher.voice.ok", JSON.stringify({ mic: [], read: ["kami"] })));
  const bubble = await answer(page, "A long answer read in three parts by the mock.");
  await bubble.hover();
  await bubble.getByTestId("read-aloud").click();
  await expect(page.getByTestId("read-status")).toContainText("part 1 of 3");
  await expect(bubble.getByTestId("read-aloud")).toHaveAttribute("data-state", "idle", { timeout: 5000 });
  expect((await calls("voice.speak")).map((c) => c.params.part)).toEqual([0, 1, 2]);
  expect((await voice(page)).plays).toHaveLength(3);
});

test("a bot on another computer has voice off with the reason, and nothing is asked for it", async ({ page }) => {
  await mock("peers.attach", { peer: "mac", label: "Mac mini", host: "demo@mini.local", url: `ws://127.0.0.1:5999/?token=${"0".repeat(32)}` });
  await page.addInitScript(() => localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren", "mac:mini"])));
  await open(page);
  await page.getByTestId("bot-mac:mini").click();
  const mic = page.getByTestId("mic");
  await expect(mic).toHaveAttribute("aria-disabled", "true");
  await expect(mic).toHaveAttribute("title", "Voice works with bots on this computer only.");
  await mic.click({ force: true });
  await expect(page.getByTestId("mic-error")).toContainText("Voice works with bots on this computer only.");
  // an answer of that bot: its read aloud is off with the same reason
  await mock("mock.answer", { bot: "mac:mini", text: "The Mac mini finished its backup." });
  await page.getByTestId("composer").fill("backup done?");
  await page.keyboard.press("Enter");
  const said = page.getByTestId("bubble-bot").filter({ hasText: "finished its backup" }).last();
  await expect(said).toBeVisible();
  await said.hover();
  await expect(said.getByTestId("read-aloud")).toHaveAttribute("aria-disabled", "true");
  await said.getByTestId("read-aloud").click({ force: true });
  await expect(page.getByTestId("read-error")).toContainText("Voice works with bots on this computer only.");
  for (const op of ["voice.info", "voice.transcribe", "voice.speak"]) expect(await calls(op)).toEqual([]);
});
