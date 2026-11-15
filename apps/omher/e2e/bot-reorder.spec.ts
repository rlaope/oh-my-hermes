// Sidebar reorder: hold a bot row, drag it, let go; the new order shows at once, stays after a reload, and ⌘1…⌘9
// follow it. A quick press still opens the bot. Escape while holding puts the row back. ⌥↑/⌥↓ moves a focused row.
// Pinned bots move only among the pinned; dragging another bot above them stops below them (nothing gets pinned).
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
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

const listed = (page: Page) =>
  page.locator(".bot-list button.bot").evaluateAll((els) => els.map((e) => (e.getAttribute("data-testid") ?? "").replace(/^bot-/, "")));
const saved = (page: Page, key: string) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) || "null"), key);

/** Hold the row's middle for `ms`, then drag to the middle of `onto` (a little past it) and let go. */
async function holdAndDrag(page: Page, bot: string, onto: string, { ms = 450, release = true } = {}) {
  const from = (await page.getByTestId(`bot-row-${bot}`).boundingBox())!;
  const to = (await page.getByTestId(`bot-row-${onto}`).boundingBox())!;
  const x = from.x + 40;
  await page.mouse.move(x, from.y + from.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(ms);
  const down = to.y > from.y;
  const y = to.y + to.height / 2 + (down ? 6 : -6);
  await page.mouse.move(x, y, { steps: 8 });
  if (release) await page.mouse.up();
}

test.beforeEach(async ({ page }) => {
  await mock("mock.reset");
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  expect(await listed(page)).toEqual(["kami", "friren", "default", "omh-tui"]);
});

test("hold and drag a bot to the top: the order shows, is saved, survives a reload, and ⌘1 opens it", async ({ page }) => {
  await holdAndDrag(page, "omh-tui", "kami");
  await expect.poll(() => listed(page)).toEqual(["omh-tui", "kami", "friren", "default"]);
  expect(await saved(page, "omher.roster")).toEqual(["omh-tui", "kami", "friren", "default"]);
  // the release did not open the dragged bot
  await expect(page.getByTestId("bot-omh-tui")).not.toHaveAttribute("aria-current", "true");
  await expect(page.locator("body")).not.toHaveClass(/row-dragging/);

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  expect(await listed(page)).toEqual(["omh-tui", "kami", "friren", "default"]);
  await page.keyboard.press(process.platform === "darwin" ? "Meta+1" : "Control+1");
  await expect(page.getByTestId("bot-omh-tui")).toHaveAttribute("aria-current", "true");
});

test("drag down past two rows, then a quick press still just opens the bot", async ({ page }) => {
  await holdAndDrag(page, "kami", "default");
  await expect.poll(() => listed(page)).toEqual(["friren", "default", "kami", "omh-tui"]);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  expect(await listed(page)).toEqual(["friren", "default", "kami", "omh-tui"]);
});

test("moving before the hold time is a plain press, not a drag", async ({ page }) => {
  await holdAndDrag(page, "omh-tui", "kami", { ms: 60 });
  expect(await listed(page)).toEqual(["kami", "friren", "default", "omh-tui"]);
});

test("Escape while holding puts the row back", async ({ page }) => {
  await holdAndDrag(page, "omh-tui", "kami", { release: false });
  await expect(page.getByTestId("bot-row-omh-tui")).toHaveClass(/lifted/);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(page.getByTestId("bot-row-omh-tui")).not.toHaveClass(/lifted/);
  expect(await listed(page)).toEqual(["kami", "friren", "default", "omh-tui"]);
  expect(await saved(page, "omher.roster")).toEqual(["kami", "friren", "default", "omh-tui"]);
});

test("⌥↑ / ⌥↓ on a focused row moves it one place", async ({ page }) => {
  await page.getByTestId("bot-default").focus();
  await page.keyboard.press("Alt+ArrowUp");
  await expect.poll(() => listed(page)).toEqual(["kami", "default", "friren", "omh-tui"]);
  await page.keyboard.press("Alt+ArrowDown");
  await page.keyboard.press("Alt+ArrowDown");
  await expect.poll(() => listed(page)).toEqual(["kami", "friren", "omh-tui", "default"]);
});

test("pinned bots stay on top: another bot dropped above them lands right below them", async ({ page }) => {
  await page.getByTestId("bot-row-default").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Pin to top" }).click();
  await expect.poll(() => listed(page)).toEqual(["default", "kami", "friren", "omh-tui"]);
  await holdAndDrag(page, "omh-tui", "default");
  await expect.poll(() => listed(page)).toEqual(["default", "omh-tui", "kami", "friren"]);
  expect(await saved(page, "omher.pinned")).toEqual(["default"]);
});

test("while searching, rows cannot be dragged", async ({ page }) => {
  await page.getByTestId("bot-search").fill("i");
  const shown = await listed(page);
  expect(shown.length).toBeGreaterThan(1);
  await holdAndDrag(page, shown[shown.length - 1], shown[0]);
  await page.getByTestId("bot-search").fill("");
  expect(await listed(page)).toEqual(["kami", "friren", "default", "omh-tui"]);
});
