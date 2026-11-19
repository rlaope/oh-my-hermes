// Steer queue in a bot's main chat: a message typed while the bot answers waits in omher as a bubble with a ↵ mark;
// the mark's menu sends it now (one interrupt, then this one first), steers it into the running answer (chat.steer,
// a refused steer is sent normally after), edits or deletes it; untouched, it goes out after the turn, in order.
// Shots (dark/light, en/ko, 900x600): OMHER_SHOTS=<dir>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  // the mock also broadcasts events to this socket: wait for the reply to this request
  const out = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out.result;
}
const calls = async (op: string) => ((await mock("mock.calls")).calls as { op: string; params: any }[]).filter((c) => c.op === op);
const sent = async () => (await calls("chat.send")).map((c) => c.params.text as string);

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.manual", { bot: "kami" });
});

/** kami's chat with a turn running (the mock runs no script: the test ends it). */
async function running(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await say(page, "Refactor the gateway retry code");
  await expect(page.getByTestId("stop")).toBeVisible();
}
async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}
const held = (page: Page, text: string) => page.locator("[data-testid=bubble-user][data-held]", { hasText: text });
const endTurn = (outcome = "done") => mock("mock.endTurn", { bot: "kami", outcome });

test("a message sent while the bot answers waits with a ↵ mark and a Waiting line; nothing goes to Hermes", async ({ page }) => {
  await running(page);
  await say(page, "and add a test for it");
  const b = held(page, "and add a test for it");
  await expect(b).toBeVisible();
  await expect(b.getByTestId("queue-mark")).toBeVisible();
  await expect(b.getByTestId("queue-mark")).toHaveText("↵");
  await expect(b.getByTestId("bubble-held")).toHaveText("Waiting");
  // the mark sits before the bubble, on its line
  const mark = (await b.getByTestId("queue-mark").boundingBox())!;
  const bub = (await b.locator(".b").boundingBox())!;
  expect(mark.x + mark.width).toBeLessThanOrEqual(bub.x);
  expect(await sent()).toEqual(["Refactor the gateway retry code"]);
  // no menu: ↵ (Steer here), ↓ (back to the box) and × (drop, shown on hover) sit before the bubble
  await expect(b.getByTestId("queue-acts").getByRole("button")).toHaveText(["×", "↵", "↓"]);
  // ↓ sits right beside the bubble, whether or not × shows
  const down = (await b.getByTestId("queue-edit").boundingBox())!;
  expect(Math.abs((await b.locator(".b").boundingBox())!.x - (down.x + down.width) - 6)).toBeLessThanOrEqual(1);
  await expect(b.getByTestId("queue-mark")).toHaveAttribute("aria-label", "Steer");
  await expect(b.getByTestId("queue-edit")).toHaveAttribute("aria-label", "Edit");
  await expect(page.getByTestId("queue-menu")).toHaveCount(0);
  await page.mouse.move(0, 0);
  await expect(b.getByTestId("queue-delete")).toHaveCSS("opacity", "0");
  await b.hover();
  await expect(b.getByTestId("queue-delete")).toHaveCSS("opacity", "1");
  // a waiting bubble is muted
  expect(Number(await b.locator(".b").evaluate((el) => getComputedStyle(el).opacity))).toBeLessThan(1);
});

test("auto-send: untouched messages go out after the turn ends, one per turn, in order", async ({ page }) => {
  await running(page);
  await say(page, "first after");
  await say(page, "second after");
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(2);
  await endTurn();
  await expect.poll(sent).toEqual(["Refactor the gateway retry code", "first after"]);
  await expect(held(page, "first after")).toHaveCount(0);
  await expect(held(page, "second after")).toBeVisible();
  await page.waitForTimeout(300);
  expect(await sent()).toHaveLength(2); // the second waits for the first's turn
  await endTurn();
  await expect.poll(sent).toEqual(["Refactor the gateway retry code", "first after", "second after"]);
  await expect(page.locator("[data-testid=bubble-user][data-held]")).toHaveCount(0);
});

test("↵ steers in one click: one chat.steer, a Steered line, never sent again, no interrupt", async ({ page }) => {
  await running(page);
  await say(page, "also keep the old timeout");
  const b = held(page, "also keep the old timeout");
  await b.getByTestId("queue-mark").click();
  const row = page.locator("[data-testid=bubble-user][data-steered]", { hasText: "also keep the old timeout" });
  // Hermes queued it: the bot has it, read right away (messenger style), with the time
  await expect(row.getByTestId("bubble-read")).toHaveText(/^Read · \d\d:\d\d$/);
  await expect(row.getByTestId("bubble-steered")).toHaveCount(0);
  await expect(row.getByTestId("queue-mark")).toHaveCount(0);
  const steer = await calls("chat.steer");
  expect(steer.map((c) => c.params)).toEqual([{ bot: "kami", text: "also keep the old timeout" }]);
  expect((await mock("mock.steers")).steers).toEqual([{ bot: "kami", text: "also keep the old timeout" }]);
  await endTurn();
  await page.waitForTimeout(400);
  expect(await sent()).toEqual(["Refactor the gateway retry code"]);
  expect((await calls("chat.interrupt")).length).toBe(0);
});

test("Steer refused: the message stays waiting and is sent normally after the turn", async ({ page }) => {
  await mock("mock.steerMode", { bot: "kami", mode: "reject" });
  await running(page);
  await say(page, "a");
  await say(page, "b goes first");
  await held(page, "b goes first").getByTestId("queue-mark").click();
  await expect.poll(async () => (await calls("chat.steer")).length).toBe(1);
  await expect(held(page, "b goes first")).toBeVisible();
  await expect(page.getByTestId("bubble-steered")).toHaveCount(0);
  // refused: the bot does not have it, so no read mark on it
  await expect(held(page, "b goes first").getByTestId("bubble-read")).toHaveCount(0);
  await endTurn();
  await expect.poll(sent).toEqual(["Refactor the gateway retry code", "b goes first"]);
  await endTurn();
  await expect.poll(sent).toEqual(["Refactor the gateway retry code", "b goes first", "a"]);
});

test("↓ puts the text back in the box; × drops it; neither is sent", async ({ page }) => {
  await running(page);
  await say(page, "fix teh typo");
  await say(page, "never mind this");
  await held(page, "fix teh typo").getByTestId("queue-edit").click();
  await expect(page.getByTestId("composer")).toHaveValue("fix teh typo");
  await expect(page.getByTestId("composer")).toBeFocused();
  await expect(held(page, "fix teh typo")).toHaveCount(0);
  await held(page, "never mind this").hover();
  await held(page, "never mind this").getByTestId("queue-delete").click();
  await expect(page.getByTestId("bubble-user").filter({ hasText: "never mind this" })).toHaveCount(0);
  await page.getByTestId("composer").fill("");
  await endTurn();
  await page.waitForTimeout(400);
  expect(await sent()).toEqual(["Refactor the gateway retry code"]);
});

test("Stop keeps the waiting messages; they go out after the stopped turn", async ({ page }) => {
  await running(page);
  await say(page, "still wanted");
  await page.getByTestId("composer").fill("");
  await page.getByTestId("stop").click();
  await expect.poll(sent).toEqual(["Refactor the gateway retry code", "still wanted"]);
  expect((await calls("chat.interrupt")).length).toBe(1);
});

test("keyboard: ↵, ↓ and × are buttons in tab order; Enter on × drops it without touching the answer", async ({ page }) => {
  await running(page);
  await say(page, "keyboard one");
  const b = held(page, "keyboard one");
  const mark = b.getByTestId("queue-mark");
  await expect(mark).not.toHaveAttribute("aria-haspopup", /.+/);
  await mark.focus();
  await page.keyboard.press("Tab");
  await expect(b.getByTestId("queue-edit")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  const x = b.getByTestId("queue-delete");
  await expect(x).toBeFocused();
  await expect(x).toHaveCSS("opacity", "1"); // focus shows it, as hover does
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-user").filter({ hasText: "keyboard one" })).toHaveCount(0);
  expect((await calls("chat.interrupt")).length).toBe(0);
  expect((await calls("chat.steer")).length).toBe(0);
});

test("read receipt: the last message the bot has says Read; a held one does not until it goes out", async ({ page }) => {
  await running(page);
  const first = page.locator("[data-testid=bubble-user]", { hasText: "Refactor the gateway retry code" });
  await expect(first.getByTestId("bubble-read")).toHaveText(/^Read · \d\d:\d\d$/);
  // only the last message the bot has carries it: earlier ones do not
  await expect(page.locator("[data-testid=bubble-user]:not([data-steered]) [data-testid=bubble-read]")).toHaveCount(1);
  await say(page, "then write the notes");
  await expect(held(page, "then write the notes").getByTestId("bubble-read")).toHaveCount(0);
  await expect(first.getByTestId("bubble-read")).toBeVisible();
  await endTurn();
  const sentLater = page.locator("[data-testid=bubble-user]", { hasText: "then write the notes" });
  await expect(sentLater.getByTestId("bubble-read")).toBeVisible();
  await expect(first.getByTestId("bubble-read")).toHaveCount(0);
});

test("steer reply: the bot's first words after it took the steer show under it, one line, the rest stays hidden", async ({ page }) => {
  await running(page);
  await say(page, "keep the old timeout");
  await held(page, "keep the old timeout").getByTestId("queue-mark").click();
  const row = page.locator("[data-testid=bubble-user][data-steered]", { hasText: "keep the old timeout" });
  await expect(row.getByTestId("bubble-read")).toBeVisible();
  await expect(row.getByTestId("bubble-steer-reply")).toHaveCount(0);
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", ...extra });
  await mock("mock.emit", { events: [
    ev("tool.start", { tool_id: "sr1", name: "terminal", detail: "ls" }),
    ev("tool.end", { tool_id: "sr1", name: "terminal", ok: true }),
    ev("delta", { text: "Got it, keeping the old timeout as it is.\nRe-running the tests now." }),
    ev("tool.start", { tool_id: "sr2", name: "terminal", detail: "pnpm test" }),
  ] });
  await expect(row.getByTestId("bubble-steer-reply")).toHaveText("↳Got it, keeping the old timeout as it is.");
  await expect(page.getByText("Re-running the tests now.")).toHaveCount(0);
  // one line under the bubble, inside its width
  const [r, b] = await Promise.all([row.getByTestId("bubble-steer-reply").boundingBox(), row.locator(".b").boundingBox()]);
  expect(r!.height).toBeLessThan(20);
  expect(r!.x + r!.width).toBeLessThanOrEqual(b!.x + b!.width + 1);
});

test("live line: a long command is cut to a glance with the full text on hover, and the line stays short", async ({ page }) => {
  await running(page);
  const long = "cd /Users/you/work/api-server && pnpm -s exec vitest run src/state/store.test.ts --reporter verbose";
  await mock("mock.emit", { events: [{ event: "tool.start", bot: "kami", tool_id: "ll1", name: "terminal", detail: long }] });
  const line = page.locator("[data-testid=activity][data-state=live]");
  const text = line.getByTestId("activity-text");
  await expect(text).toContainText("cd /Users/you/work");
  expect(((await text.textContent()) ?? "").length).toBeLessThanOrEqual("Running ".length + 48);
  await expect(line.locator(".act-live")).toHaveAttribute("title", `Running ${long}`);
  const [h, tl] = await Promise.all([line.getByTestId("activity-toggle").boundingBox(), page.getByTestId("timeline").boundingBox()]);
  expect(h!.width).toBeLessThanOrEqual(Math.min(0.6 * tl!.width, 520) + 1);
  // the typing dots wait directly under it, with no ringed face of their own
  await expect(page.getByTestId("typing")).toBeVisible();
  await expect(page.getByTestId("typing-ring")).toHaveCount(0);
});

test("shots: a waiting bubble and its menu, dark/light, en/ko, 900x600", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS not set");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 900, height: 600 });
  for (const lang of ["en", "ko"] as const) {
    for (const theme of ["dark", "light"] as const) {
      await mock("mock.reset");
      await mock("mock.manual", { bot: "kami" });
      await page.addInitScript(([t, l]) => {
        localStorage.setItem("omher.theme", t);
        localStorage.setItem("omher.lang", l);
      }, [theme, lang]);
      await running(page);
      const steer = lang === "ko" ? "기존 타임아웃 값은 그대로 둬" : "keep the old timeout as it is";
      await say(page, steer);
      await held(page, steer).getByTestId("queue-mark").click();
      await expect(page.getByTestId("bubble-read")).toBeVisible();
      await say(page, lang === "ko" ? "끝나면 테스트도 돌려줘" : "run the tests when you are done");
      await say(page, lang === "ko" ? "그리고 PR 설명도 써줘" : "and write the PR description");
      // the last waiting message hovered: its three buttons, none over a bubble of the person's
      const last = page.locator("[data-testid=bubble-user][data-held]").last();
      await last.hover();
      await expect(last.getByTestId("queue-delete")).toHaveCSS("opacity", "1");
      const acts = (await last.getByTestId("queue-acts").boundingBox())!;
      for (const box of await page.locator("[data-testid=bubble-user] .b").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON())))
        expect(acts.x + acts.width <= box.x || acts.y + acts.height <= box.y || box.y + box.height <= acts.y, JSON.stringify({ acts, box })).toBe(true);
      // contrast of a waiting bubble's text and of its Waiting line, as drawn (opacity included)
      console.log(lang, theme, JSON.stringify(await page.evaluate(() => {
        const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).map(Number);
        const lum = ([r, g, b]: number[]) => {
          const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
          return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
        };
        const mix = (fg: number[], bg: number[], a: number) => fg.slice(0, 3).map((v, i) => v * a + bg[i] * (1 - a));
        const ratio = (x: number[], y: number[]) => { const [l1, l2] = [lum(x), lum(y)].sort((p, q) => q - p); return +((l1 + 0.05) / (l2 + 0.05)).toFixed(2); };
        const page = rgb(getComputedStyle(document.querySelector(".thread")!).backgroundColor);
        const bg0 = page.length >= 3 && (page[3] ?? 1) > 0 ? page : rgb(getComputedStyle(document.body).backgroundColor);
        const b = document.querySelector("[data-held] .b") as HTMLElement;
        const cs = getComputedStyle(b);
        const op = Number(cs.opacity);
        const bub = rgb(cs.backgroundColor);
        const bubOn = mix(bub, bg0, (bub[3] ?? 1));
        const drawnBg = mix(bubOn, bg0, op);
        const drawnFg = mix(mix(rgb(cs.color), bubOn, 1), bg0, op);
        const w = getComputedStyle(document.querySelector("[data-testid=bubble-held]")!);
        return { text: ratio(drawnFg, drawnBg), waiting: ratio(rgb(w.color), bg0) };
      })));
      await page.screenshot({ path: join(SHOTS, `steer-queue-${lang}-${theme}.png`), animations: "disabled" });
    }
  }
});

// Shots for the read receipt, the steer reply and the live line with the dots under it (ko, dark/light, 1280x820,
// Retina): STEER_ACK_SHOTS=<dir>.
test.describe("steer ack shots", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const theme of ["dark", "light"] as const) {
    test(`shot steer-ack-ko-${theme}`, async ({ page }) => {
      const dir = process.env.STEER_ACK_SHOTS || "";
      test.skip(!dir, "STEER_ACK_SHOTS not set");
      mkdirSync(dir, { recursive: true });
      await page.setViewportSize({ width: 1280, height: 820 });
      await page.addInitScript(([t]) => {
        localStorage.setItem("omher.theme", t);
        localStorage.setItem("omher.lang", "ko");
      }, [theme]);
      await page.goto("/");
      await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
      await expect(page.getByTestId("bubble-user").first()).toBeVisible();
      await say(page, "게이트웨이 재시도 코드 리팩터링해줘");
      await expect(page.getByTestId("stop")).toBeVisible();
      await say(page, "기존 타임아웃 값은 그대로 둬");
      await held(page, "기존 타임아웃 값은 그대로 둬").getByTestId("queue-mark").click();
      const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", ...extra });
      await mock("mock.emit", { events: [
        ev("tool.start", { tool_id: "sh1", name: "read_file", detail: "gateway/retry.py" }),
        ev("tool.end", { tool_id: "sh1", name: "read_file", ok: true }),
        ev("delta", { text: "알겠어요, 타임아웃 값은 그대로 두고 재시도 횟수만 정리할게요.\n" }),
        ev("tool.start", { tool_id: "sh2", name: "terminal", detail: "cd /Users/you/work/api-server && pnpm -s exec vitest run src/gateway/retry.test.ts --reporter verbose" }),
      ] });
      const row = page.locator("[data-testid=bubble-user][data-steered]");
      await expect(row.getByTestId("bubble-steer-reply")).toBeVisible();
      await expect(page.getByTestId("typing")).toBeVisible();
      await page.mouse.move(700, 120);
      await page.waitForTimeout(400);
      await page.evaluate(() => {
        for (const a of document.getAnimations()) {
          const name = (a as CSSAnimation).animationName ?? "";
          a.pause();
          if (name === "ui-typing-hop") a.currentTime = 300;
        }
      });
      await page.screenshot({ path: join(dir, `steer-ack-ko-${theme}.png`) });
    });
  }
});
