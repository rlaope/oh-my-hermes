// Fit of the settings and tool pages (UI review B): card grids never leave a card alone beside empty slots, card
// actions line up across a row, and short labels stay whole, at 1280x820 and at the 900x600 minimum window.
import { expect, test, type Page } from "@playwright/test";
import { gridRows } from "./layout-helpers";

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
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** Every row ends on the grid's right edge: a lone last card spans the row instead of leaving empty slots. */
async function expectFullRows(page: Page, testId: string) {
  const rows = await gridRows(page.getByTestId(testId));
  expect(rows.length, testId).toBeGreaterThan(0);
  for (const r of rows) expect(r.gap, `${testId} ${JSON.stringify(rows)}`).toBeLessThanOrEqual(1);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const [w, h] of [
  [1280, 820],
  [900, 600],
] as const) {
  test(`All bots at ${w}: four bots fill whole rows of equal height; one match takes the whole row`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("settings-nav-bots").click();
    const grid = page.getByTestId("bots-grid");
    await expect(grid.locator(".bot-card")).toHaveCount(4);
    await expectFullRows(page, "bots-grid");
    const rows = await gridRows(grid);
    // 2 + 2 where two fit, else one per row; never 3 + 1
    expect(rows.map((r) => r.n)).toEqual(w === 1280 ? [2, 2] : [1, 1, 1, 1]);
    const heights = await grid.locator(".bot-card").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    expect(new Set(heights).size, JSON.stringify(heights)).toBe(1);
    await page.getByTestId("bots-search").fill("research");
    await expect(grid.locator(".bot-card")).toHaveCount(1);
    await expectFullRows(page, "bots-grid");
  });

  test(`Plugins at ${w}: an odd count's last card spans the row, and each row's actions sit on one line`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    await page.getByTestId("nav-plugins").click();
    await expect(page.getByTestId("plug-grid-installed")).toBeVisible();
    await expectFullRows(page, "plug-grid-installed");
    await page.getByTestId("plug-tab-browse").click();
    const grid = page.getByTestId("plug-grid-browse");
    await expect(grid.locator("[data-testid^=plug-card-]")).toHaveCount(13);
    await expectFullRows(page, "plug-grid-browse");
    // the action rows of the two cards in a row end on the same line
    const bottoms = await grid.locator(".pl-card").evaluateAll((cards) =>
      cards.map((c) => ({ top: Math.round(c.getBoundingClientRect().top), ctl: Math.round(c.querySelector(".pl-ctl")!.getBoundingClientRect().bottom), card: Math.round(c.getBoundingClientRect().bottom) })),
    );
    expect(new Set(bottoms.map((b) => b.card - b.ctl)).size, JSON.stringify(bottoms)).toBe(1);
    await page.getByTestId("plug-tab-builtin").click();
    await expect(page.getByTestId("plug-grid-builtin").locator("[data-testid^=plug-card-]")).toHaveCount(3);
    await expectFullRows(page, "plug-grid-builtin");
  });

  test(`Apps at ${w}: no section ends with a card alone beside an empty slot`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    await page.getByTestId("nav-apps").click();
    for (const tier of ["work", "ops", "more"]) {
      const sec = page.getByTestId(`apps-sec-${tier}`);
      await expect(sec).toBeVisible();
      const rows = await gridRows(sec.locator(".pl-grid"));
      for (const r of rows) expect(r.gap, `${tier} ${JSON.stringify(rows)}`).toBeLessThanOrEqual(1);
    }
  });
}
