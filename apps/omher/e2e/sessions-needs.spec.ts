// SESSIONS chats in Needs-you: a session's approvals and questions are the same asks as a bot's. A Claude Code
// approval shows in the strip (named by the agent and folder, with the agent's mark) and is answered from there;
// ⌘J reaches a session's ask after a bot's; the session row rings while its turn runs, with the elapsed time,
// and turns to the amber dot and "waiting" while it asks.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (NEEDS_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.NEEDS_SHOTS || "test-results";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "sn1") res(msg);
    };
    ws.send(JSON.stringify({ id: "sn1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const hostCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const mod = async (page: Page) => ((await page.evaluate(() => /Mac/.test(navigator.platform))) ? "Meta" : "Control");

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.pinned");
    localStorage.removeItem("omher.hidden");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/web-app";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toContainText("updater");
}

async function startClaude(page: Page) {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("session-chat")).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  return page.locator("[data-testid=session-list] .ss-row").first();
}

async function ask(page: Page) {
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-approval")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a Claude Code session's approval shows in the needs strip and is answered from there", async ({ page }) => {
  await open(page);
  const row = await startClaude(page);
  await ask(page);
  // look away: back to a bot's chat
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);

  const strip = page.getByTestId("needs-strip");
  await expect(strip).toContainText("1 needs you");
  await expect(row).toHaveAttribute("data-needs-you", "true");
  await expect(row.getByTestId("needs")).toBeVisible();
  await expect(row.getByTestId("bot-time")).toHaveText("waiting");
  await strip.click();
  const item = page.getByTestId("needs-item");
  await expect(item).toHaveCount(1);
  await expect(item.locator(".needs-b")).toHaveText("web-app · Claude Code");
  // the folder comes first, so a narrow row cuts the agent name (its mark is beside it), never the folder
  const folderShown = await item.locator(".needs-b").evaluate((el) => {
    const r = document.createRange();
    r.setStart(el.firstChild!, 0);
    r.setEnd(el.firstChild!, "web-app".length);
    return r.getBoundingClientRect().right <= el.getBoundingClientRect().right;
  });
  expect(folderShown).toBe(true);
  await expect(item.getByTestId("needs-tag")).toHaveText("Approve");
  await expect(item).toContainText("Allow rm -rf ./build?");
  await expect(item.getByTestId("session-face").locator("[data-mark], svg")).toHaveCount(1);
  await item.click();

  // the session opens with its card scrolled to and focused; the answer goes to the agent, not the bridge
  await expect(page.getByTestId("session-title")).toHaveText("Claude Code");
  await expect(row).toHaveClass(/active/);
  const card = page.getByTestId("timeline").getByTestId("card-approval");
  await expect(card).toBeFocused();
  await expect(page.getByTestId("composer")).toHaveAttribute("placeholder", "Answer above, or type to reply");
  await card.getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("card-line")).toContainText("Allowed once");
  await expect(strip).toHaveCount(0);
  await expect(row).not.toHaveAttribute("data-needs-you", "true");
  await expect(row.getByTestId("needs")).toHaveCount(0);
  const approve = (await hostCalls(page)).find((c) => c.op === "chat.input" && c.input?.kind === "approve")!;
  expect(approve.input).toMatchObject({ kind: "approve", choice: "once" });
  expect((await mock("mock.calls")).calls.filter((c: { op: string }) => c.op === "approval.respond")).toHaveLength(0);
});

test("⌘J walks a bot's ask and a session's ask in age order", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await expect(page.getByTestId("bot-friren").getByTestId("needs")).toBeVisible();
  await startClaude(page);
  await ask(page);
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("needs-strip")).toContainText("2 need you");

  const key = await mod(page);
  await page.keyboard.press(`${key}+j`);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline").getByTestId("card-approval")).toBeFocused();
  await page.keyboard.press(`${key}+j`);
  await expect(page.getByTestId("session-title")).toHaveText("Claude Code");
  const card = page.getByTestId("timeline").getByTestId("card-approval");
  await expect(card).toBeFocused();
  await expect(card.locator(".card-cmd")).toHaveText("rm -rf ./build");
  // the focused card's own keys answer it: 1 = Deny
  await page.keyboard.press("1");
  await expect(page.getByTestId("card-line")).toContainText("Denied");
  await expect(page.getByTestId("needs-strip")).toContainText("1 needs you");
  // and ⌘J wraps back to the bot
  await page.keyboard.press(`${key}+j`);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
});

test("the session row rings while its turn runs, with the elapsed time, and stops when it ends", async ({ page }) => {
  await open(page);
  const row = await startClaude(page);
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  await page.getByTestId("composer").fill("/slow");
  await page.keyboard.press("Enter");
  const ring = row.getByTestId("live-ring");
  await expect(ring).toBeVisible();
  await expect(ring).toHaveAttribute("aria-label", "Answering");
  await expect(row.getByTestId("live-dot")).toHaveCount(0);
  await expect(row.getByTestId("bot-typing")).toBeVisible();
  await expect(row.getByTestId("bot-time")).toHaveText(/^\d+s$/);
  // the ring sits around the agent mark without moving the row's text
  const box = (await row.locator(".ss-av").boundingBox())!;
  const r = (await ring.boundingBox())!;
  expect(r.width).toBeGreaterThan(box.width);
  expect(Math.abs(r.x + r.width / 2 - (box.x + box.width / 2))).toBeLessThan(1.5);
  // it keeps ringing from a bot's chat
  await page.getByTestId("bot-friren").click();
  await expect(ring).toBeVisible();
  await expect(row.getByTestId("bot-time")).toHaveText(/^\d+s$/);
  await row.locator(".ss-open").click();
  await page.keyboard.press("Escape");
  await expect(ring).toHaveCount(0);
  await expect(row.getByTestId("bot-time")).not.toHaveText(/^\d+s$/);
});

for (const theme of ["dark", "light"] as const) {
  test(`screenshot T14b-needs-${theme}: the needs strip with a session ask and a bot ask`, async ({ page }) => {
    mkdirSync(SHOTS, { recursive: true });
    await open(page, theme);
    await mock("mock.ask", { bot: "friren", kind: "clarify" });
    await startClaude(page);
    await ask(page);
    const row = page.locator("[data-testid=session-list] .ss-row", { hasText: "web-app" });
    await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/api-server"));
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-codex").click();
    await page.getByTestId("session-choose").click();
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await page.getByTestId("composer").fill("/slow");
    await page.keyboard.press("Enter");
    await expect(page.locator("[data-testid=session-list] .ss-row").first().getByTestId("live-ring")).toBeVisible();
    await page.getByTestId("bot-kami").click();
    await page.getByTestId("needs-strip").click();
    await expect(page.getByTestId("needs-item")).toHaveCount(2);
    await expect(row.getByTestId("needs")).toBeVisible();
    await page.mouse.move(900, 790);
    await page.screenshot({ path: join(SHOTS, `T14b-needs-${theme}.png`), animations: "disabled" });
  });
}
