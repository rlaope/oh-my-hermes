// First run (no `omher.onboarded` in localStorage): two cards in one container over a chat with no messages yet,
// each with one quiet button of the same look, one × that dismisses both for good. The empty Sessions section stays
// one New session row (its hint is the row's tooltip, not a line under it).
// A chat with history never shows them. Every other spec starts past this
// (playwright.config.ts sets `omher.onboarded`).
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

test("first run: the cards sit over an empty chat only, their quiet buttons work, and one × dismisses both for good", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("omher.sessions.recent"));
  await mock("mock.clearHistory", { bot: "friren" });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // Kami's chat has history: no cards above it; the empty Sessions section is one row, its hint only in the tooltip
  await expect(page.getByTestId("timeline")).toContainText("Ping me when the retry fix is up.");
  await expect(page.getByTestId("onboarding")).toHaveCount(0);
  await expect(page.getByTestId("onb-hint-sessions")).toHaveCount(0);
  await expect(page.getByTestId("session-none")).toHaveText("New session");
  await expect(page.getByTestId("session-start")).toHaveAttribute("title", /^Run a coding agent in a folder, as a chat\./);

  // Friren's chat has no messages: the cards show there
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  const onb = page.getByTestId("onboarding");
  await expect(onb).toBeVisible();
  await expect(page.getByTestId("onb-bots")).toContainText("Bots");
  await expect(page.getByTestId("onb-bots")).toContainText("Coworkers you hand work to. They plan it, run it and report back.");
  await expect(page.getByTestId("onb-sessions")).toContainText("A coding agent (Claude Code, Codex, pi, omp) working with you in one folder.");
  await expect(onb).not.toContainText("Hermes");
  // one flat container, no gradient, small radius; both cards inside it; one × in its top-right corner
  const look = await onb.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { img: cs.backgroundImage, radius: parseFloat(cs.borderRadius) };
  });
  expect(look.img).toBe("none");
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  await expect(onb.getByTestId("onb-dismiss")).toHaveCount(1);
  const box = (await onb.boundingBox())!;
  const x = (await page.getByTestId("onb-dismiss").boundingBox())!;
  expect(box.x + box.width - (x.x + x.width)).toBeLessThanOrEqual(10);
  expect(x.y - box.y).toBeLessThanOrEqual(10);
  // two quiet outlined buttons of one look (no fill, same edge, height, type, no icon on either), never a solid fill
  const looks = [];
  for (const id of ["onb-message", "onb-session"]) {
    looks.push(
      await page.getByTestId(id).evaluate((el) => {
        const cs = getComputedStyle(el);
        return {
          bg: cs.backgroundColor,
          border: cs.borderTopWidth,
          edge: cs.borderTopColor,
          h: el.getBoundingClientRect().height,
          font: `${cs.fontSize} ${cs.fontWeight}`,
          color: cs.color,
          icons: el.querySelectorAll("svg").length,
        };
      }),
    );
  }
  expect(looks[0].bg).toBe("rgba(0, 0, 0, 0)");
  expect(parseFloat(looks[0].border)).toBeGreaterThan(0);
  expect(looks[1]).toEqual(looks[0]);
  expect(looks[0].icons).toBe(0);

  // "Message a bot" focuses the composer of the empty chat it sits over
  await page.getByTestId("onb-message").click();
  await expect(page.getByTestId("composer")).toBeFocused();

  // "New session" opens the same SESSIONS + menu as the sidebar's own New session row
  await page.getByTestId("onb-session").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
  await expect(page.getByTestId("session-start")).toBeVisible();

  // × dismisses both cards, and they stay gone after a reload
  await page.getByTestId("onb-dismiss").click();
  await expect(onb).toHaveCount(0);
  await expect(page.getByTestId("onb-hint-sessions")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.onboarded"))).toBe("1");
  await page.reload();
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("session-none")).toBeVisible();
  await expect(page.getByTestId("onboarding")).toHaveCount(0);
});

test("the cards' words come from the string table", async ({ page }) => {
  await mock("mock.clearHistory", { bot: "kami" });
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await page.goto("/");
  await expect(page.getByTestId("onb-bots")).toContainText("봇에게 메시지");
  await expect(page.getByTestId("onb-sessions")).toContainText("새 세션");
  await expect(page.getByTestId("onb-dismiss")).toHaveAttribute("aria-label", "닫기");
});
