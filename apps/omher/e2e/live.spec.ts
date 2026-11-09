// Answer in progress: a thin rotating ring around the bot's face in the sidebar, the live step sliding through
// the row preview with typing dots, the amber needs-you dot taking over while an ask is open, a typing bubble
// with the ringed face in the chat until the first delta, the same ring on a working away session's mark, and
// a still ring and still dots under reduced motion.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (LIVE_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.LIVE_SHOTS || "test-results/live-shots";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "l1") res(msg);
    };
    ws.send(JSON.stringify({ id: "l1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const ev = (bot: string, event: string, extra: Record<string, unknown> = {}) => ({ event, bot, ...extra });
const emit = (...events: Record<string, unknown>[]) => mock("mock.emit", { events });

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toContainText("updater");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("sidebar: turn.start rings the face, the live step slides into the preview, turn.end clears it", async ({ page }) => {
  await open(page);
  const row = page.getByTestId("bot-friren");
  const sub = row.getByTestId("bot-sub");
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  const before = await row.locator(".bot-m").boundingBox();

  await emit(ev("friren", "turn.start"));
  const ring = row.getByTestId("live-ring");
  await expect(ring).toBeVisible();
  await expect(row.getByTestId("live-dot")).toHaveCount(0);
  // no step yet: Thinking…, then the typing dots at the end of the line
  await expect(sub).toHaveText("Thinking…");
  await expect(row.getByTestId("bot-typing")).toBeVisible();
  await expect(row.getByTestId("bot-typing").locator("i")).toHaveCount(3);
  // the dots end the preview text, not the row
  const gapPx = await row.evaluate((el) => {
    const t = el.querySelector("[data-testid=bot-sub]")!.getBoundingClientRect();
    const d = el.querySelector("[data-testid=bot-typing]")!.getBoundingClientRect();
    return d.left - t.right;
  });
  expect(gapPx).toBeGreaterThanOrEqual(0);
  expect(gapPx).toBeLessThan(12);

  // the ring hugs the 34px face from outside: 1.5px arc, rotating, absolutely placed, no layout shift
  const geo = await ring.evaluate((el) => {
    const cs = getComputedStyle(el);
    // the rotation turns the box, so measure the unrotated layout box (offset + size), not the client rect
    const svg = el as unknown as SVGSVGElement;
    const c = el.querySelector("circle.ui-ring-arc")!;
    return {
      pos: cs.position,
      anim: cs.animationName,
      dur: cs.animationDuration,
      w: svg.width.baseVal.value,
      dx: -parseFloat(cs.left),
      dy: -parseFloat(cs.top),
      stroke: c.getAttribute("stroke-width"),
      cap: c.getAttribute("stroke-linecap"),
      grad: c.getAttribute("stroke"),
    };
  });
  expect(geo.pos).toBe("absolute");
  expect(geo.anim).toBe("ui-ring-turn");
  expect(geo.dur).toBe("1.2s");
  expect(geo.w).toBeCloseTo(41, 0);
  expect(geo.dx).toBeCloseTo(3.5, 0);
  expect(geo.dy).toBeCloseTo(3.5, 0);
  expect(geo.stroke).toBe("1.5");
  expect(geo.cap).toBe("round");
  expect(geo.grad).toMatch(/^url\(#ring/);
  expect(await row.locator(".bot-m").boundingBox()).toEqual(before);

  // the live step from the activity line, sliding up like it
  await emit(ev("friren", "tool.start", { tool_id: "f1", name: "read_file", detail: "gateway.log" }));
  await expect(sub.getByTestId("tick-text")).toHaveText("Reading gateway.log");
  await expect(sub.locator(".ui-tick-t.in")).toHaveCSS("animation-name", "ui-tick-in");
  await emit(ev("friren", "tool.end", { tool_id: "f1", name: "read_file", ok: true }));
  await emit(ev("friren", "tool.start", { tool_id: "f2", name: "terminal", detail: "pnpm test" }));
  await expect(sub.getByTestId("tick-text")).toHaveText("Running pnpm test");

  await emit(ev("friren", "turn.end", { outcome: "done" }));
  await expect(ring).toHaveCount(0);
  await expect(row.getByTestId("bot-typing")).toHaveCount(0);
  await expect(sub).not.toHaveText(/Running|Thinking/);
  expect(await row.locator(".bot-m").boundingBox()).toEqual(before);
});

test("needs you overrides the ring: an open ask shows the amber dot, answering it brings the ring back", async ({ page }) => {
  await open(page);
  const row = page.getByTestId("bot-friren");
  await emit(ev("friren", "turn.start"), ev("friren", "tool.start", { tool_id: "f1", name: "terminal", detail: "ls" }));
  await expect(row.getByTestId("live-ring")).toBeVisible();

  await emit(
    ev("friren", "approval.request", { request_id: "ap-live", title: "Run shell command", command: "rm -rf build/", choices: ["once", "deny"] }),
  );
  await expect(row.getByTestId("needs")).toBeVisible();
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
  await expect(row.getByTestId("bot-typing")).toHaveCount(0);
  await expect(row.getByTestId("bot-sub")).toHaveText("Allow rm -rf build/?");

  await emit(ev("friren", "prompt.expired", { request_id: "ap-live", reason: "timeout" }));
  await expect(row.getByTestId("needs")).toHaveCount(0);
  await expect(row.getByTestId("live-ring")).toBeVisible();

  await emit(ev("friren", "turn.end", { outcome: "done" }));
  await expect(row.getByTestId("live-ring")).toHaveCount(0);
});

test("chat: a typing bubble with the ringed face waits for the first delta, which replaces it", async ({ page }) => {
  await open(page);
  const tl = page.getByTestId("timeline");
  // the mock starts Kami as busy elsewhere; give it a clean turn of its own
  await emit(ev("kami", "turn.start"));
  const typing = tl.getByTestId("typing");
  await expect(typing).toBeVisible();
  await expect(typing.getByTestId("typing-ring")).toBeVisible();
  await expect(typing.locator(".msg-face")).toHaveCount(1);
  await expect(typing.getByTestId("typing-bubble").locator(".ui-typing i")).toHaveCount(3);
  const dot = typing.locator(".ui-typing i").first();
  await expect(dot).toHaveCSS("animation-name", "ui-typing-hop");
  await expect(dot).toHaveCSS("animation-duration", "1s");
  // same bubble fill as a bot answer
  const [bg, botBg] = await Promise.all([
    typing.getByTestId("typing-bubble").evaluate((e) => getComputedStyle(e).backgroundColor),
    tl.getByTestId("bubble-bot").first().locator(".b").evaluate((e) => getComputedStyle(e).backgroundColor),
  ]);
  expect(bg).toBe(botBg);
  // as tall as the one-line bubble that replaces it
  const [th, bh] = await Promise.all([
    typing.getByTestId("typing-bubble").evaluate((e) => e.getBoundingClientRect().height),
    tl.getByTestId("bubble-user").last().locator(".b").evaluate((e) => e.getBoundingClientRect().height),
  ]);
  expect(Math.abs(th - bh)).toBeLessThan(1.5);
  // the face is centred on the bubble
  const [fb, bb] = await Promise.all([typing.locator(".msg-face").boundingBox(), typing.getByTestId("typing-bubble").boundingBox()]);
  expect(Math.abs(fb!.y + fb!.height / 2 - (bb!.y + bb!.height / 2))).toBeLessThan(1.5);
  // it sits under the activity line, last in the thread
  const last = await tl.locator(":scope > .row").last().getAttribute("data-kind");
  expect(last).toBe("typing");

  // tools run, still nothing said: it stays
  await emit(ev("kami", "tool.start", { tool_id: "k1", name: "terminal", detail: "pnpm test" }));
  await expect(page.getByTestId("activity").last().getByTestId("activity-text")).toContainText("pnpm test");
  await expect(typing).toBeVisible();

  await emit(ev("kami", "delta", { text: "Found it: the" }));
  await expect(tl.getByTestId("bubble-streaming")).toContainText("Found it");
  await expect(tl.getByTestId("typing")).toHaveCount(0);

  await emit(ev("kami", "message", { id: "k-a1", text: "Found it: the retry cap." }), ev("kami", "turn.end", { outcome: "done" }));
  await expect(tl.getByTestId("bubble-bot").last()).toHaveText("Found it: the retry cap.");
  await expect(tl.getByTestId("typing")).toHaveCount(0);
});

test("chat: an approval card replaces the typing bubble while the bot waits on you", async ({ page }) => {
  await open(page);
  await emit(ev("kami", "turn.start"));
  const tl = page.getByTestId("timeline");
  await expect(tl.getByTestId("typing")).toBeVisible();
  await emit(ev("kami", "approval.request", { request_id: "ap-k", title: "Run shell command", command: "rm -rf build/", choices: ["once", "deny"] }));
  await expect(tl.locator('[data-kind="approval"]')).toBeVisible();
  await expect(tl.getByTestId("typing")).toHaveCount(0);
  await emit(ev("kami", "turn.end", { outcome: "interrupted" }));
});

test("away bubbles: a session still working there rings its source mark instead of a spinner", async ({ page }) => {
  await open(page);
  const tl = page.getByTestId("timeline");
  const slack = tl.locator("[data-testid=away][data-source=slack]");
  await expect(slack.getByTestId("away-time")).toContainText(/working · \d+m/);
  await expect(slack.locator(".ui-spin")).toHaveCount(0);
  const ring = slack.getByTestId("away-ring");
  await expect(ring).toBeVisible();
  await expect(ring).toHaveCSS("animation-name", "ui-ring-turn");
  // the ring wraps the Slack mark inside the link
  const wraps = await ring.evaluate((el) => {
    const mark = el.parentElement!.querySelector("svg.src-ic-slack")!.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return r.left < mark.left && r.right > mark.right && r.top < mark.top && r.bottom > mark.bottom && !!el.closest("[data-testid=away-link]");
  });
  expect(wraps).toBe(true);
  // a finished session has no ring
  await expect(tl.locator("[data-testid=away][data-source=discord]").getByTestId("away-ring")).toHaveCount(0);
});

test("reduced motion: the arc and the dots stand still", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  await emit(ev("kami", "turn.start"), ev("friren", "turn.start"));
  const ring = page.getByTestId("bot-friren").getByTestId("live-ring");
  await expect(ring).toBeVisible();
  await expect(ring).toHaveCSS("animation-name", "none");
  // still an arc, not a full circle
  await expect(ring.locator("circle.ui-ring-arc")).toHaveAttribute("stroke-dasharray", "40 60");
  for (const dot of await page.getByTestId("bot-friren").locator(".ui-typing i").all()) await expect(dot).toHaveCSS("animation-name", "none");
  const typing = page.getByTestId("typing");
  await expect(typing.getByTestId("typing-ring")).toHaveCSS("animation-name", "none");
  for (const dot of await typing.locator(".ui-typing i").all()) await expect(dot).toHaveCSS("animation-name", "none");
  await expect(page.locator("[data-testid=away][data-source=slack]").getByTestId("away-ring")).toHaveCSS("animation-name", "none");
  await emit(ev("friren", "tool.start", { tool_id: "r1", name: "read_file", detail: "a.txt" }));
  const sub = page.getByTestId("bot-friren").getByTestId("bot-sub");
  await expect(sub.getByTestId("tick-text")).toHaveText("Reading a.txt");
  await expect(sub.locator(".ui-tick-t.in")).toHaveCSS("animation-name", "none");
  await emit(ev("kami", "turn.end", { outcome: "done" }), ev("friren", "turn.end", { outcome: "done" }));
});

// Retina, like the Macs omher runs on: a 1.5px arc at 1x is a blur of two half-lit pixels.
test.describe("screenshots", () => {
test.use({ deviceScaleFactor: 2 });
for (const theme of ["dark", "light"] as const) {
  test(`screenshot T12b-live-${theme}: sidebar rings, needs-you, typing bubble`, async ({ page }) => {
    mkdirSync(SHOTS, { recursive: true });
    await page.setViewportSize({ width: 1280, height: 820 });
    await open(page, theme);
    await emit(
      ev("kami", "turn.start"),
      ev("kami", "tool.start", { tool_id: "s1", name: "terminal", detail: "pnpm test" }),
      ev("friren", "turn.start"),
      ev("friren", "tool.start", { tool_id: "s2", name: "read_file", detail: "gateway.log" }),
    );
    await mock("mock.ask", { bot: "default", kind: "approval" });
    await expect(page.getByTestId("bot-default").getByTestId("needs")).toBeVisible();
    await expect(page.getByTestId("bot-kami").getByTestId("tick-text")).toHaveText("Running pnpm test");
    await expect(page.getByTestId("bot-friren").getByTestId("tick-text")).toHaveText("Reading gateway.log");
    await expect(page.getByTestId("typing")).toBeVisible();
    await page.mouse.move(700, 400);
    await page.waitForTimeout(400);
    // hold every animation at a mid frame (ring part-way round, dots mid-hop) instead of turning them off
    await page.evaluate(() => {
      for (const a of document.getAnimations()) {
        const name = (a as CSSAnimation).animationName ?? "";
        a.pause();
        // keep each ring's own phase (its negative delay), so the shot shows them at different angles
        if (name === "ui-ring-turn") a.currentTime = 1600 - Number(a.effect?.getTiming().delay ?? 0);
        else if (name === "ui-typing-hop") a.currentTime = 300;
        else if (name === "pulse") a.currentTime = 500;
      }
    });
    await page.screenshot({ path: join(SHOTS, `T12b-live-${theme}.png`) });
    await page.evaluate(() => document.getAnimations().forEach((a) => a.play()));
    await emit(ev("kami", "turn.end", { outcome: "done" }), ev("friren", "turn.end", { outcome: "done" }));
  });
}
});
