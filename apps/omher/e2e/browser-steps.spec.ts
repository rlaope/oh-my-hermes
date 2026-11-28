// A bot's browser steps (BOUNDARY rule 53), against the mock bridge's `/browser` turn: a `browser_exec` step reads as
// the label its code starts with, one without a label as a plain line, a CDP step as its method, a dialog and a saved
// login as their action; a step whose capture the bridge read shows a thumbnail that opens the lightbox, a
// `computer_use` capture too; and the text the bot typed into the page (in the mocked code, CDP params and dialog
// prompt) never appears anywhere in the page.
//
// The mock bridge scrubs the mocked calls with its own copy of the bridge's rules (mock-bridge.mjs `bridgeStep`), so
// these tests cover the page side: what the page does with the events the bridge sends. They cannot catch a bridge
// regression; that guarantee is pinned in `bridge/tests/test_browser_steps.py` and `tests/test_omher_boundary.py`.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
/** What the mocked calls type into the page (e2e/mock-bridge.mjs BROWSER_TYPED). */
const TYPED = "hunter2-typed-in-page";

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

/** Runs the scripted browser turn in Kami's chat and opens its step list once it is done. */
async function browserTurn(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await page.getByTestId("composer").fill("/browser log in to the shop");
  await page.getByTestId("composer").press("Enter");
  const act = page.locator('[data-testid=activity][data-state=done]').last();
  await expect(act.getByTestId("activity-text")).toContainText("6 steps");
  await act.getByTestId("activity-toggle").click();
  const steps = act.getByTestId("activity-details").getByTestId("activity-step");
  await expect(steps).toHaveCount(6);
  return steps;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("each browser step reads as its label, method or action; one without a label is a plain line", async ({ page }) => {
  const steps = await browserTurn(page);
  await expect(steps.nth(0)).toContainText("Opening the shop's login page");
  await expect(steps.nth(1).locator(".k")).toHaveText("Used the browser");
  await expect(steps.nth(1).locator(".v")).toHaveCount(0);
  await expect(steps.nth(2)).toContainText("Ran browser command");
  await expect(steps.nth(2).locator("code")).toHaveText("Input.insertText");
  await expect(steps.nth(3).locator(".k")).toHaveText("Accepted a page dialog");
  await expect(steps.nth(4).locator(".k")).toHaveText("Filled in a saved login");
  await expect(steps.nth(5).locator(".k")).toHaveText("Looked at the screen in Safari");
});

test("a captured step shows a thumbnail that opens the lightbox, and Escape closes it", async ({ page }) => {
  const steps = await browserTurn(page);
  // the two steps Hermes named a capture for: the browser_exec with a label and the computer_use capture
  const shots = page.getByTestId("activity-step-shot");
  await expect(shots).toHaveCount(2);
  await expect(steps.nth(0).getByTestId("activity-step-shot")).toHaveAttribute("aria-label", "Open the screenshot of Opening the shop's login page");
  for (const i of [1, 2, 3, 4]) await expect(steps.nth(i).getByTestId("activity-step-shot")).toHaveCount(0);
  const thumb = steps.nth(0).getByTestId("activity-step-shot");
  await expect(thumb.locator("img")).toHaveJSProperty("naturalWidth", 64);
  // keyboard reachable: focus it and press Enter
  await thumb.focus();
  await expect(thumb).toBeFocused();
  await page.keyboard.press("Enter");
  const box = page.getByTestId("lightbox");
  await expect(box).toBeVisible();
  await expect(box).toHaveAttribute("aria-label", "Screenshot of Opening the shop's login page");
  await page.keyboard.press("Escape");
  await expect(box).toHaveCount(0);
  // the live activity line itself has no picture: only the step list does
  await expect(page.locator('[data-testid=activity] .act-h img')).toHaveCount(0);
});

test("an open lightbox stays open when newer screenshots elsewhere push its thumbnail out", async ({ page }) => {
  const steps = await browserTurn(page);
  const thumb = steps.nth(0).getByTestId("activity-step-shot");
  const src = await thumb.locator("img").getAttribute("src");
  await thumb.click();
  const box = page.getByTestId("lightbox");
  await expect(box).toBeVisible();
  // 24 captures in three other chats, 8 each (the per-chat bound): past the page's bound of 16 in all, so Kami's two
  // older ones are dropped while the lightbox is open
  const events: Record<string, unknown>[] = [];
  for (const bot of ["friren", "default", "omh-tui"]) {
    events.push({ event: "turn.start", bot });
    for (let i = 0; i < 8; i += 1) {
      const tool_id = `${bot}-c${i}`;
      events.push({ event: "tool.start", bot, tool_id, name: "computer_use", detail: "", action: "capture" });
      events.push({ event: "tool.shot", bot, tool_id, mime: "image/png", data_base64: src!.split(",")[1] });
    }
  }
  await mock("mock.emit", { events });
  await expect(steps.nth(0).getByTestId("activity-step-shot")).toHaveCount(0);
  await expect(steps.nth(5).getByTestId("activity-step-shot")).toHaveCount(0);
  // the image it opened with is still there until the person closes it
  await expect(box).toBeVisible();
  await expect(box.locator("img")).toHaveAttribute("src", src!);
  await page.keyboard.press("Escape");
  await expect(box).toHaveCount(0);
});

test("a computer_use capture shows a thumbnail too", async ({ page }) => {
  const steps = await browserTurn(page);
  const thumb = steps.nth(5).getByTestId("activity-step-shot");
  await expect(thumb).toHaveAttribute("aria-label", "Open the screenshot of Looked at the screen in Safari");
  await thumb.click();
  await expect(page.getByTestId("lightbox")).toBeVisible();
  await page.getByTestId("lightbox").click({ position: { x: 5, y: 5 } });
  await expect(page.getByTestId("lightbox")).toHaveCount(0);
});

test("what the bot typed into the page never appears in it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // every text the live line shows on the way, recorded from inside the page
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as any).__seen = seen;
    new MutationObserver(() => seen.push(document.body.innerText)).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await page.getByTestId("composer").fill("/browser log in to the shop");
  await page.getByTestId("composer").press("Enter");
  const act = page.locator('[data-testid=activity][data-state=done]').last();
  await expect(act.getByTestId("activity-text")).toContainText("6 steps");
  await act.getByTestId("activity-toggle").click();
  await expect(act.getByTestId("activity-step")).toHaveCount(6);
  const html = await page.content();
  for (const leak of [TYPED, "fill_input", "prompt_text", "Input.insertText\",", "h_7f2c"]) expect(html).not.toContain(leak);
  const seen: string[] = await page.evaluate(() => (window as any).__seen);
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.some((t) => t.includes(TYPED) || t.includes("fill_input"))).toBe(false);
});
