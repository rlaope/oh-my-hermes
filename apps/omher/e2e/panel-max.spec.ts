// The side panel maximises IN PLACE: the same panel grows to every pixel right of the sidebar, the chat column folds
// to 0 (still mounted: its draft stays), the sidebar never moves. Restore brings back the exact width the tab had.
// Controls: the tab row's button, a double click on the tab row, ⌘⇧G, Esc; closing the panel restores too. No
// dialog, no second header. Set OMHER_SHOTS=<dir> to also write the panelmax-*.png shots.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "m1", op, ...params }));
  });
  ws.close();
}

async function mod(page: Page) {
  return (await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform))) ? "Meta" : "Control";
}

/** Rects read in one frame: sidebar, chat column, panel. */
const rects = (page: Page) =>
  page.evaluate(() => {
    const r = (id: string) => {
      const b = document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect();
      return { x: b.x, right: b.right, width: b.width };
    };
    const main = document.querySelector(".main")!.getBoundingClientRect();
    return { side: r("sidebar"), panel: r("details"), main: { x: main.x, width: main.width }, vw: window.innerWidth };
  });
const panelW = async (page: Page) => Math.round((await rects(page)).panel.width);
/** Every CSS transition running now has ended. */
const settled = (page: Page) =>
  page.evaluate(() =>
    Promise.all(document.getAnimations().filter((a) => a instanceof CSSTransition).map((a) => a.finished.catch(() => null))).then(() => undefined),
  );

async function openPanel(page: Page, tab: "details" | "runs" | "terminal" = "runs") {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  if (!/\bpanel-open\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "")) await page.getByTestId("places").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await page.getByTestId(`panel-tab-${tab}`).click();
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", tab);
  await settled(page);
}

async function expectMaxed(page: Page) {
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
  await expect
    .poll(async () => {
      const r = await rects(page);
      return [Math.abs(r.panel.x - r.side.right) <= 1, Math.abs(r.panel.right - r.vw) <= 1, Math.round(r.main.width)];
    })
    .toEqual([true, true, 0]);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Plans: the tab row's button maximises the panel in place; the sidebar stays; restore returns the exact width and the draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "details");
  await page.getByTestId("composer").fill("half-written thought");
  await page.getByTestId("panel-tab-runs").click();
  await settled(page);
  const before = await panelW(page);
  const btn = page.getByTestId("panel-max");
  await expect(btn).toHaveAttribute("title", "Expand");
  await btn.click();
  await expectMaxed(page);
  // one header: the panel's own tab row; no dialog over the chat, no resizer
  await expect(page.locator("[role=dialog]")).toHaveCount(0);
  await expect(page.getByTestId("runs-full")).toHaveCount(0);
  await expect(page.getByTestId("panel-resizer")).toHaveCount(0);
  await expect(btn).toHaveAttribute("title", "Restore");
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  // the chat is still mounted, hidden and inert
  await expect(page.locator(".main")).toHaveAttribute("inert", "");
  await expect(page.getByTestId("composer")).toHaveCount(1);
  // the Plans graph renders at the bigger width: the full drawing with its zoom tools
  await expect(page.getByTestId("run-graph-box")).toHaveClass(/\bmax\b/);
  await expect(page.getByTestId("run-zoom")).toBeVisible();
  // the sidebar is visible and clickable
  await expect(page.getByTestId("sidebar")).toBeVisible();
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // restore: back to the width it had before, and the draft is still in the composer
  await page.getByTestId("panel-max").click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await settled(page);
  await expect.poll(() => panelW(page)).toBe(before);
  await expect(page.locator(".main")).not.toHaveAttribute("inert", "");
  await expect(page.getByTestId("composer")).toHaveValue("half-written thought");
  await expect(page.getByTestId("panel-resizer")).toHaveCount(1);
});

test("a dragged width comes back exactly after maximise and restore, for Details", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "details");
  const h = (await page.getByTestId("panel-resizer").boundingBox())!;
  await page.mouse.move(h.x + 3, h.y + 200);
  await page.mouse.down();
  await page.mouse.move(h.x + 3 - 77, h.y + 200, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => panelW(page)).toBe(377);
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  // maximising saves nothing
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.panelWidth") || "null"))).toEqual({ details: 377 });
  await page.getByTestId("panel-max").click();
  await settled(page);
  await expect.poll(() => panelW(page)).toBe(377);
});

test("⌘⇧G toggles (opening Plans when the panel is closed), Esc restores, double-click on the tab row toggles, closing restores", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  const m = await mod(page);
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "runs");
  await expectMaxed(page);
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  // the panel open on another tab: ⌘⇧G maximises that tab
  await page.getByTestId("panel-tab-terminal").click();
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "terminal");
  await expectMaxed(page);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  // double-click on the free part of the tab row
  const row = page.getByTestId("panel-tabs");
  const b = (await row.boundingBox())!;
  const tabsRight = await row.evaluate((e) => Math.max(...[...e.querySelectorAll(".pn-tab")].map((t) => t.getBoundingClientRect().right)));
  await page.mouse.dblclick(tabsRight + 12, b.y + b.height / 2);
  await expectMaxed(page);
  await page.mouse.dblclick(tabsRight + 12, b.y + b.height / 2);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  // a double click on a tab only picks the tab
  await page.getByTestId("panel-tab-details").dblclick();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  // closing the panel restores: it opens again at its own width
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await page.getByRole("button", { name: "Close details" }).click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
});

test("Esc in a field inside the panel does not restore it", async ({ page }) => {
  await openPanel(page, "details");
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await page.evaluate(() => {
    const i = document.createElement("input");
    i.id = "probe";
    document.querySelector("[data-testid=details-panel]")!.appendChild(i);
  });
  await page.locator("#probe").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
});

test("the graph's expand button maximises the panel on Plans, and restores it", async ({ page }) => {
  await openPanel(page, "runs");
  const expand = page.getByTestId("graph-expand");
  await expect(expand).toHaveAttribute("title", /^Full view (⌘⇧G|Ctrl\+Shift\+G)$/);
  await expand.click();
  await expectMaxed(page);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "runs");
  await expect(expand).toHaveAttribute("title", /^Restore (⌘⇧G|Ctrl\+Shift\+G)$/);
  await expand.click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
});

test("eases in about 180ms; reduced motion: no transition", async ({ browser }) => {
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    const ctx = await browser.newContext({ reducedMotion, viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await openPanel(page, "details");
    await page.getByTestId("panel-max").click();
    const t = await page.getByTestId("window").evaluate((e) => [getComputedStyle(e).transitionDuration, getComputedStyle(e).transitionProperty]);
    // reduced motion: base.css forces every transition to 0.001ms, i.e. none a person can see
    if (reducedMotion === "reduce") expect(parseFloat(t[0]) * (t[0].endsWith("ms") ? 1 : 1000)).toBeLessThan(1);
    else expect(t).toEqual(["0.18s", "grid-template-columns"]);
    await expectMaxed(page);
    await ctx.close();
  }
});

test("under 1100px the overlay panel maximises to the window less the sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 760 });
  await openPanel(page, "details");
  await page.getByTestId("panel-max").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
  await expect
    .poll(async () => {
      const r = await rects(page);
      return [Math.abs(r.panel.x - r.side.right) <= 1, Math.abs(r.panel.right - r.vw) <= 1];
    })
    .toEqual([true, true]);
  await expect(page.getByTestId("sidebar")).toBeVisible();
});

test("shots: normal, maximised Plans, maximised Details (dark) and maximised Plans (light)", async ({ browser }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  mkdirSync(SHOTS, { recursive: true });
  const shot = async (scheme: "dark" | "light", name: string, tab: "details" | "runs", max: boolean) => {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await openPanel(page, tab);
    if (max) {
      await page.getByTestId("panel-max").click();
      await expectMaxed(page);
    }
    await page.waitForTimeout(1600);
    await page.screenshot({ path: join(SHOTS, `panelmax-${name}.png`), animations: "disabled" });
    await ctx.close();
  };
  await shot("dark", "normal-dark", "runs", false);
  await shot("dark", "max-plans-dark", "runs", true);
  await shot("dark", "max-details-dark", "details", true);
  await shot("light", "max-plans-light", "runs", true);
});
