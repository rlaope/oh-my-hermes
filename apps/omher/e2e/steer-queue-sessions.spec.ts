// steer queue sessions: in a SESSIONS chat, a message sent while the agent answers waits with the ↵ mark; its menu
// offers Send now, Steer (only for an agent with its own mid-turn input; otherwise off with a reason), Edit and
// Delete (only while omher still holds it). Runs on the mock host (src/sessions/host.ts MockChat).
import { expect, test, type Page } from "@playwright/test";

test.skip(true, "chat-mode CLI sessions replaced by bot threads (2026-11-16: terminals kept)");

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string) {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<string>((res) => {
    ws.onmessage = (m) => res(String(m.data));
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Input = { kind: string; text?: string; id?: string };
const inputs = (page: Page) =>
  page.evaluate(() =>
    ((window as unknown as { __omherSessionCalls?: { op: string; input?: Input }[] }).__omherSessionCalls ?? [])
      .filter((c) => c.op === "chat.input")
      .map((c) => c.input!),
  );
const sent = async (page: Page) => (await inputs(page)).filter((i) => i.kind === "send").map((i) => i.text);

async function running(page: Page, agent: "claude" | "codex" | "omo" | "dsh") {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/home/you/code/omher";
    w.__omherMockAgents = ["claude", "codex", "omo", "dsh", "omh"];
  });
  // shots are 900x600, laid out at that size from the start
  if (process.env.OMHER_SHOTS) await page.setViewportSize({ width: 900, height: 600 });
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

/** Start a long turn, then send `texts` while it runs. */
async function busy(page: Page, ...texts: string[]) {
  const box = page.getByTestId("composer");
  await box.fill("/slow");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  for (const t of texts) {
    await box.fill(t);
    await page.keyboard.press("Enter");
    await expect(bubble(page, t)).toHaveAttribute("data-held", "true");
  }
}
const bubble = (page: Page, text: string) => page.getByTestId("bubble-user").filter({ hasText: text });

test("Codex: a waiting message has the ↵ menu with every item on; Steer sends one steer input", async ({ page }) => {
  await running(page, "codex");
  await busy(page, "also check the changelog");
  const b = bubble(page, "also check the changelog");
  await expect(b.getByTestId("bubble-queued")).toHaveText("Waiting");
  // held in omher: not sent to the agent yet
  expect(await sent(page)).toEqual(["/status", "/slow"]);
  await b.getByTestId("queue-mark").click();
  const menu = page.getByTestId("queue-menu");
  for (const c of ["now", "steer", "edit", "delete"]) await expect(menu.getByTestId(`queue-${c}`)).not.toHaveAttribute("aria-disabled", "true");
  await menu.getByTestId("queue-steer").click();
  await expect.poll(async () => (await inputs(page)).filter((i) => i.kind === "steer")).toEqual([
    { kind: "steer", id: expect.stringMatching(/^local-s/), text: "also check the changelog" },
  ]);
  // the agent took it into the running turn: no mark, never sent as its own message
  await expect(b).not.toHaveAttribute("data-wait", /.+/);
  await expect(b.getByTestId("queue-mark")).toHaveCount(0);
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  expect(await sent(page)).toEqual(["/status", "/slow"]);
});

test("Send now: one Stop, then this message goes first; the other keeps waiting", async ({ page }) => {
  await running(page, "claude");
  await busy(page, "second", "third");
  await bubble(page, "third").getByTestId("queue-mark").click();
  await page.getByTestId("queue-menu").getByTestId("queue-now").click();
  await expect.poll(() => sent(page)).toEqual(["/status", "/slow", "third"]);
  expect((await inputs(page)).filter((i) => i.kind === "interrupt")).toHaveLength(1);
  await expect(bubble(page, "second")).toHaveAttribute("data-held", "true");
  // after third's turn, second goes out by itself
  await expect.poll(() => sent(page), { timeout: 8000 }).toEqual(["/status", "/slow", "third", "second"]);
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "You said: second" })).toBeVisible();
});

test("Edit and Delete take a message back while omher holds it", async ({ page }) => {
  await running(page, "omo");
  await busy(page, "drop me", "fix me");
  await bubble(page, "drop me").getByTestId("queue-mark").click();
  await page.getByTestId("queue-menu").getByTestId("queue-delete").click();
  await expect(bubble(page, "drop me")).toHaveCount(0);
  await bubble(page, "fix me").getByTestId("queue-mark").click();
  await page.getByTestId("queue-menu").getByTestId("queue-edit").click();
  await expect(bubble(page, "fix me")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveValue("fix me");
  // (with text in the box the composer shows Send, not Stop)
  await page.getByTestId("composer").fill("");
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  expect(await sent(page)).toEqual(["/status", "/slow"]);
});

test("an agent without its own steer: Steer is off with its reason; once handed over, every item says so", async ({ page }) => {
  await running(page, "dsh");
  await busy(page, "later please");
  const b = bubble(page, "later please");
  await b.getByTestId("queue-mark").click();
  const menu = page.getByTestId("queue-menu");
  await expect(menu.getByTestId("queue-steer")).toHaveAttribute("aria-disabled", "true");
  await expect(menu.getByTestId("queue-steer-why")).toHaveText("DSH has no way to take a message mid-answer");
  // an item that is off does nothing (forced: Playwright never clicks an aria-disabled element)
  await menu.getByTestId("queue-steer").click({ force: true });
  await expect(menu).toBeVisible();
  expect((await inputs(page)).filter((i) => i.kind === "steer")).toEqual([]);
  for (const c of ["now", "edit", "delete"]) await expect(menu.getByTestId(`queue-${c}`)).not.toHaveAttribute("aria-disabled", "true");
  if (process.env.OMHER_SHOTS) await shot(page, "dsh");
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("session-status")).toHaveText("Working");
});

test("a steered message the agent has not taken yet: every item off, with one reason", async ({ page }) => {
  await running(page, "codex");
  await busy(page, "steered one");
  // the mock agent takes a steer after 60 ms: hold that back so the row stays with the agent
  await page.evaluate(() => {
    const real = window.setTimeout;
    (window as unknown as { __hold?: boolean }).__hold = true;
    window.setTimeout = ((fn: () => void, ms?: number) => real(fn, ms === 60 ? 60_000 : ms)) as typeof window.setTimeout;
  });
  const b = bubble(page, "steered one");
  await b.getByTestId("queue-mark").click();
  await page.getByTestId("queue-menu").getByTestId("queue-steer").click();
  await expect(b).not.toHaveAttribute("data-held", "true");
  await expect(b).toHaveAttribute("data-wait", "queued");
  await b.getByTestId("queue-mark").click();
  const menu = page.getByTestId("queue-menu");
  await expect(menu.getByTestId("queue-why")).toHaveText("Already with Codex · it takes it next");
  for (const c of ["now", "steer", "edit", "delete"]) await expect(menu.getByTestId(`queue-${c}`)).toHaveAttribute("aria-disabled", "true");
  await menu.getByTestId("queue-delete").click({ force: true });
  await expect(b).toHaveCount(1);
  if (process.env.OMHER_SHOTS) await shot(page, "handed");
});

test("shots: Codex menu with every item on", async ({ page }) => {
  test.skip(!process.env.OMHER_SHOTS, "OMHER_SHOTS not set");
  await running(page, "codex");
  await busy(page, "also check the changelog", "then run the tests");
  await bubble(page, "then run the tests").getByTestId("queue-mark").click();
  await expect(page.getByTestId("queue-menu")).toBeVisible();
  await shot(page, "codex");
});

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/steer-queue-sessions-${name}.png` });
}
