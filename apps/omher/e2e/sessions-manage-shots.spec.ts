// Shots for finding, opening and switching sessions: a session row's right-click menu, the sidebar search over
// sessions, and the + menu's "Continue a conversation" list. Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
// On a tree without the feature the same steps show what was there (two menu items, a search that leaves sessions
// alone, a + menu with no continue rows).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

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

async function start(page: Page, folder: string, first: string) {
  await page.evaluate((f) => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = f), folder);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

const shot = (page: Page, what: string, theme: string) =>
  page.screenshot({ path: join(SHOTS, `sessions-manage-${what}-${TAG}-${theme}.png`), animations: "disabled" });

for (const theme of ["dark", "light"] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await page.addInitScript((t) => {
      localStorage.setItem("omher.theme", t);
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.resume");
    }, theme);
    await page.goto("/");
    await start(page, "/Users/you/code/web-app", "Fix the login redirect");
    await start(page, "/Users/you/code/omher", "Add rate limits to the API");
    await page.mouse.move(900, 790);

    // the row's right-click menu
    const row = page.locator("[data-testid=session-list] .ss-row").first();
    const box = (await row.boundingBox())!;
    await page.mouse.click(box.x + 60, box.y + box.height / 2, { button: "right" });
    await expect(page.getByTestId("session-row-menu")).toBeVisible();
    await shot(page, "menu", theme);
    await page.keyboard.press("Escape");

    // the sidebar search typed with a folder's name
    const search = page.getByTestId("bot-search");
    await search.fill("web-app");
    await page.waitForTimeout(100);
    await shot(page, "search", theme);
    await search.fill("");

    // the + menu, and its Claude Code conversations
    await page.getByTestId("bot-kami").click();
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu")).toBeVisible();
    const pastRow = page.getByTestId("session-past-claude");
    if (await pastRow.count()) {
      await pastRow.click();
      await expect(page.getByTestId("session-past-list")).toBeVisible();
    }
    await shot(page, "continue", theme);
  });
}
