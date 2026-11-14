// First run (no `omher.onboarded` in localStorage, a fresh install): there is no first-run panel. The sidebar lists
// one bot, the default profile. An empty chat shows just the chat (its timeline and composer), a chat with history
// shows its history, and the empty Sessions section stays one New session row with its hint in the tooltip.
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ storageState: { cookies: [], origins: [] }, colorScheme: "dark" });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "o1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("first run: an empty chat shows just the chat, with no first-run panel over it", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("omher.sessions.recent"));
  await mock("mock.clearHistory", { bot: "friren" });
  await page.goto("/");
  // a fresh install starts with the default bot alone; its chat has history
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  expect(await page.locator(".bot-list button.bot").count()).toBe(1);
  await expect(page.getByTestId("timeline")).toContainText("Hi, I'm Hermes.");
  await expect(page.getByTestId("session-none")).toHaveText("New session");
  await expect(page.getByTestId("session-start")).toHaveAttribute("title", /^Run a coding agent in a folder, as a chat\./);
  // another bot comes in from + in one click; its empty chat is just the chat
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-friren").getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  const pane = page.locator('[data-pane="friren"]');
  await expect(pane.getByTestId("composer")).toBeVisible();
  // nothing of the old panel: no cards, no buttons, no language row, no ×
  for (const id of ["onboarding", "onb-bots", "onb-sessions", "onb-omh", "onb-lang", "onb-dismiss"]) await expect(page.getByTestId(id)).toHaveCount(0);
  await expect(pane.locator(".onb, .onb-card")).toHaveCount(0);
});
