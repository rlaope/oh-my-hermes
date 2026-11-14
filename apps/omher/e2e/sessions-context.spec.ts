import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

async function open(page: Page, theme = "dark") {
  await page.addInitScript((theme) => {
    localStorage.setItem("omher.theme", theme);
    localStorage.removeItem("omher.resume");
    localStorage.removeItem("omher.sessions.recent");
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function background(page: Page) {
  const box = (await page.getByTestId("side-sessions").boundingBox())!;
  const at = { x: box.x + box.width - 12, y: box.y + box.height - 10 };
  await page.mouse.click(at.x, at.y, { button: "right" });
  return at;
}

async function draft(page: Page) {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
}

const starts = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).filter((c) => c.op === "start" || c.op === "chat.start"));

test("empty session background opens a pointer menu, reuses the chooser and never starts an agent", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-search").focus();
  const at = await background(page);
  const menu = page.getByTestId("sessions-context-menu");
  const item = menu.getByRole("menuitem", { name: "New session", exact: true });
  await expect(item).toBeFocused();
  const box = (await menu.boundingBox())!;
  expect(Math.abs(box.x - at.x)).toBeLessThanOrEqual(168);
  expect(Math.abs(box.y - at.y)).toBeLessThanOrEqual(40);
  expect(box.x).toBeGreaterThanOrEqual(6);
  expect(box.x + box.width).toBeLessThanOrEqual(1280 - 6);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("End");
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowUp");
  await expect(item).toBeFocused();
  expect(await starts(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("bot-search")).toBeFocused();
  await background(page);
  await page.getByTestId("bot-search").click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("bot-search")).toBeFocused();
  await background(page);
  await page.keyboard.press("Enter");
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await expect(page.getByTestId("session-agent-claude")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-new")).toBeFocused();
  await background(page);
  await item.click();
  await page.getByTestId("session-agent-claude").click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  expect(await starts(page)).toEqual([]);
});

for (const theme of ["dark", "light"]) {
  test(`render compact view marks and populated background (${theme})`, async ({ page }) => {
    await open(page, theme);
    await draft(page);
    await page.getByTestId("composer").fill("Review the web-app layout");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    // A terminal draft gives both view marks without starting a second agent.
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-codex").click();
    await page.getByTestId("session-way-terminal").click();
    await page.getByTestId("bot-kami").click();
    await page.mouse.move(900, 780);
    const marks = await page.getByTestId("session-view").evaluateAll((els) => els.map((el) => {
      const svg = el.querySelector("svg")!.getBoundingClientRect();
      const row = el.closest(".ss-row")!.getBoundingClientRect();
      return { view: el.getAttribute("data-view"), label: el.getAttribute("aria-label"), width: svg.width, height: svg.height, rowWidth: row.width, rowHeight: row.height };
    }));
    const shots = process.env.OMHER_CONTEXT_SHOTS;
    const tag = process.env.OMHER_CAPTURE_BEFORE ? "before" : "after";
    if (shots) {
      mkdirSync(shots, { recursive: true });
      writeFileSync(join(shots, `marks-${tag}-${theme}.json`), JSON.stringify(marks, null, 2));
      await page.screenshot({ path: join(shots, `sessions-${tag}-${theme}.png`), animations: "disabled" });
    }
    if (process.env.OMHER_CAPTURE_BEFORE) return;
    expect(marks.map((m) => m.view).sort()).toEqual(["chat", "terminal"]);
    for (const mark of marks) {
      expect(mark.width).toBe(12);
      expect(mark.height).toBe(10);
      expect(mark.label).toMatch(/^(Chat|Terminal)$/);
      expect(mark.rowHeight).toBeGreaterThanOrEqual(40);
    }
    await background(page);
    await expect(page.getByTestId("sessions-context-menu")).toBeVisible();
    if (shots) await page.screenshot({ path: join(shots, `sessions-context-${theme}.png`), animations: "disabled" });
  });
}

test("row, rename input, buttons and chooser keep their own context; filter-empty still offers New session", async ({ page }) => {
  await open(page);
  await draft(page);
  await page.getByTestId("composer").fill("Review web-app");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  const row = page.locator(".ss-row").first();
  await row.click({ button: "right" });
  await expect(page.getByTestId("session-row-menu")).toBeVisible();
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await page.getByTestId("session-rename").click({ button: "right" });
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await page.getByTestId("session-rename").click();
  const input = page.getByTestId("session-rename-input");
  const native = await input.evaluate((el) => el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true })));
  expect(native).toBe(true);
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await input.press("Escape");
  await page.getByTestId("session-new").click({ button: "right" });
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click({ button: "right" });
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByTestId("bot-search").fill("no-matching-session");
  await expect(page.getByTestId("session-none-match")).toBeVisible();
  await background(page);
  await expect(page.getByTestId("sessions-context-menu").getByRole("menuitem")).toHaveText("New session");
});

test("background context menu fits a narrow viewport, follows resize and dismisses on Tab", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 480 });
  await open(page);
  await background(page);
  const menu = page.getByTestId("sessions-context-menu");
  await expect(menu).toBeVisible();
  await page.setViewportSize({ width: 560, height: 420 });
  const box = (await menu.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(6);
  expect(box.y).toBeGreaterThanOrEqual(6);
  expect(box.x + box.width).toBeLessThanOrEqual(554);
  expect(box.y + box.height).toBeLessThanOrEqual(414);
  await page.keyboard.press("Tab");
  await expect(menu).toHaveCount(0);
});
