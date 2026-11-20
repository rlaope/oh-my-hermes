// The ways to start a thread besides the row menu (owner, 2026-11-18), against the mock bridge:
// 1. `./` in a bot's composer lists `./thread` first (a skill named thread is `$thread`, never this row); `./thread`
//    alone opens a new empty thread with its composer focused; `./thread <text>` opens one and sends <text> as its
//    first message (chat.send session=<new thread>), never to the main chat; mid-message it goes out as typed;
//    inside a thread it opens a sibling thread under the same bot;
// 2. "+ New thread" closes each bot's thread list on the rail; under a bot with no threads it shows while the bot is
//    open; a "+" shows on the row's hover; an offline bot has neither;
// 3. the row menu puts New thread in its own group (icon, divider), the management items below in their old order.
// Shots: OMHER_SHOTS=<dir> -> thread-entry-{sidebar,picker,menu}-{dark,light}.png (ko)
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
type Call = { op: string; params: Record<string, any> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);

async function setup(page: Page, opts: { theme?: "dark" | "light"; lang?: string } = {}) {
  await page.addInitScript(([t, l]) => {
    localStorage.setItem("omher.theme", t);
    if (l) localStorage.setItem("omher.lang", l);
  }, [opts.theme ?? "dark", opts.lang ?? ""] as const);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** The thread the app opened last (the one thread.create made). */
async function created(page: Page) {
  await expect.poll(async () => (await calls("thread.create")).length).toBeGreaterThan(0);
  const chat = page.getByTestId("thread-chat");
  await expect(chat).toBeVisible();
  return (await chat.getAttribute("data-thread"))!;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("./ lists ./thread first; ./thread alone opens an empty thread with the composer focused", async ({ page }) => {
  await setup(page);
  const box = page.getByTestId("composer");
  await box.click();
  await page.keyboard.type("./");
  const pick = page.getByTestId("thread-picker");
  await expect(pick).toBeVisible();
  await expect(pick.getByTestId("thread-option")).toHaveCount(1);
  await expect(pick.getByTestId("thread-option").first()).toContainText("./thread");
  await expect(pick.getByTestId("thread-option").first()).toContainText("New thread with Kami");
  // the skills are `$name`: no skill row here (a skill named thread is `$thread`)
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await page.keyboard.type("th");
  await page.keyboard.press("Enter"); // picks: the box reads `./thread `
  await expect(box).toHaveValue("./thread ");
  await expect(page.getByTestId("thread-picker")).toHaveCount(0);
  await page.keyboard.press("Enter");
  const id = await created(page);
  expect((await calls("thread.create"))[0].params.bot).toBe("kami");
  await expect(page.getByTestId("thread-empty")).toBeVisible();
  await expect(page.getByTestId(`thread-row-${id}`)).toBeVisible();
  // nothing was sent anywhere, and the thread's composer has the focus
  expect(await calls("chat.send")).toEqual([]);
  await expect(page.getByTestId("composer")).toBeFocused();
  await expect(page.getByTestId("composer")).toHaveValue("");
});

test("./thread <text> opens a thread and sends <text> there as its first message, not to the main chat", async ({ page }) => {
  await setup(page);
  await page.getByTestId("composer").click();
  await page.keyboard.type("./thread OG 대시보드 502 원인 찾기");
  // the token is drawn as a pill in the mirror
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveText("./thread");
  await page.keyboard.press("Enter");
  const id = await created(page);
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params)).toEqual([{ bot: "kami", session: id, text: "OG 대시보드 502 원인 찾기" }]);
  await expect(page.getByTestId("thread-title")).toHaveText("OG 대시보드 502 원인 찾기");
  // the main chat got nothing: no bubble with the command or the text
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("thread-chat")).toHaveCount(0);
  await expect(page.locator(".pane").getByText("OG 대시보드 502 원인 찾기")).toHaveCount(0);
  expect((await mock("mock.submits")).submits.filter((s: { session?: string }) => !s.session)).toEqual([]);
});

test("./thread mid-message, ./threads and a path go out as typed", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-friren").click(); // a bot with no turn running, so the send goes out at once
  await page.getByTestId("composer").click();
  await page.keyboard.type("run ./thread later");
  await expect(page.getByTestId("thread-picker")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params.text)).toEqual(["run ./thread later"]);
  expect(await calls("thread.create")).toEqual([]);
  // `./b` is a path: no picker
  await page.getByTestId("composer").fill("./b");
  await expect(page.getByTestId("thread-picker")).toHaveCount(0);
});

test("inside a thread, ./thread opens a sibling thread under the same bot", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-kami").click({ button: "right" });
  await page.getByTestId("row-new-thread").click();
  const first = await created(page);
  await page.keyboard.type("./thread 두 번째 일");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await calls("thread.create")).length).toBe(2);
  const chat = page.getByTestId("thread-chat");
  await expect(chat).not.toHaveAttribute("data-thread", first);
  const second = (await chat.getAttribute("data-thread"))!;
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params)).toEqual([{ bot: "kami", session: second, text: "두 번째 일" }]);
  await expect(page.getByTestId("threads-kami").locator("[data-thread]")).toHaveCount(2);
});

test("no New thread line under a bot: the tree holds only its threads; the row's + is the way in", async ({ page }) => {
  await setup(page);
  // khope (2026-11-19): a "+ New thread" line always under the bot is too much. Kami is open with no threads: nothing
  await expect(page.getByTestId("threads-kami")).toHaveCount(0);
  await expect(page.getByTestId("thread-new")).toHaveCount(0);
  await page.getByTestId("bot-row-kami").hover();
  await page.getByTestId("bot-new-kami").click();
  const id = await created(page);
  await expect(page.getByTestId("thread-empty")).toBeVisible();
  await expect(page.getByTestId("composer")).toBeFocused();
  // the tree is the thread card alone, the last row on the rail
  const rows = page.getByTestId("threads-kami").locator(":scope > li");
  await expect(rows).toHaveCount(1);
  await expect(rows.nth(0)).toHaveAttribute("data-thread", id);
  await expect(rows.nth(0)).toHaveClass(/th-last/);
  await expect(page.getByTestId("thread-new")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
});

test("the row's + opens a new thread; an offline bot has no + and no New thread in its menu", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-row-friren").hover();
  const plus = page.getByTestId("bot-new-friren");
  await expect(plus).toBeVisible();
  // the + sits left of ⋯ and the time gives way: nothing overlaps
  const p = (await plus.boundingBox())!;
  const more = (await page.getByTestId("bot-more-friren").boundingBox())!;
  expect(p.x + p.width).toBeLessThanOrEqual(more.x);
  const name = (await page.getByTestId("bot-row-friren").locator(".bot-n").boundingBox())!;
  expect(name.x + name.width).toBeLessThanOrEqual(p.x);
  await plus.click();
  await created(page);
  expect((await calls("thread.create"))[0].params.bot).toBe("friren");
  await expect(page.getByTestId("composer")).toBeFocused();

  await mock("mock.botStatus", { bot: "omh-tui", status: "offline" });
  await page.getByTestId("bot-omh-tui").click();
  await page.getByTestId("bot-row-omh-tui").hover();
  await expect(page.getByTestId("bot-new-omh-tui")).toHaveCount(0);
  await page.getByTestId("bot-omh-tui").click({ button: "right" });
  await expect(page.getByTestId("row-new-thread")).toHaveCount(0);
  await expect(page.getByTestId("row-menu-sep")).toHaveCount(0);
});

test("the row menu sets New thread apart: its own group with an icon and a divider, then the management items", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-kami").click({ button: "right" });
  const menu = page.getByTestId("row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["New thread · Kami", "Pin to top", "Edit bot", /^Restart/, "Remove from list"]);
  const nt = menu.getByTestId("row-new-thread");
  await expect(nt.locator("svg.nt-ic")).toHaveCount(1);
  const sep = menu.getByTestId("row-menu-sep");
  await expect(sep).toHaveAttribute("role", "separator");
  const a = (await nt.boundingBox())!;
  const s = (await sep.boundingBox())!;
  const pin = (await menu.getByRole("menuitem", { name: "Pin to top" }).boundingBox())!;
  expect(s.y).toBeGreaterThanOrEqual(a.y + a.height);
  expect(pin.y).toBeGreaterThanOrEqual(s.y + s.height);
  // no fill on the item at rest (the owner: no colour, no badge)
  expect(await nt.evaluate((el) => getComputedStyle(el).backgroundColor)).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  // the keys still walk every item, and the divider is not one of them
  await expect(nt).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: "Pin to top" })).toBeFocused();
  // the menu stays inside the window
  const box = (await menu.boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(900);
});

test("shots: sidebar with threads (no New thread line), the ./th picker, the row menu (ko, dark and light)", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS not set");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await mock("mock.threads", {
    bot: "kami",
    threads: [
      { title: "릴리스 노트 초안 정리", ago: 4 * 3600, messages: [["user", "릴리스 노트 초안 정리해줘"], ["assistant", "초안을 docs/RELEASE.md에 올렸어요."]] },
      { title: "Nightly 빌드 실패 원인", ago: 3 * 3600 },
      { title: "OG 대시보드 502 원인 찾기", ago: 60 },
    ],
  });
  for (const theme of ["dark", "light"] as const) {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
    await page.goto("/");
    await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
    await expect(page.getByTestId("threads-kami").locator("[data-thread]")).toHaveCount(3);
    await expect(page.getByTestId("thread-new")).toHaveCount(0);
    const box = page.getByTestId("composer");
    await box.fill("");
    await page.getByTestId("bot-row-friren").hover();
    await page.waitForTimeout(250);
    await page.screenshot({ path: join(SHOTS, `thread-entry-sidebar-${theme}.png`), animations: "disabled", caret: "initial" });
    await box.click();
    await page.keyboard.type("./th");
    await expect(page.getByTestId("thread-picker")).toBeVisible();
    await page.screenshot({ path: join(SHOTS, `thread-entry-picker-${theme}.png`), animations: "disabled", caret: "initial" });
    await box.fill("");
    await page.getByTestId("bot-kami").click({ button: "right" });
    await expect(page.getByTestId("row-menu")).toBeVisible();
    await page.mouse.move(1200, 500);
    await page.screenshot({ path: join(SHOTS, `thread-entry-menu-${theme}.png`), animations: "disabled", caret: "initial" });
    await page.keyboard.press("Escape");
  }
});
