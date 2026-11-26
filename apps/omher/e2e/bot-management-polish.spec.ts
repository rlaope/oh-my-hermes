// Bot management polish, against the mock bridge:
// 1. Remove from list on the open bot, from Settings, keeps Settings open (the chat behind it moves to another bot);
// 2. a bot renamed in Settings shows its new name on its threads' Needs-you lines;
// 3. a failed rename: Cancel clears the error, so the pencil opens a clean editor;
// 4. the row menu closed with Escape or a pick gives the keyboard back to the bot's ⋯, not <body>; the ContextMenu
//    key (no pointer position) opens it under the row, not at the window's top-left;
// 5. the handover card opened from a Worktrees row gives the keyboard back to that row when it closes.
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
      if (msg.id === "g6") res(msg);
    };
    ws.send(JSON.stringify({ id: "g6", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const focused = (page: Page) => page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? document.activeElement?.tagName);

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Remove from list on the open bot keeps Settings open", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await expect(page.getByTestId("bot-head")).toBeVisible();
  await page.getByTestId("bot-kami").click({ button: "right" });
  await page.getByTestId("row-remove").click();
  await expect(page.getByTestId("bot-kami")).toHaveCount(0);
  await expect(page.getByTestId("settings-nav-bot-kami")).toBeVisible();
  await expect(page.getByTestId("bot-head")).toBeVisible();
});

test("a renamed bot's threads show the new name in Needs you", async ({ page }) => {
  await open(page);
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "Docs pass", ago: 60 }] });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami", session: (threads as string[])[0] },
      { event: "approval.request", bot: "kami", session: (threads as string[])[0], request_id: "ap-g6", title: "Run shell command", command: "pnpm build", choices: ["once", "deny"] },
    ],
  });
  await expect(page.getByTestId("needs-strip")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await page.getByTestId("rename").click();
  await page.getByTestId("rename-input").fill("Renamed Helper");
  await page.getByTestId("rename-save").click();
  await expect(page.getByTestId("bot-name")).toHaveText("Renamed Helper");
  await page.getByTestId("needs-strip").click();
  await expect(page.getByTestId("needs-list")).toContainText("Docs pass · Renamed Helper");
  await mock("mock.manual", { bot: "kami", on: false });
});

test("rename Cancel clears the error", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await page.getByTestId("rename").click();
  await page.getByTestId("rename-input").evaluate((el: HTMLInputElement) => el.removeAttribute("maxlength"));
  await page.getByTestId("rename-input").fill("x".repeat(70));
  await page.getByTestId("rename-save").click();
  await expect(page.getByRole("alert")).toContainText("too long");
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByTestId("rename").click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("row menu: Escape and a pick return focus to the bot's ⋯; the ContextMenu key opens under the row", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-more-kami").click();
  await expect(page.getByTestId("row-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("row-menu")).toHaveCount(0);
  expect(await focused(page)).toBe("bot-more-kami");
  await page.getByTestId("bot-more-kami").click();
  await page.getByRole("menuitem", { name: "Pin to top" }).click();
  await expect(page.getByTestId("row-menu")).toHaveCount(0);
  expect(await focused(page)).toBe("bot-more-kami");

  // a keyboard-opened menu reports no pointer position (0, 0)
  await page.getByTestId("bot-friren").evaluate((el) => {
    el.closest('[data-testid="bot-row-friren"]')!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 0, clientY: 0 }));
  });
  const row = (await page.getByTestId("bot-row-friren").boundingBox())!;
  const menu = (await page.getByTestId("row-menu").boundingBox())!;
  expect(menu.y).toBeGreaterThanOrEqual(row.y + row.height - 1);
  expect(menu.y).toBeLessThan(row.y + row.height + 40);
});

test("a Worktrees row's handover card gives focus back to the row on Escape", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-worktrees").click();
  const tree = page.getByTestId("panel-tree").first();
  await expect(tree).toBeVisible();
  await tree.click({ button: "right" });
  await page.getByTestId("session-hand").click();
  await expect(page.getByTestId("handover")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("handover")).toHaveCount(0);
  expect(await focused(page)).toBe("panel-tree");
});
