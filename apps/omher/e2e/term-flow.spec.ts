// Output flow of a SESSIONS terminal (mock host): the page acknowledges every message its terminal has taken, with
// that message's byte count and in the order they came, and a burst of resizes reaches the program as one resize
// with the size it ended on. In the app the shell reads a program only as far ahead of the page as these
// acknowledgements allow (src-tauri/src/sessions.rs FLOW_HIGH / FLOW_LOW).
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
/** RESIZE_SETTLE_MS in src/sessions/sessions.ts. */
const SETTLE = 32;
/** One frame of a drag at 60 Hz. */
const FRAME = 16;

test.use({ colorScheme: "dark" });

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

type Flow = { op: "feed" | "ack"; id: number; bytes: number };
type Call = { op: string; id?: number; cols?: number; rows?: number; bytes?: number };
const flow = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionFlow?: Flow[] }).__omherSessionFlow ?? []);
const calls = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []);
const resizes = async (page: Page) => (await calls(page)).filter((c) => c.op === "resize").map((c) => ({ cols: c.cols, rows: c.rows }));
const bytes = (text: string) => new TextEncoder().encode(text).length;

/** A Grok session: the agent that opens as its own terminal. */
async function terminal(page: Page) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.resume");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "grok"];
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-grok").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  // the banner has been printed, taken by the terminal and acknowledged
  await expect.poll(async () => (await flow(page)).filter((f) => f.op === "ack").length).toBe(1);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("every message the program prints is acknowledged once, with its byte count, in order", async ({ page }) => {
  await terminal(page);
  await page.locator(".xterm-helper-textarea").focus();
  // each key is echoed as its own message; Enter is answered with one message, Ctrl+C with one more
  await page.keyboard.type("hi");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("you said: hi");
  await page.keyboard.press("Control+c");
  await expect(page.locator(".xterm-rows")).toContainText("^C");
  await expect.poll(async () => (await flow(page)).filter((f) => f.op === "ack").length).toBe(5);

  const all = await flow(page);
  const feeds = all.filter((f) => f.op === "feed");
  const acks = all.filter((f) => f.op === "ack");
  // one session; the banner, "h", "i", the answer with the next prompt, "^C" with the next prompt
  expect(new Set(all.map((f) => f.id)).size).toBe(1);
  const prompt = "\x1b[2m›\x1b[0m ";
  const answer = `\r\n\x1b[2m(mock) you said:\x1b[0m hi\r\n${prompt}`;
  expect(feeds.slice(1).map((f) => f.bytes)).toEqual([1, 1, bytes(answer), bytes(`^C\r\n${prompt}`)]);
  // bytes, as the shell counts them, not characters: the prompt's "›" is one character and three bytes
  expect(bytes(answer)).toBe(answer.length + 2);
  // the acknowledgements are the messages: as many, of the same sizes, in the same order
  expect(acks.map((a) => a.bytes)).toEqual(feeds.map((f) => f.bytes));
  // and none comes before its message was handed over: the n-th ack is after the n-th feed
  let fed = 0;
  let acked = 0;
  for (const step of all) {
    if (step.op === "feed") fed += 1;
    else expect(++acked).toBeLessThanOrEqual(fed);
  }
  // the host's call log has the same acknowledgements, as the shell would get them
  expect((await calls(page)).filter((c) => c.op === "ack").map((c) => c.bytes)).toEqual(feeds.map((f) => f.bytes));
});

test("a burst of resizes ends as one resize with the last size", async ({ page }) => {
  await terminal(page);
  const box = page.getByTestId("terminal");
  const drawn = () => page.locator(".xterm-screen").evaluate((el) => (el as HTMLElement).style.width);
  /** Narrow the terminal's box (null = as it was) and wait until the terminal has refitted to it. */
  const width = async (px: number | null) => {
    const before = await drawn();
    await box.evaluate((el, w) => {
      (el as HTMLElement).style.maxWidth = w === null ? "" : `${w}px`;
    }, px);
    await expect.poll(drawn).not.toBe(before);
  };
  const full = (await box.boundingBox())!.width;
  expect(await resizes(page)).toEqual([]);

  // one settled change, and back: the sizes of the narrow box and of the full one
  await width(full - 400);
  await expect.poll(() => resizes(page)).toHaveLength(1);
  const narrow = (await resizes(page))[0];
  await width(null);
  await expect.poll(() => resizes(page)).toHaveLength(2);
  const wide = (await resizes(page))[1];
  expect(wide.rows).toBe(narrow.rows);
  expect(wide.cols).toBeGreaterThan(narrow.cols! + 20);

  // the burst: five widths one frame apart, as a drag gives them. The page's timers are held and moved by hand, so
  // the frames and the wait after the last one are counted here and not by how busy the machine is
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  for (const cut of [80, 160, 240, 320, 400]) {
    await width(full - cut);
    await page.clock.runFor(FRAME);
  }
  // five sizes came and went, and the program was told none of them
  expect(await resizes(page)).toHaveLength(2);
  await page.clock.runFor(SETTLE - FRAME - 2);
  expect(await resizes(page)).toHaveLength(2);
  // once the size has stood still: one resize, with the size the burst ended on
  await page.clock.runFor(4);
  await expect.poll(() => resizes(page)).toHaveLength(3);
  expect((await resizes(page))[2]).toEqual(narrow);
  await page.clock.runFor(1000);
  expect(await resizes(page)).toHaveLength(3);

  // a size that comes back to the one the program already has is not sent again
  await width(full - 200);
  await page.clock.runFor(FRAME);
  await width(full - 400);
  await page.clock.runFor(1000);
  expect(await resizes(page)).toHaveLength(3);
});
