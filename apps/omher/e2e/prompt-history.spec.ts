// ArrowUp/ArrowDown in a bot chat's composer recall the person's earlier prompts of that chat, like a shell: ArrowUp on
// the first line shows the previous one (newest first, caret at the end), ArrowDown on the last line goes newer and past
// the newest gives back the draft. Open pickers keep their arrows; middle lines of a multi-line draft only move the caret
// (Alt+arrow recalls from any line).
// A prompt held in omher's queue joins the history once it is sent; text the app puts in the box ends a walk.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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
const sent = async () => ((await mock("mock.calls")).calls as { op: string; params: any }[]).filter((c) => c.op === "chat.send").map((c) => c.params.text as string);
const steered = async () => ((await mock("mock.calls")).calls as { op: string; params: any }[]).filter((c) => c.op === "chat.steer").map((c) => c.params.text as string);

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function openFriren(page: Page) {
  await page.goto("/");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("header").getByText("Friren", { exact: true })).toBeVisible();
  await expect(page.getByTestId("composer")).toBeEnabled();
  await page.getByTestId("composer").click();
}
async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
  const row = page.getByTestId("bubble-user").filter({ hasText: text }).last();
  await expect(row).toBeVisible();
  // typed while the last answer still runs, it is steered in (or, refused, waits in omher's queue) and is history
  // only once the bot has it
  await expect(row).not.toHaveAttribute("data-held", /.*/, { timeout: 15000 });
}
const caret = (page: Page) => page.getByTestId("composer").evaluate((el: HTMLTextAreaElement) => [el.selectionStart, el.selectionEnd]);

test("ArrowUp recalls the two sent prompts newest first; ArrowDown walks back to the unsent draft", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await say(page, "summarise the OG outage thread");
  await say(page, "list the three causes");
  await box.fill("half typed");

  await box.press("ArrowUp");
  await expect(box).toHaveValue("list the three causes");
  expect(await caret(page)).toEqual([21, 21]);
  await box.press("ArrowUp");
  await expect(box).toHaveValue("summarise the OG outage thread");
  await box.press("ArrowDown");
  await expect(box).toHaveValue("list the three causes");
  await box.press("ArrowDown");
  await expect(box).toHaveValue("half typed");
  await box.press("ArrowDown"); // past the draft: nothing more
  await expect(box).toHaveValue("half typed");

  // an arrow while an input method composes is the IME's, not a recall
  await box.dispatchEvent("keydown", { key: "ArrowUp", isComposing: true, bubbles: true, cancelable: true });
  await expect(box).toHaveValue("half typed");

  // an edited recalled prompt goes out as edited; the history keeps the original
  await box.press("ArrowUp");
  await box.press("End");
  await box.pressSequentially(" again");
  await box.press("Enter");
  const again = page.getByTestId("bubble-user").filter({ hasText: "list the three causes again" });
  await expect(again).toBeVisible();
  // sent, or steered into the turn still running (a message typed mid-answer joins it): the bot has it
  await expect(again).not.toHaveAttribute("data-held", /.*/, { timeout: 15000 });
  await expect.poll(async () => [...(await sent()), ...(await steered())], { timeout: 15000 }).toContain("list the three causes again");
  await box.press("ArrowUp");
  await expect(box).toHaveValue("list the three causes again");
  await box.press("ArrowUp");
  await expect(box).toHaveValue("list the three causes");
});

test("leaving the chat mid-walk keeps the unsent draft, not the prompt on show", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await say(page, "an earlier prompt");
  await box.fill("my unsent draft");
  await box.press("ArrowUp");
  await expect(box).toHaveValue("an earlier prompt");
  await page.getByTestId("bot-kami").click();
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("composer")).toHaveValue("my unsent draft");
});

test("an open $ skill picker keeps ArrowUp/ArrowDown for its highlight", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await say(page, "an earlier prompt");
  await box.pressSequentially("fix this $pl");
  const opts = page.getByTestId("skill-option");
  await expect(opts).toHaveCount(2);
  await expect(opts.first()).toHaveAttribute("aria-selected", "true");
  await box.press("ArrowDown");
  await expect(opts.nth(1)).toHaveAttribute("aria-selected", "true");
  await box.press("ArrowUp");
  await expect(opts.first()).toHaveAttribute("aria-selected", "true");
  await expect(box).toHaveValue("fix this $pl");
});

test("arrows on the middle line of a multi-line draft only move the caret", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await say(page, "an earlier prompt");
  const draft = "line one\nline two\nline three";
  await box.fill(draft);
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(13, 13)); // inside "line two"
  await box.press("ArrowUp");
  await expect(box).toHaveValue(draft);
  expect((await caret(page))[0]).toBeLessThan(9); // moved to line one
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(13, 13));
  await box.press("ArrowDown");
  await expect(box).toHaveValue(draft);
  expect((await caret(page))[0]).toBeGreaterThan(17); // moved to line three
  // from the first line the same key recalls
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(2, 2));
  await box.press("ArrowUp");
  await expect(box).toHaveValue("an earlier prompt");
  await box.press("ArrowDown");
  await expect(box).toHaveValue(draft);
});

test("Alt+ArrowUp/Down recall from any line of a multi-line draft", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await say(page, "an earlier prompt");
  const draft = "line one\nline two\nline three";
  await box.fill(draft);
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(13, 13)); // inside "line two"
  await box.press("Alt+ArrowUp");
  await expect(box).toHaveValue("an earlier prompt");
  await box.press("Alt+ArrowDown");
  await expect(box).toHaveValue(draft);
});

test("a held prompt is not recalled until it is sent; text the app puts in the box ends the walk", async ({ page }) => {
  await mock("mock.manual", { bot: "kami" });
  // Hermes refuses the steer: what is typed mid-answer waits in omher's queue
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const box = page.getByTestId("composer");
  const held = (text: string) => page.locator("[data-testid=bubble-user][data-held]", { hasText: text });
  await say(page, "Refactor the gateway retry code");
  await expect(page.getByTestId("stop")).toBeVisible();
  await box.fill("and add a test for it");
  await box.press("Enter");
  await expect(held("and add a test for it")).toBeVisible();

  // the held row waits in omher's queue: ArrowUp skips it
  await box.press("ArrowUp");
  await expect(box).toHaveValue("Refactor the gateway retry code");
  // its ↓ puts it in the box (store ui.draft) mid-walk: that text is the draft now, an arrow never swaps it away
  await held("and add a test for it").getByTestId("queue-edit").click();
  const injected = "and add a test for it\nRefactor the gateway retry code";
  await expect(box).toHaveValue(injected);
  await box.press("ArrowDown");
  await expect(box).toHaveValue(injected);

  // once sent, it is history
  await box.fill("also keep the old timeout");
  await box.press("Enter");
  await expect(held("also keep the old timeout")).toBeVisible();
  await box.press("ArrowUp");
  await expect(box).toHaveValue("Refactor the gateway retry code");
  await box.fill("");
  await mock("mock.endTurn", { bot: "kami", outcome: "done" });
  await expect.poll(sent, { timeout: 15000 }).toContain("also keep the old timeout");
  await expect(held("also keep the old timeout")).toHaveCount(0);
  await box.press("ArrowUp");
  await expect(box).toHaveValue("also keep the old timeout");
});
