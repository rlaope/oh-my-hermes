// Sidebar usage meters (usage.read) and the agent marks. Read-only: the meters only read the CLIs' own files.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS_DIR || join(dirname(fileURLToPath(import.meta.url)), "__shots__");

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
  return reply.result;
}

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("usage")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("one mark per provider above the user row; rings only where the source gave a %", async ({ page }) => {
  await open(page);
  const usage = page.getByTestId("usage");
  await expect(usage.locator(".usage-m")).toHaveCount(3);
  await expect(page.getByTestId("usage-codex").locator('[data-agent="codex"]')).toHaveCount(1);
  await expect(page.getByTestId("usage-claude").locator('[data-agent="claude"]')).toHaveCount(1);
  await expect(page.getByTestId("usage-grok").locator('[data-agent="grok"]')).toHaveCount(1);
  // usage sits above the user row, inside the sidebar footer
  const [u, me] = await Promise.all([usage.boundingBox(), page.locator(".side .me").boundingBox()]);
  expect(u!.y + u!.height).toBeLessThanOrEqual(me!.y + 1);
  // codex 73 %: amber ring; claude and grok: no ring fill, a state dot instead
  await expect(page.getByTestId("usage-codex").getByTestId("usage-fill")).toHaveClass(/lv-amber/);
  await expect(page.getByTestId("usage-claude").getByTestId("usage-fill")).toHaveCount(0);
  await expect(page.getByTestId("usage-claude").locator(".usage-dot")).toHaveClass(/st-limited/);
  await expect(page.getByTestId("usage-grok").getByTestId("usage-fill")).toHaveCount(0);
  // no % from the source: no ring at all (an empty track reads as 0 %), and no dot when nothing is wrong
  await expect(page.getByTestId("usage-grok").locator(".usage-ring")).toHaveCount(0);
  await expect(page.getByTestId("usage-grok").locator(".usage-dot")).toHaveCount(0);
  await expect(page.getByTestId("usage-claude").locator(".usage-ring")).toHaveCount(0);
  // the marks sit on the nav icons' column: the first mark's centre matches the Settings icon's and the "Y"
  const cx = await page.evaluate(() => {
    const mid = (el: Element | null) => { const r = el!.getBoundingClientRect(); return r.left + r.width / 2; };
    return [mid(document.querySelector(".usage-m .usage-mark")), mid(document.querySelector("[data-testid=nav-settings] svg")), mid(document.querySelector(".me-i"))];
  });
  expect(Math.abs(cx[0] - cx[1]), `mark ${cx[0]} vs nav icon ${cx[1]}`).toBeLessThanOrEqual(1.5);
  expect(Math.abs(cx[0] - cx[2]), `mark ${cx[0]} vs user initial ${cx[2]}`).toBeLessThanOrEqual(1.5);
  await expect(page.getByTestId("usage-codex")).toHaveAttribute("aria-label", "Codex usage: 73%");
  // the meter calls only the read op
  const ops = (await mock("mock.calls")).calls.map((c: { op: string }) => c.op);
  expect(ops).toContain("usage.read");
});


test("Claude with five logins: the card lists each with only its own record, never a % it did not give", async ({ page }) => {
  await open(page);
  await page.getByTestId("usage-claude").hover();
  const card = page.getByTestId("usage-card");
  await expect(card.getByTestId("usage-accounts")).toContainText("5 logins");
  const rows = card.getByTestId("usage-account");
  await expect(rows).toHaveCount(5);
  await expect(rows.locator(".uc-who")).toHaveText(["owner@example.com", "ana@example.com", "ben@example.com", "cho@example.com", "team@example.org"]);
  await expect(rows.first().locator(".uc-state")).toHaveText(/^Limited until (\w{3} )?\d\d:\d\d$/);
  await expect(rows.nth(1).locator(".uc-state")).toHaveText("No record");
  await expect(card.getByTestId("usage-accounts")).not.toContainText("%");
  // the meter itself is unchanged: one Claude mark, no ring (Claude Code gives no %)
  await expect(page.getByTestId("usage-claude")).toHaveCount(1);
  await expect(page.getByTestId("usage-claude").locator(".usage-ring")).toHaveCount(0);
  // Codex has one login: no list
  await page.getByTestId("usage-codex").hover();
  await expect(page.getByTestId("usage-card").getByTestId("usage-accounts")).toHaveCount(0);
});
test("hover shows the card: plan, then each window with % and reset", async ({ page }) => {
  await open(page);
  await page.getByTestId("usage-codex").hover();
  const card = page.getByTestId("usage-card");
  await expect(card).toBeVisible();
  await expect(card.locator(".uc-head")).toContainText("Codex");
  await expect(card.locator(".uc-plan")).toHaveText("Pro");
  const rows = card.getByTestId("usage-window");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toHaveText(/^5-hour limit\s*73% used\s*Resets in 1h 4[67]m$/);
  await expect(rows.nth(1)).toHaveText(/^Weekly limit\s*60% used\s*Resets in 4d 2[23]h$/);
  // each window with a % gets a bar filled to it, coloured like the ring
  await expect(rows.nth(0).locator(".uc-bar > i")).toHaveClass(/lv-amber/);
  await expect(rows.nth(1).locator(".uc-bar > i")).toHaveClass(/lv-gray/);
  const w = await rows.nth(0).locator(".uc-bar").evaluate((b) => (b.firstElementChild as HTMLElement).offsetWidth / (b as HTMLElement).clientWidth);
  expect(w).toBeGreaterThan(0.7);
  expect(w).toBeLessThan(0.76);
  const radius = await card.evaluate((e) => getComputedStyle(e).borderRadius);
  expect(radius).toBe("8px");
  // the caret points at the hovered mark
  for (const id of ["codex", "claude"]) {
    await page.getByTestId(`usage-${id}`).hover();
    const [caret, mark] = await page.evaluate((id) => {
      const c = document.querySelector("[data-testid=usage-card]")!;
      const a = getComputedStyle(c, "::after");
      const left = c.getBoundingClientRect().left + parseFloat(a.left) + parseFloat(a.width) / 2;
      const m = document.querySelector(`[data-testid=usage-${id}]`)!.getBoundingClientRect();
      return [left, m.left + m.width / 2];
    }, id);
    expect(Math.abs(caret - mark), id).toBeLessThanOrEqual(1.5);
  }
  // the card starts on the first mark's edge and covers the nav rows' counts whole (never cuts one in half)
  const [cardBox, first, count] = await Promise.all([
    page.getByTestId("usage-card").boundingBox(), page.getByTestId("usage-codex").boundingBox(),
    page.locator("[data-testid=nav-automations] .nav-count").boundingBox(),
  ]);
  expect(Math.abs(cardBox!.x - first!.x)).toBeLessThanOrEqual(0.5);
  expect(cardBox!.x + cardBox!.width).toBeGreaterThanOrEqual(count!.x + count!.width);
  // moving away closes a hover card; a click pins it until outside click / Escape
  await page.getByTestId("bot-friren").hover();
  await expect(card).toHaveCount(0);
  await page.getByTestId("usage-codex").click();
  await page.getByTestId("bot-friren").hover();
  await expect(page.getByTestId("usage-card")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("usage-card")).toHaveCount(0);
});

test("Claude shows Limited until … and never a %", async ({ page }) => {
  await open(page);
  await page.getByTestId("usage-claude").hover();
  const card = page.getByTestId("usage-card");
  await expect(card.locator(".uc-head")).toContainText("Claude Code");
  await expect(card.getByTestId("usage-window")).toHaveCount(1);
  await expect(card.getByTestId("usage-window")).toContainText(/Weekly limit\s*Limited until (\w{3} )?\d{2}:\d{2}/);
  await expect(card).not.toContainText("%");
  await page.getByTestId("usage-grok").hover();
  await expect(page.getByTestId("usage-card").getByTestId("usage-empty")).toHaveText("No usage yet");
  // one line: the state sits in the head, where a plan would
  await expect(page.getByTestId("usage-card").locator(".uc-head [data-testid=usage-empty]")).toHaveCount(1);
  await expect(page.getByTestId("usage-card").locator(".uc-bar")).toHaveCount(0);
  await expect(page.getByTestId("usage-card")).not.toContainText("%");
});

test("a record past its reset time says No recent record, with no number and no ring", async ({ page }) => {
  await mock("mock.usage", { fixture: "stale" });
  await open(page);
  await expect(page.getByTestId("usage").locator(".usage-m")).toHaveCount(1);
  await expect(page.getByTestId("usage-codex")).toHaveAttribute("data-state", "stale");
  await expect(page.getByTestId("usage-codex").getByTestId("usage-fill")).toHaveCount(0);
  await page.getByTestId("usage-codex").hover();
  const rows = page.getByTestId("usage-card").getByTestId("usage-window");
  await expect(rows).toHaveCount(2);
  for (const i of [0, 1]) await expect(rows.nth(i)).toContainText("No recent record");
  await expect(page.getByTestId("usage-codex").locator(".usage-dot")).toHaveClass(/st-stale/);
  await expect(page.getByTestId("usage-card")).not.toContainText("%");
});

test("screenshots: the 22 agent marks and the usage card, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await page.setViewportSize({ width: 920, height: 330 });
    await page.goto(`/e2e/agents.html?theme=${theme}`);
    await expect(page.getByTestId("agent-grid").locator("[data-testid^=agent-cell-]")).toHaveCount(23);
    await expect(page.locator('[data-agent="letter"]')).toHaveCount(2);
    await page.screenshot({ path: join(SHOTS, `T7-agents-${theme}.png`) });
  }
  for (const theme of ["dark", "light"] as const) {
    await page.setViewportSize({ width: 1100, height: 720 });
    await open(page, theme);
    await page.getByTestId("usage-codex").hover();
    await expect(page.getByTestId("usage-card")).toBeVisible();
    await page.screenshot({ path: join(SHOTS, `T10-usage-codex-${theme}.png`), clip: { x: 0, y: 380, width: 420, height: 340 }, animations: "disabled" });
    await page.getByTestId("usage-claude").hover();
    await expect(page.getByTestId("usage-card")).toContainText("Limited until");
    await page.screenshot({ path: join(SHOTS, `T10-usage-claude-${theme}.png`), clip: { x: 0, y: 380, width: 420, height: 340 }, animations: "disabled" });
  }
});
