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
  await expect(page.getByTestId("usage-codex")).toHaveAttribute("aria-label", "Codex usage: 73%");
  // the meter calls only the read op
  const ops = (await mock("mock.calls")).calls.map((c: { op: string }) => c.op);
  expect(ops).toContain("usage.read");
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
  await expect(rows.nth(0)).toHaveText(/^5 hours\s*73%\s*resets in 1h 4[67]m$/);
  await expect(rows.nth(1)).toHaveText(/^Weekly\s*60%\s*resets in 4d 2[23]h$/);
  const radius = await card.evaluate((e) => getComputedStyle(e).borderRadius);
  expect(radius).toBe("8px");
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
  await expect(card.getByTestId("usage-window")).toContainText(/Weekly\s*Limited until (\w{3} )?\d{2}:\d{2}/);
  await expect(card).not.toContainText("%");
  await page.getByTestId("usage-grok").hover();
  await expect(page.getByTestId("usage-card")).toContainText("Connected · no usage record");
  await expect(page.getByTestId("usage-card")).not.toContainText("%");
});

test("a record past its reset time shows stale, with no number and no ring", async ({ page }) => {
  await mock("mock.usage", { fixture: "stale" });
  await open(page);
  await expect(page.getByTestId("usage").locator(".usage-m")).toHaveCount(1);
  await expect(page.getByTestId("usage-codex")).toHaveAttribute("data-state", "stale");
  await expect(page.getByTestId("usage-codex").getByTestId("usage-fill")).toHaveCount(0);
  await page.getByTestId("usage-codex").hover();
  const rows = page.getByTestId("usage-card").getByTestId("usage-window");
  await expect(rows).toHaveCount(2);
  for (const i of [0, 1]) await expect(rows.nth(i)).toContainText("stale");
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
