// Elsewhere: header places chip, read-only away lines with peek, Details panel (where + routines).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls, mock.emit). */
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

const calls = async (): Promise<{ op: string; params: Record<string, unknown> }[]> => (await mock("mock.calls")).calls;

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

/** No text entry anywhere inside the read-only elsewhere UI. */
async function expectNoInputs(page: Page) {
  for (const scope of [page.getByTestId("away"), page.getByTestId("details")]) {
    expect(await scope.locator("textarea, input, [contenteditable=true], [contenteditable='']").count()).toBe(0);
  }
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("header chip counts the other places and toggles the panel", async ({ page }) => {
  await open(page);
  const chip = page.getByTestId("places");
  await expect(chip).toHaveText("3 other places");
  await expect(chip.locator(".src-sq")).toHaveCount(3);
  await expect(chip.locator(".src-sq.src-slack")).toHaveCount(1);
  await expect(chip.locator(".src-sq.src-discord")).toHaveCount(2);
  // the header right keeps exactly one control
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);

  const details = page.getByTestId("details");
  await chip.click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(300);
  await expect(chip).toHaveAttribute("aria-expanded", "true");
  await chip.click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBeLessThan(2);

  // a bot with no sessions elsewhere shows no chip
  await page.getByTestId("bot-default").click();
  await expect(page.getByTestId("header").getByText("Hermes", { exact: true })).toBeVisible();
  await expect(page.getByTestId("places")).toHaveCount(0);
  // Friren has one Telegram session
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("places")).toHaveText("1 other place");
});

test("away line expands to a read-only peek", async ({ page }) => {
  await open(page);
  const tl = page.getByTestId("timeline");
  const lines = tl.getByTestId("away");
  await expect(lines).toHaveCount(2); // newest two in the timeline; the rest live in the panel
  const slack = tl.locator('[data-testid=away][data-source=slack]');
  await expect(slack).toContainText("Slack");
  await expect(slack).toContainText("#og-dev › gateway 502 on /v1/responses");
  await expect(slack.getByTestId("away-time")).toHaveText(/^working · \d+m$/);
  await expect(slack.getByRole("status")).toBeVisible(); // spinner while the session works
  const discord = tl.locator('[data-testid=away][data-source=discord]');
  await expect(discord.getByTestId("away-time")).toHaveText(/^\d\d:\d\d$|^[A-Z][a-z]{2}( \d+)?$/);

  await expect(slack.getByTestId("peek")).toHaveCount(0);
  await slack.getByRole("button").click();
  const peek = slack.getByTestId("peek");
  await expect(peek).toBeVisible();
  await expect(peek.getByTestId("peek-msg")).toHaveCount(4);
  await expect(peek).toContainText("can we raise the pool idle timeout?");
  await expect(peek.getByTestId("peek-msg").first().locator("b")).toHaveText("Kami"); // assistant row → bot name
  await expect(peek.getByTestId("peek-msg").nth(1).locator("b")).toHaveText("jun");
  const openLink = peek.getByText("Open in Slack ↗");
  await expect(openLink).toHaveAttribute("title", "Opens in Slack");
  await expect(peek).toContainText("+10 messages · read-only here");
  // author bold, text gray and at most two lines
  const style = await peek.getByTestId("peek-msg").first().evaluate((el) => {
    const b = getComputedStyle(el.querySelector("b")!);
    const t = getComputedStyle(el.querySelector("span")!);
    return { weight: Number(b.fontWeight), clamp: t.getPropertyValue("-webkit-line-clamp"), color: t.color, bcolor: b.color };
  });
  expect(style.weight).toBeGreaterThanOrEqual(600);
  expect(style.clamp).toBe("2");
  expect(style.color).not.toBe(style.bcolor);

  // clicking "Open in Slack" opens nothing in v0.1
  const pages = page.context().pages().length;
  await openLink.click();
  expect(page.context().pages().length).toBe(pages);

  await expectNoInputs(page);
  const peeks = (await calls()).filter((c) => c.op === "elsewhere.peek");
  expect(peeks).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "kami", session_id: "slack-og-dev-502", limit: 4 }) }),
  ]);

  // collapse
  await slack.getByRole("button", { expanded: true }).click();
  await expect(slack.getByTestId("peek")).toHaveCount(0);
});

test("Details panel: identity, where the bot is, note, routines", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  const panel = page.getByTestId("details-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Hermes profile · kami · Opus 5.5");
  await expect(panel.getByTestId("where-sec")).toHaveText("Where Kami is4");

  const rows = panel.getByTestId("where-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("This chat");
  await expect(rows.nth(0)).toContainText("omher");
  await expect(rows.nth(1)).toContainText("#og-dev › gateway 502 on /v1/responses");
  await expect(rows.nth(1)).toContainText("Slack");
  await expect(rows.nth(1)).toContainText(/working · \d+m/);
  await expect(rows.nth(2)).toContainText("#cron › OpenMausBot 조사후 브리핑");
  await expect(rows.nth(3)).toContainText("#oh-my-hermes › PR #2657 review");
  await expect(rows.nth(3)).toContainText("Discord");

  await expect(panel.getByTestId("where-note")).toHaveText(
    "Talk to Kami here — it knows what it did in Slack and Discord. Those threads are read-only here; reply in their apps.",
  );

  await expect(panel.getByTestId("routines-sec")).toHaveText("Routines2");
  const routines = panel.getByTestId("routine-row");
  await expect(routines).toHaveCount(2);
  await expect(routines.nth(0)).toContainText("Repo watch");
  await expect(routines.nth(0)).toContainText(/next \d\d:\d\d/);
  await expect(routines.nth(0)).toContainText("daily");
  await expect(routines.nth(1)).toContainText("OG digest");
  await expect(routines.nth(1)).toContainText(/next (Sun|Mon|Tue|Wed|Thu|Fri|Sat)/);
  await expect(routines.nth(1)).toContainText("weekly");

  await expectNoInputs(page);
  // panel rows are plain read-only rows (no buttons that could act on another session)
  expect(await panel.getByTestId("where-list").locator("button, a, input, textarea").count()).toBe(0);

  await panel.getByRole("button", { name: "Close details" }).click();
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBeLessThan(2);
});

test("elsewhere.update re-fetches the list; nothing but peek names a session", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("where-row")).toHaveCount(4);
  const listed = (await calls()).filter((c) => c.op === "elsewhere.list").length;
  await mock("mock.emit", { events: [{ event: "elsewhere.update", bot: "kami" }] });
  await expect.poll(async () => (await calls()).filter((c) => c.op === "elsewhere.list").length).toBeGreaterThan(listed);
  await expect(page.getByTestId("where-row")).toHaveCount(4);

  // interact: open both away lines, send a message to the main chat
  for (const line of await page.getByTestId("timeline").getByTestId("away").all()) {
    await line.getByRole("button").first().click();
    await expect(line.getByTestId("peek")).toBeVisible();
  }
  await page.getByTestId("composer").fill("status?");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("bubble-user").filter({ hasText: "status?" })).toBeVisible();

  const all = await calls();
  const withSession = all.filter((c) => "session_id" in c.params);
  expect(withSession.length).toBeGreaterThanOrEqual(2);
  for (const c of withSession) expect(c.op, JSON.stringify(c)).toBe("elsewhere.peek");
  const send = all.filter((c) => c.op === "chat.send");
  expect(send).toEqual([expect.objectContaining({ params: { bot: "kami", text: "status?" } })]);
});

test("screenshots: dark and light with the panel and a peek open", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("routine-row")).toHaveCount(2);
  const slack = page.locator('[data-testid=away][data-source=slack]');
  await slack.getByRole("button").click();
  await expect(slack.getByTestId("peek-msg")).toHaveCount(4);
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "elsewhere-dark.png") });
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, "elsewhere-light.png") });
  await page.evaluate(() => localStorage.removeItem("omher.theme"));
});
