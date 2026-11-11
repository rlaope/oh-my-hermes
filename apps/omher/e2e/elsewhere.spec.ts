// Elsewhere: header places chip, away lines that link to their thread, Details panel (where + routines).
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
  // one app mark per place (1 Slack + 2 Discord sessions -> Slack and Discord marks), not one per session
  await expect(chip.locator(".src-ic")).toHaveCount(2);
  await expect(chip.locator(".src-ic-slack")).toHaveCount(1);
  await expect(chip.locator(".src-ic-discord")).toHaveCount(1);
  await expect(chip.locator(".src-sq")).toHaveCount(0);
  // the header right keeps the model control and the panel button, nothing else
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(2);

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

test("elsewhere shows the bot's last answer as a bubble with a link to the thread", async ({ page }) => {
  const opened: string[] = [];
  await page.exposeFunction("__omherOpened", (u: string) => opened.push(u));
  await page.addInitScript(() => {
    window.open = ((u: string) => {
      (window as unknown as { __omherOpened: (u: string) => void }).__omherOpened(String(u));
      return null;
    }) as typeof window.open;
  });
  await open(page);
  const tl = page.getByTestId("timeline");
  await expect(tl.getByTestId("away")).toHaveCount(2); // newest two in the timeline; the rest live in the panel
  const slack = tl.locator('[data-testid=away][data-source=slack]');
  // same bubble as a bot answer
  await expect(slack).toHaveClass(/\bmsg\b.*\ba\b/);
  const [bg, botBg] = await Promise.all([
    slack.locator(".b").evaluate((e) => getComputedStyle(e).backgroundColor),
    tl.getByTestId("bubble-bot").first().locator(".b").evaluate((e) => getComputedStyle(e).backgroundColor),
  ]);
  expect(bg).toBe(botBg);
  await expect(slack.getByTestId("away-text")).toHaveText("Reading gateway logs from 14:31. Upstream resets look like keep-alive expiry.");
  await expect(slack.getByTestId("away-time")).toContainText(/working · \d+m/);
  const link = slack.getByTestId("away-link");
  await expect(link).toHaveText("Slack #og-dev");
  await expect(link).toHaveAttribute("href", /^slack:\/\/channel\?/);
  // the Slack mark sits right before the underlined place name, inside the same link
  const mark = link.locator("svg.src-ic-slack");
  await expect(mark).toBeVisible();
  const [mb, tb] = await Promise.all([mark.boundingBox(), link.locator(".ew-lt").boundingBox()]);
  expect(mb!.x + mb!.width).toBeLessThanOrEqual(tb!.x + 1);
  expect(Math.abs(mb!.y + mb!.height / 2 - (tb!.y + tb!.height / 2))).toBeLessThan(3);
  await expect(link.locator(".ew-lt")).toHaveCSS("text-decoration-line", "underline");
  const discord = tl.locator('[data-testid=away][data-source=discord]').first();
  await expect(discord.locator("svg.src-ic-discord")).toBeVisible();

  await link.click();
  await expect.poll(() => opened).toEqual([expect.stringMatching(/^slack:\/\/channel\?team=T1&id=C1/)]);
  // the thread's history is never replayed or read here
  await expect(page.getByTestId("peek")).toHaveCount(0);
  expect((await calls()).filter((c) => c.op === "elsewhere.peek")).toEqual([]);
  await expectNoInputs(page);
});

test("a session with no answer yet falls back to its title", async ({ page }) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "elsewhere.list" && msg.ok) {
        for (const s of msg.result.sessions) s.last_reply = null;
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const slack = page.getByTestId("timeline").locator('[data-testid=away][data-source=slack]');
  await expect(slack.getByTestId("away-text")).toHaveText("gateway 502 on /v1/responses");
});

test("Details panel: identity, where the bot is, note, routines", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  const panel = page.getByTestId("details-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Hermes profile · kami");
  await expect(panel.locator(".details-sub.mono")).toHaveText("Opus 5.5");
  await expect(panel.getByTestId("where-sec")).toHaveText("Where Kami is4");

  const rows = panel.getByTestId("where-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("This chat");
  await expect(rows.nth(0)).toContainText("omher");
  await expect(rows.nth(1)).toContainText("gateway 502 on /v1/responses");
  await expect(rows.nth(1)).toContainText("Slack #og-dev");
  await expect(rows.nth(1)).toContainText(/working · \d+m/);
  await expect(rows.nth(2)).toContainText("OpenMausBot 조사후 브리핑");
  await expect(rows.nth(3)).toContainText("PR #2657 review");
  await expect(rows.nth(3)).toContainText("Discord #oh-my-hermes");

  await expect(panel.getByTestId("where-note")).toHaveText(
    "Talk to Kami here — it knows what it did in Slack and Discord. Replies to those threads go in their own apps.",
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
  // the only controls on other sessions are links out to their own apps
  const links = panel.getByTestId("where-list").locator("a");
  await expect(links).toHaveCount(3);
  for (const l of await links.all()) await expect(l).toHaveAttribute("href", /^(slack:\/\/|https:\/\/discord\.com\/channels\/)/);
  expect(await panel.getByTestId("where-list").locator("input, textarea, [contenteditable]").count()).toBe(0);

  await panel.getByRole("button", { name: "Close details" }).click();
  await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBeLessThan(2);
});

test("elsewhere.update re-fetches the list; no request names another session", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("where-row")).toHaveCount(4);
  const listed = (await calls()).filter((c) => c.op === "elsewhere.list").length;
  await mock("mock.emit", { events: [{ event: "elsewhere.update", bot: "kami" }] });
  await expect.poll(async () => (await calls()).filter((c) => c.op === "elsewhere.list").length).toBeGreaterThan(listed);
  await expect(page.getByTestId("where-row")).toHaveCount(4);

  // send a message to the main chat
  await page.getByTestId("composer").fill("status?");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("bubble-user").filter({ hasText: "status?" })).toBeVisible();

  const all = await calls();
  expect(all.filter((c) => "session_id" in c.params)).toEqual([]); // no request ever names another session
  const send = all.filter((c) => c.op === "chat.send");
  expect(send).toEqual([expect.objectContaining({ params: { bot: "kami", text: "status?" } })]);
});

test("panel shows the 6 latest sessions, running first, and Show all for the rest", async ({ page }) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "elsewhere.list" && msg.ok && msg.result.sessions.length) {
        const t = msg.result.sessions[0].last_active;
        for (let i = 0; i < 6; i++)
          msg.result.sessions.push({ id: `cron-${i}`, source: "cron", label: `superagent-observe run ${i + 1}`, title: "",
            started_at: t - 9000 - i * 3600, last_active: t - 8000 - i * 3600, message_count: 2, running: false, url: null, place: null });
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  await page.getByTestId("places").click();
  const panel = page.getByTestId("details-panel");
  const rows = panel.getByTestId("where-row");
  await expect(rows).toHaveCount(7); // This chat + 6
  await expect(rows.nth(1)).toContainText(/working/); // running first
  await expect(panel.getByTestId("routines-sec")).toBeInViewport();
  await panel.getByTestId("where-more").click();
  await expect(rows).toHaveCount(10);
  await expect(panel.getByTestId("where-more")).toHaveText("Show fewer");
});

test("screenshots: dark and light with the panel open", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("routine-row")).toHaveCount(2);
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
