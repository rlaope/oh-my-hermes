// Fit of the settings and tool pages (UI review B): card grids never leave a card alone beside empty slots, card
// actions line up across a row, and short labels stay whole, at 1280x820 and at the 900x600 minimum window.
import { expect, test, type Page } from "@playwright/test";
import { gridRows, lineCount } from "./layout-helpers";

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

test("General: every switch ends on one right edge and starts where the 200px switches start; the sidebar row has its own heading", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-general").click();
  const x = async (id: string) => page.getByTestId(id).evaluate((e) => { const r = e.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right) }; });
  const theme = await x("theme-seg");
  const lang = await x("language");
  expect(lang, JSON.stringify({ theme, lang })).toEqual(theme);
  for (const b of await page.getByTestId("language").getByRole("radio").all()) expect(await lineCount(b)).toBe(1);
  // "Tasks in the sidebar" sits in a group under its own heading, a section gap below Notifications
  const head = await page.getByTestId("set-tasks-bar").evaluate((el) => {
    const grp = el.closest(".st-grp")!;
    const prev = grp.previousElementSibling as HTMLElement;
    return { cls: prev.className, text: prev.textContent, gap: Math.round(grp.getBoundingClientRect().top - prev.getBoundingClientRect().bottom) };
  });
  expect(head.cls).toContain("st-gh");
  expect(head.text).toBe("Sidebar");
});

test("light: a selected segment stands out from its track on the Settings pages", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.theme", "light"));
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-general").click();
  const c = await page.getByTestId("theme-seg").evaluate((seg) => ({ track: getComputedStyle(seg).backgroundColor, on: getComputedStyle(seg.querySelector("button.on")!).backgroundColor }));
  expect(c.track, JSON.stringify(c)).not.toBe(c.on);
  // the track is --raise2 (#e9e5eb), the selected segment white
  expect(c.track).toBe("rgb(233, 229, 235)");
});

test("Computer is marked Soon in the nav itself", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-nav-computer").locator(".nav-soon")).toHaveText("Soon");
});

test("Agents: the action comes first in every confirm, as on the other pages; the state column keeps one x", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await expect(page.getByTestId("agents-builtins").locator(".ag-state").first()).toBeVisible();
  const lefts = await page.getByTestId("agents-builtins").locator(".ag-state").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().left)));
  expect(new Set(lefts).size, JSON.stringify(lefts)).toBe(1);
  await page.getByTestId("agents-add").click();
  const order = async (sel: string) => page.locator(sel).evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(await order("[data-testid=agent-form] .ag-acts button")).toEqual(["agent-form-save", "agent-form-cancel"]);
  await page.getByTestId("agent-form-label").fill("Cursor");
  await page.getByTestId("agent-form-program").fill("cursor-agent");
  await page.getByTestId("agent-form-args").fill("acp");
  await page.getByTestId("agent-form-save").click();
  await expect(page.getByTestId("agent-confirm")).toBeVisible();
  expect(await order("[data-testid=agent-confirm] .ag-acts button")).toEqual(["agent-confirm-add", "agent-confirm-cancel"]);
  // Cancel keeps the focus, so Enter does not add by accident
  await expect(page.getByTestId("agent-confirm-cancel")).toBeFocused();
  await page.getByTestId("agent-confirm-cancel").click();
});

test("Agents at 900: Add agent's rows stack label, hint and a full-width input, all one shape", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await page.getByTestId("agents-add").click();
  const rows = await page.locator("[data-testid=agent-form] .st-row:not(.ag-formfoot)").evaluateAll((els) =>
    els.map((r) => {
      const k = r.querySelector(".st-k")!.getBoundingClientRect();
      const i = r.querySelector("input")!.getBoundingClientRect();
      return { h: Math.round(r.getBoundingClientRect().height - parseFloat(getComputedStyle(r).borderTopWidth)), under: i.top >= k.bottom - 1, wide: Math.round(i.width) >= Math.round(r.getBoundingClientRect().width) - 26 };
    }),
  );
  expect(rows).toHaveLength(4);
  for (const r of rows) expect(r, JSON.stringify(rows)).toMatchObject({ under: true, wide: true });
  expect(new Set(rows.map((r) => r.h)).size, JSON.stringify(rows)).toBe(1);
  for (const hint of await page.locator("[data-testid=agent-form] .st-k span").all()) expect(await lineCount(hint)).toBe(1);
});
