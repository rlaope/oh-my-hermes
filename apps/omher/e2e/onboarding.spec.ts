// First run (no `omher.onboarded` in localStorage): two cards above the first bot's chat, each with one button,
// one muted line under the empty Sessions section, dismissed with × for good. Every other spec starts past this
// (playwright.config.ts sets `omher.onboarded`).
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ storageState: { cookies: [], origins: [] }, colorScheme: "dark" });

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "o1", op }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("first run: Bots and Sessions cards, their buttons, the empty-section line, and × dismisses them for good", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("omher.sessions.recent"));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const onb = page.getByTestId("onboarding");
  await expect(onb).toBeVisible();
  await expect(page.getByTestId("onb-bots")).toContainText("Bots");
  await expect(page.getByTestId("onb-bots")).toContainText("Your Hermes coworkers. Message one to hand it work; it plans and runs it.");
  await expect(page.getByTestId("onb-sessions")).toContainText("Open Claude Code, Codex, pi or omp in a folder and work alongside it.");
  await expect(page.getByTestId("onb-hint-sessions")).toHaveText("Run a coding agent in a folder, as a chat.");
  // flat cards: no gradient, small radius
  const look = await page.getByTestId("onb-bots").evaluate((el) => {
    const cs = getComputedStyle(el);
    return { img: cs.backgroundImage, radius: parseFloat(cs.borderRadius) };
  });
  expect(look.img).toBe("none");
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);

  // "Message a bot" focuses the first bot's composer
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("onb-message").click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("composer")).toBeFocused();

  // "New session" opens the SESSIONS + menu
  await page.getByTestId("onb-session").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-menu")).toHaveCount(0);

  // × dismisses the cards and the line, and they stay gone after a reload
  await page.getByTestId("onb-dismiss").click();
  await expect(onb).toHaveCount(0);
  await expect(page.getByTestId("onb-hint-sessions")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.onboarded"))).toBe("1");
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("session-none")).toBeVisible();
  await expect(page.getByTestId("onboarding")).toHaveCount(0);
});

test("the cards' words come from the string table", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await page.goto("/");
  await expect(page.getByTestId("onb-bots")).toContainText("봇에게 메시지");
  await expect(page.getByTestId("onb-sessions")).toContainText("새 세션");
  await expect(page.getByTestId("onb-dismiss")).toHaveAttribute("aria-label", "닫기");
});
