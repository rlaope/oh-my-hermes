// Hand to bot from an answer (BOUNDARY rule 58): Kami's answer goes to a new Friren thread only on Hand over (one
// thread.create, one chat.send there), the person stays in Kami's chat, and the card under the answer follows that
// thread: working, then Friren's answer, which Give to Kami sends once into Kami's chat as the person's own message.
// A mention only suggests (its chip opens the popover and sends nothing). Shots: OMHER_SHOTS=<dir>.
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
const calls = async (op: string) => ((await mock("mock.calls")).calls as { op: string; params: any }[]).filter((c) => c.op === op);
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name) });
};

test.beforeEach(async () => {
  await mock("mock.reset");
  // Friren's thread runs no script: the test drives its turn
  await mock("mock.manual", { bot: "friren" });
});

/** Kami's chat, and the answer the tests hand over. */
async function kami(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const answer = page.getByTestId("bubble-bot").filter({ hasText: "upstream timeout" });
  await expect(answer).toBeVisible();
  return answer;
}

/** Hand Kami's answer to Friren with a note; returns the card and its thread. `shots`: save the popover's. */
async function handToFriren(page: Page, note: string, shots = false) {
  const answer = await kami(page);
  await answer.hover();
  await answer.getByTestId("handoff-action").click();
  const pop = page.getByTestId("handoff-popover");
  await expect(pop).toBeVisible();
  await pop.locator('[data-testid=handoff-bot][data-bot="friren"]').click();
  await pop.getByTestId("handoff-note").fill(note);
  if (shots) await shot(page, "1-popover.png");
  await pop.getByTestId("handoff-confirm").click();
  await expect(pop).toHaveCount(0);
  const card = page.getByTestId("handoff-card");
  await expect(card).toBeVisible();
  const thread = (await card.getAttribute("data-thread"))!;
  return { card, thread };
}

test("Hand to bot: a Friren thread gets the note and the quoted answer, the card follows it, Give sends its answer back once", async ({ page }) => {
  const { card, thread } = await handToFriren(page, "Check this against the keep-alive docs", true);
  // one thread, one first message, in Friren; the person is still in Kami's main chat
  await expect.poll(async () => (await calls("thread.create")).map((c) => [c.params.bot, c.params.title])).toEqual([["friren", "From Kami: Check this against the keep-alive docs"]]);
  const first = (await calls("chat.send")).map((c) => c.params);
  expect(first).toHaveLength(1);
  expect(first[0]).toMatchObject({ bot: "friren", session: thread });
  expect(first[0].text).toMatch(
    /^Handoff from omher: Kami wrote the answer below, and the person handed it to you\.\n\nNote: Check this against the keep-alive docs\n\n> 확인했어요\./,
  );
  expect(first[0].text).toContain("upstream timeout");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("thread-chat")).toHaveCount(0);
  // working, right under that answer, announced politely
  await expect(card).toHaveAttribute("data-state", "working");
  await expect(card.getByTestId("handoff-state")).toHaveText("Friren is working on it");
  await expect(card.getByTestId("handoff-state")).toHaveAttribute("aria-live", "polite");
  await expect(card.getByTestId("handoff-give")).toHaveCount(0);
  await shot(page, "2-card-working.png");

  // Friren answers in that thread and the turn ends
  await mock("mock.threadAnswer", { bot: "friren", thread, text: "The keep-alive docs say 5 s idle, so the 3 retries fit.\nSource: docs/keepalive.md" });
  await expect(card).toHaveAttribute("data-state", "done");
  await expect(card.getByTestId("handoff-answer")).toContainText("The keep-alive docs say 5 s idle");
  const give = card.getByTestId("handoff-give");
  await expect(give).toHaveText("Give to Kami");
  await shot(page, "3-card-done.png");

  const before = (await calls("chat.send")).length;
  await give.click();
  await expect(give).toHaveText("Given");
  await expect(give).toBeDisabled();
  await expect.poll(async () => (await calls("chat.send")).slice(before).map((c) => c.params)).toEqual([
    { bot: "kami", text: "Answer from Friren:\n\nThe keep-alive docs say 5 s idle, so the 3 retries fit.\nSource: docs/keepalive.md" },
  ]);
  // the person's own message in Kami's chat; nothing else went anywhere
  await expect(page.getByTestId("bubble-user").filter({ hasText: "Answer from Friren:" })).toBeVisible();
  await page.waitForTimeout(300);
  expect((await calls("chat.send")).length).toBe(before + 1);
  expect((await calls("thread.create")).length).toBe(1);

  // Open thread opens Friren's thread
  await card.getByTestId("handoff-open").click();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", thread);
});

test("a mention suggests: the chip opens the popover with that bot chosen and sends nothing; keys move and Escape gives focus back", async ({ page }) => {
  await kami(page);
  const said = page.getByTestId("bubble-bot").filter({ hasText: "keep-alive 문서는" });
  const chip = said.locator('[data-testid=handoff-chip][data-to="friren"]');
  await expect(chip).toHaveText("Hand this to Friren");
  // never one for the answer's own bot
  await expect(said.locator('[data-testid=handoff-chip][data-to="kami"]')).toHaveCount(0);
  await chip.click();
  const pop = page.getByTestId("handoff-popover");
  await expect(pop).toBeVisible();
  const friren = pop.locator('[data-testid=handoff-bot][data-bot="friren"]');
  await expect(friren).toHaveAttribute("aria-selected", "true");
  await expect(friren).toBeFocused();
  // the answer's own bot is not offered
  await expect(pop.locator('[data-testid=handoff-bot][data-bot="kami"]')).toHaveCount(0);
  await page.keyboard.press("ArrowDown");
  await expect(friren).toHaveAttribute("aria-selected", "false");
  await page.keyboard.press("ArrowUp");
  await expect(friren).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Escape");
  await expect(pop).toHaveCount(0);
  await expect(chip).toBeFocused();
  await page.waitForTimeout(300);
  expect(await calls("thread.create")).toEqual([]);
  expect(await calls("chat.send")).toEqual([]);
});

test("the narrowest window, all four languages: the chips, the popover and the card fit", async ({ page }) => {
  // the app's minimum window (tauri.conf.json minWidth 900)
  await page.setViewportSize({ width: 900, height: 600 });
  const titles: Record<string, string> = { en: "Handed to Friren", ko: "Friren에게 넘겼어요", ja: "Friren に渡しました", zh: "已交给 Friren" };
  for (const lang of ["en", "ko", "ja", "zh"]) {
    await page.addInitScript((l) => localStorage.setItem("omher.lang", l), lang);
    const { card, thread } = await handToFriren(page, "");
    await expect(card.locator(".hf-title")).toHaveText(titles[lang]);
    await mock("mock.threadAnswer", { bot: "friren", thread, text: "Five seconds, per docs/keepalive.md." });
    await expect(card).toHaveAttribute("data-state", "done");
    const pane = page.getByTestId("timeline");
    const [c, p] = await Promise.all([card.boundingBox(), pane.boundingBox()]);
    expect(c!.x + c!.width, lang).toBeLessThanOrEqual(p!.x + p!.width);
    for (const b of await card.locator("button").all()) {
      const r = (await b.boundingBox())!;
      expect(r.x + r.width, lang).toBeLessThanOrEqual(c!.x + c!.width);
    }
    expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth), lang).toBe(true);
    for (const chip of await page.getByTestId("handoff-chip").all()) {
      const r = (await chip.boundingBox())!;
      expect(r.x + r.width, lang).toBeLessThanOrEqual(p!.x + p!.width);
    }
    // the popover from a chip, inside the window
    await page.getByTestId("handoff-chip").first().click();
    const pop = (await page.getByTestId("handoff-popover").boundingBox())!;
    expect(pop.x, lang).toBeGreaterThanOrEqual(0);
    expect(pop.x + pop.width, lang).toBeLessThanOrEqual(900);
    expect(pop.y, lang).toBeGreaterThanOrEqual(0);
    expect(pop.y + pop.height, lang).toBeLessThanOrEqual(600);
    await page.keyboard.press("Escape");
  }
});

test("stopped: a turn that ends interrupted shows the outcome and offers no Give", async ({ page }) => {
  const { card, thread } = await handToFriren(page, "");
  await expect(card).toHaveAttribute("data-state", "working");
  await mock("mock.emit", { events: [{ event: "approval.request", bot: "friren", session: thread, request_id: "hf-r1", title: "Run a command", command: "ls", choices: ["once", "deny"] }] });
  await expect(card).toHaveAttribute("data-state", "waiting");
  await expect(card.getByTestId("handoff-state")).toHaveText("Friren is waiting for you");
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "friren", session: thread, outcome: "interrupted" }] });
  await expect(card).toHaveAttribute("data-state", "stopped");
  await expect(card.getByTestId("handoff-state")).toHaveText("Friren stopped before answering");
  await expect(card.getByTestId("handoff-give")).toHaveCount(0);
  await expect(card.getByTestId("handoff-open")).toBeVisible();
});

test("a held Enter hands over once: its repeat neither opens the popover again nor confirms a second thread", async ({ page }) => {
  const answer = await kami(page);
  await answer.hover();
  await answer.getByTestId("handoff-action").click();
  const pop = page.getByTestId("handoff-popover");
  await pop.getByTestId("handoff-note").fill("once");
  await pop.getByTestId("handoff-note").focus();
  await page.keyboard.down("Enter");
  await expect(pop).toHaveCount(0);
  await expect(answer.getByTestId("handoff-action")).toBeFocused();
  // the key is still held: each further keydown is a repeat
  for (let i = 0; i < 4; i++) {
    await page.keyboard.down("Enter");
    await page.waitForTimeout(80);
  }
  await page.keyboard.up("Enter");
  await expect(pop).toHaveCount(0);
  await page.waitForTimeout(300);
  expect((await calls("thread.create")).length).toBe(1);
  await expect(page.getByTestId("handoff-card")).toHaveCount(1);
});

test("the picked bot goes offline while the popover is open: the first bot left is picked", async ({ page }) => {
  const answer = await kami(page);
  await answer.hover();
  await answer.getByTestId("handoff-action").click();
  const pop = page.getByTestId("handoff-popover");
  const friren = pop.locator('[data-testid=handoff-bot][data-bot="friren"]');
  await friren.click();
  await expect(friren).toHaveAttribute("aria-selected", "true");
  await mock("mock.botStatus", { bot: "friren", status: "offline" });
  await expect(friren).toHaveCount(0);
  const first = pop.getByTestId("handoff-bot").first();
  await expect(first).toHaveAttribute("aria-selected", "true");
  const name = (await first.locator(".hf-name").textContent())!;
  await expect(pop.locator(".ho-note")).toHaveText(`${name} gets a new thread with your note and this answer. You stay here.`);
  await expect(pop.getByTestId("handoff-confirm")).toBeEnabled();
  await mock("mock.botStatus", { bot: "friren", status: "online" });
});

test("Hand to bot waits for the answer to finish: not on a row of the turn still running", async ({ page }) => {
  await kami(page);
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }, { event: "message", bot: "kami", id: "hf-live", text: "Looking at the logs first." }] });
  const live = page.getByTestId("bubble-bot").filter({ hasText: "Looking at the logs first." });
  await expect(live).toBeVisible();
  await expect(live.getByTestId("copy-answer")).toHaveCount(1);
  await expect(live.getByTestId("handoff-action")).toHaveCount(0);
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", outcome: "done" }] });
  await expect(live.getByTestId("handoff-action")).toHaveCount(1);
});
