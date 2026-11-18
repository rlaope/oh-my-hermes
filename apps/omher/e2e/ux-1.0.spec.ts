// The 1.0 usability pass, as a person meets it: a search that finds no bot says so where it can be seen, the side
// panel speaks the UI language (its time words, a routine's cadence and last run), a bot with nothing elsewhere gets
// no note about Slack threads it does not have, and Settings shows whole names (the in-use model, a profile id).
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
      if (msg.id === "u1") res(msg);
    };
    ws.send(JSON.stringify({ id: "u1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function open(page: Page, lang?: string) {
  if (lang) await page.addInitScript((l) => localStorage.setItem("omher.lang", l), lang);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a search with no bot shows its one line between the search and TERMINALS, not under TERMINALS", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-search").fill("zzzz");
  const empty = page.getByTestId("side-bots").locator(".bot-empty");
  await expect(empty).toHaveText("No bot named “zzzz”");
  await expect(empty).toBeInViewport();
  const box = await page.evaluate(() => {
    const line = document.querySelector("[data-testid=side-bots] .bot-empty")!.getBoundingClientRect();
    const sec = document.querySelector("[data-testid=side-bots]")!.getBoundingClientRect();
    const head = document.querySelector("[data-testid=side-sessions] .side-sh")!.getBoundingClientRect();
    const hit = document.elementFromPoint(line.left + 20, line.top + line.height / 2);
    return { secH: sec.height, lineInSec: line.bottom <= sec.bottom + 0.5, above: line.bottom <= head.top + 0.5, own: !!hit?.closest(".bot-empty") };
  });
  expect(box.secH).toBeGreaterThan(0);
  expect(box).toMatchObject({ lineInSec: true, above: true, own: true });
});

test("Details on a bot with nothing elsewhere: no Slack-thread note, and its time word is the UI language's", async ({ page }) => {
  await open(page, "ko");
  await page.getByTestId("bot-omh-tui").click();
  await expect(page.getByTestId("bot-omh-tui")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("panel-button").click();
  const panel = page.getByTestId("details-panel");
  await expect(panel.getByTestId("where-row")).toHaveCount(1);
  // "now" was English in every language
  await expect(panel.getByTestId("where-row").locator(".st")).toHaveText("지금");
  const note = panel.getByTestId("where-note");
  await expect(note).toContainText("OMH TUI");
  // no "Reply there" / ↗ when there is nothing to reply to or open
  await expect(note).not.toContainText("↗");
  await expect(note).not.toContainText("답장");
});

test("Details › Routines and the Schedule tab say cadence and last run in the UI language", async ({ page }) => {
  await open(page, "ko");
  await page.getByTestId("panel-button").click();
  const routines = page.getByTestId("details-panel").getByTestId("routine-row");
  await expect(routines).toHaveCount(2);
  await expect(routines.nth(0)).toContainText("매일");
  await expect(routines.nth(1)).toContainText("매주");
  await expect(routines.nth(0)).not.toContainText("daily");
  await page.getByTestId("panel-tab-schedule").click();
  const rows = page.getByTestId("panel-routine");
  await expect(rows).toHaveCount(2);
  for (const i of [0, 1]) {
    const st = rows.nth(i).locator(".pn-st");
    // Hermes' raw "ok" became a word
    await expect(st).not.toHaveText("ok");
    await expect(st).toHaveText("완료");
  }
  await expect(page.getByTestId("panel-schedule")).not.toContainText(/\b(daily|weekly)\b/);
});

test("Settings: the in-use model's name is whole, and a profile id chip stays on one line", async ({ page }) => {
  await open(page);
  // OMH TUI runs Sonnet 5.5: the longest of its provider's three names, and the one with the check
  await page.getByTestId("bot-omh-tui").click();
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-providers").click();
  const on = page.locator("[data-testid=provider-model].on");
  await expect(on).toHaveAttribute("data-id", "Sonnet 5.5");
  const clip = await on.locator(".pv-mn").evaluate((n) => n.scrollWidth - n.clientWidth);
  expect(clip).toBeLessThanOrEqual(0);
  // the chips of a provider with no vendor prefix share a row, not one per line under an empty vendor column
  const tops = await page.locator("[data-testid=provider-model]").evaluateAll((els) => new Set(els.map((e) => Math.round(e.getBoundingClientRect().top))).size);
  expect(tops).toBe(1);

  await page.getByTestId("settings-nav-bots").click();
  const chip = page.getByTestId("bot-card-omh-tui").locator(".bc-id code");
  await expect(chip).toHaveText("omh-tui");
  expect(await chip.evaluate((c) => c.getClientRects().length)).toBe(1);
  const h = await chip.evaluate((c) => c.getBoundingClientRect().height);
  expect(h).toBeLessThan(20);
});
