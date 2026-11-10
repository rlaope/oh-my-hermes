// Activity line: one row per turn that slides through steps, a skill chip, elapsed time, then collapses
// to "Worked for … · N steps" with step details on click. Tool calls never get their own timeline rows.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS_DIR || "test-results/activity-shots";

test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.emit). */
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
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

/** Records every distinct text the live activity line shows, from inside the page. */
async function recordTexts(page: Page) {
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as any).__actTexts = seen;
    const grab = () => {
      const live = document.querySelector('[data-testid=activity][data-state=live] [data-testid=activity-text]');
      const t = live?.textContent?.trim();
      if (t && seen[seen.length - 1] !== t) seen.push(t);
    };
    new MutationObserver(grab).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
}

async function send(page: Page, text: string) {
  const box = page.getByTestId("composer");
  await box.fill(text);
  await box.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("live line slides through steps with a skill chip, then collapses with details", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await open(page);
  await recordTexts(page);
  await send(page, "Check the 502s please");

  const tl = page.getByTestId("timeline");
  const live = tl.locator("[data-testid=activity][data-state=live]");
  await expect(live).toHaveCount(1);
  await expect(live.getByTestId("activity-elapsed")).toHaveText(/^\d+s$/);
  const chip = live.getByTestId("activity-skill");
  await expect(chip).toHaveText("/plan");
  // brand gradient on the chip, mono 11px
  const chipStyle = await chip.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundImage, size: cs.fontSize, font: cs.fontFamily };
  });
  expect(chipStyle.bg).toContain("linear-gradient");
  expect(chipStyle.size).toBe("11px");
  expect(chipStyle.font).toMatch(/mono|Menlo/i);
  await page.screenshot({ path: `${SHOTS}/activity-live.png` });

  // ends collapsed
  const act = tl.getByTestId("activity").last();
  await expect(act).toHaveAttribute("data-state", "done", { timeout: 10_000 });
  await expect(act.getByTestId("activity-text")).toHaveText(/^Worked for \d+s · 4 steps$/);
  await expect(act.getByTestId("activity-details")).toHaveCount(0);
  await expect(act.getByTestId("activity-skill")).toHaveCount(0);
  await expect(act.getByTestId("activity-elapsed")).toHaveCount(0);
  await expect(tl.getByTestId("bubble-bot").last()).toContainText("keep-alive");

  const texts: string[] = await page.evaluate(() => (window as any).__actTexts);
  expect(texts.length, JSON.stringify(texts)).toBeGreaterThanOrEqual(4); // first text + at least 3 changes
  expect(texts).toEqual(
    expect.arrayContaining(["Running git log --oneline -5", "Reading src/gateway/router.py", "Searching 502 upstream"]),
  );

  // click → one row per step
  await act.getByTestId("activity-toggle").click();
  await expect(act.getByTestId("activity-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(act.locator(".act-chev")).toHaveCSS("transform", /^matrix\([^,]+, 1, -1,/); // rotated 90°
  const rows = act.getByTestId("activity-step");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("git log --oneline -5");
  await expect(rows.nth(0).locator(".k")).toHaveText("Ran");
  await expect(rows.nth(1).locator(".k")).toHaveText("Used skill");
  await expect(rows.nth(0).locator(".s")).toHaveText(/^\d+(\.\d)?s$/);
  await page.screenshot({ path: `${SHOTS}/activity-done-open.png` });
  await act.getByTestId("activity-toggle").click();
  await expect(act.getByTestId("activity-details")).toHaveCount(0);

  // no per-tool rows anywhere in the timeline outside the activity element
  const kinds = await tl.locator(":scope > .row").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
  expect(kinds.every((k) => ["user", "assistant", "activity", "away", "routine", "streaming", "typing"].includes(k ?? "")))
    .toBe(true);
  expect(kinds.filter((k) => k === "activity")).toHaveLength(1);
  const outside = await tl.evaluate((el) => {
    const clone = el.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("[data-testid=activity]").forEach((a) => a.remove());
    return clone.textContent ?? "";
  });
  for (const t of ["git log --oneline -5", "src/gateway/router.py", "502 upstream", "/plan"]) {
    expect(outside).not.toContain(t);
  }
});

test("Stop ends the line as 'Stopped after Xs'", async ({ page }) => {
  await open(page);
  await send(page, "Check the 502s please");
  await expect(page.getByTestId("activity")).toHaveAttribute("data-state", "live");
  await page.getByTestId("stop").click();
  const act = page.getByTestId("activity").last();
  await expect(act).toHaveAttribute("data-state", "interrupted");
  await expect(act.getByTestId("activity-text")).toHaveText(/^Stopped after \d+s$/);
});

test("a failed step shows red in the details; elapsed ticks each second", async ({ page }) => {
  await open(page);
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", ...extra });
  await mock("mock.emit", {
    events: [
      ev("turn.start"),
      ev("tool.start", { tool_id: "f1", name: "read_file", detail: "gateway.log" }),
      ev("tool.end", { tool_id: "f1", name: "read_file", ok: true, ms: 10 }),
      ev("tool.start", { tool_id: "f2", name: "terminal", detail: "pnpm test auth" }),
      ev("tool.end", { tool_id: "f2", name: "terminal", ok: false, ms: 10 }),
    ],
  });
  const act = page.getByTestId("activity");
  await expect(act).toHaveAttribute("data-state", "live");
  const el = act.getByTestId("activity-elapsed");
  await expect(el).toHaveText("0s");
  await expect(el).toHaveText("1s", { timeout: 3000 });
  await expect(el).toHaveText("2s", { timeout: 3000 });
  await mock("mock.emit", { events: [ev("turn.end", { outcome: "done" })] });
  await expect(act).toHaveAttribute("data-state", "done");
  await expect(act.getByTestId("activity-text")).toHaveText(/^Worked for \d+s · 2 steps$/);
  await act.getByTestId("activity-toggle").click();
  const failed = act.locator("[data-testid=activity-step][data-ok=false]");
  await expect(failed).toHaveCount(1);
  await expect(failed).toContainText("pnpm test auth");
  const [bad, good] = await Promise.all([
    failed.locator(".v").evaluate((e) => getComputedStyle(e).color),
    act.locator("[data-testid=activity-step][data-ok=true] .v").evaluate((e) => getComputedStyle(e).color),
  ]);
  expect(bad).toBe("rgb(240, 138, 138)"); // --danger (dark)
  expect(good).not.toBe(bad);
});

test("reduced motion: the text swaps without sliding", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", ...extra });
  await mock("mock.emit", { events: [ev("turn.start"), ev("status", { text: "Looking into it…" })] });
  const act = page.getByTestId("activity");
  await expect(act.getByTestId("activity-text")).toHaveText("Looking into it…");
  await mock("mock.emit", { events: [ev("tool.start", { tool_id: "r1", name: "read_file", detail: "a.txt" })] });
  await expect(act.getByTestId("activity-text")).toHaveText("Reading a.txt");
  const anim = await act.getByTestId("activity-text").evaluate((e) => getComputedStyle(e).animationName);
  expect(anim).toBe("none");
  await expect(act.locator(".act-tick-t.out")).toBeHidden();
  await mock("mock.emit", { events: [ev("turn.end", { outcome: "done" })] });
  await expect(act).toHaveAttribute("data-state", "done");
});
