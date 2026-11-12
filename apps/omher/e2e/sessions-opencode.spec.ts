// OpenCode in SESSIONS, on the mock host (the browser build's MockHost sends what acp_chat.rs sends for a real
// OpenCode run): the + menu row with its mark, the Not installed line, a chat turn with the model, and the
// approval card that offers only Deny and Allow once (OpenCode's "always" is a saved project rule, never shown).
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Call = { op: string; agent?: string; resume?: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

async function open(page: Page, installed: string[]) {
  await page.addInitScript((list) => {
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = list;
  }, installed);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

test("OpenCode not installed: the + menu row is dimmed and its tooltip names OpenCode's own install line", async ({ page }) => {
  await open(page, ["claude"]);
  await page.getByTestId("session-new").click();
  const row = page.getByTestId("session-menu").getByTestId("session-agent-opencode");
  await expect(row).toContainText("OpenCode");
  await expect(row).toContainText("Not installed");
  await expect(row).toHaveAttribute("aria-disabled", "true");
  await expect(row).toHaveAttribute("title", "opencode was not found on this computer · install: npm install -g opencode-ai");
  // the official mark, not a letter
  await expect(row.locator('svg[data-agent="opencode"]')).toHaveCount(1);
});

test("an OpenCode chat: a turn with its model, then an approval card with Deny and Allow once only", async ({ page }) => {
  await open(page, ["claude", "opencode"]);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-opencode").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("Add a dark mode toggle");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("(mock OpenCode) You said: Add a dark mode toggle");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("model-pill")).toContainText("OpenCode/Big Pickle");
  const start = (await calls(page)).find((c) => c.op === "chat.start")!;
  expect(start.agent).toBe("opencode");

  await page.getByTestId("composer").fill("/approve clean the build folder");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  expect(await card.locator(".card-btn").allInnerTexts()).toEqual(["Deny", "Allow once"]);
  await card.getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("card-line")).toContainText("Allowed once");
  const approve = (await calls(page)).find((c) => c.op === "chat.input" && c.input?.kind === "approve")!;
  expect(approve.input).toMatchObject({ kind: "approve", choice: "once" });
});
