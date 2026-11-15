// Threads under a bot (src/threads, bridge thread.*), against the mock bridge:
// 1. right-click Kami -> "New thread · Kami" (first item) -> a row under Kami, the thread's chat with the composer
//    focused -> send -> the message lands on that thread id (chat.send session=<thread>), and the row takes its title;
// 2. the rows read as a tree: the bot list is role=tree, each bot row a treeitem aria-level=1, its threads a
//    role=group inside it with treeitems aria-level=2 joined by a thin connector (two levels only);
// 3. the five states come from events (data-state): running, needs_you, done, failed, idle;
// 4. reduced motion: no glyph animates (getAnimations().length === 0);
// 5. x -> confirm -> the row goes (thread.remove); Cancel keeps it and sends nothing.
// Shots (taken first): OMHER_SHOTS=<dir> -> threads-{menu,states-dark,states-light,confirm}.png
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

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(SHOTS, `threads-${name}.png`), caret: "initial" });
}

async function setup(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** Kami with four threads, one per live state the events below put them in (plus a fifth that stays idle). */
const SEED = [
  { title: "릴리스 노트 초안 정리", ago: 4 * 3600, messages: [["user", "릴리스 노트 초안 정리해줘"], ["assistant", "초안을 docs/RELEASE.md에 올렸어요."]] },
  { title: "Nightly 빌드 실패 원인", ago: 3 * 3600 },
  { title: "Slack 알림 문구 다듬기", ago: 2 * 3600 },
  { title: "Docs dark mode 대비 점검", ago: 3600 },
  { title: "OG 대시보드 502 원인 찾기", ago: 60 },
];

async function seed(page: Page) {
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: SEED });
  // reload so the app reads thread.list fresh
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const ids = threads as string[];
  const [notes, nightly, slack, docs, og] = ids;
  // running: a turn starts on the 502 thread; needs you: the docs thread asks; done / failed: turns ended
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami", session: og },
      { event: "tool.start", bot: "kami", session: og, tool_id: "t1", name: "terminal", detail: "rg 502 gateway.log" },
      { event: "turn.start", bot: "kami", session: docs },
      { event: "approval.request", bot: "kami", session: docs, request_id: "ap-docs", title: "Run shell command", command: "pnpm build:docs", choices: ["once", "deny"] },
      { event: "turn.start", bot: "kami", session: slack },
      { event: "message", bot: "kami", session: slack, id: "m-slack", text: "알림 문구를 세 가지로 다듬었어요." },
      { event: "turn.end", bot: "kami", session: slack, outcome: "done" },
      { event: "turn.start", bot: "kami", session: nightly },
      { event: "turn.end", bot: "kami", session: nightly, outcome: "error", error: "gateway timeout" },
    ],
  });
  return { notes, nightly, slack, docs, og };
}

test.beforeEach(async () => {
  await mock("mock.reset");
});
test.afterEach(async () => {
  await mock("mock.manual", { bot: "kami", on: false });
});

test.describe("shots", () => {
  // 2x, so the 1px connector and its rounded elbows read in the pictures as on a Retina screen
  test.use({ deviceScaleFactor: 2 });
  test("shots: menu, states dark and light, confirm (with the tree lines)", async ({ page }) => {
    await setup(page, "dark");
    const ids = await seed(page);
    await expect(page.getByTestId(`thread-row-${ids.og}`)).toHaveAttribute("data-state", "running");
    await page.getByTestId("bot-kami").click({ button: "right" });
    await expect(page.getByTestId("row-menu")).toBeVisible();
    await shot(page, "menu");
    await page.keyboard.press("Escape");
    await page.mouse.move(900, 600);
    await shot(page, "states-dark");
    await page.getByTestId(`thread-row-${ids.og}`).hover();
    await page.getByTestId(`thread-row-${ids.og}`).getByTestId("thread-x").click();
    await expect(page.getByTestId("thread-confirm")).toBeVisible();
    await shot(page, "confirm");
    await page.getByTestId("thread-cancel").click();
    await page.evaluate(() => localStorage.setItem("omher.theme", "light"));
    await setup(page, "light");
    // the reloaded app has read its threads before the events come
    await expect(page.getByTestId(`thread-row-${ids.nightly}`)).toBeVisible();
    await mock("mock.emit", {
      events: [
        { event: "turn.start", bot: "kami", session: ids.og },
        { event: "turn.start", bot: "kami", session: ids.docs },
        { event: "approval.request", bot: "kami", session: ids.docs, request_id: "ap-docs2", title: "Run shell command", command: "pnpm build:docs", choices: ["once", "deny"] },
        { event: "turn.start", bot: "kami", session: ids.slack },
        { event: "turn.end", bot: "kami", session: ids.slack, outcome: "done" },
        { event: "turn.start", bot: "kami", session: ids.nightly },
        { event: "turn.end", bot: "kami", session: ids.nightly, outcome: "interrupted" },
      ],
    });
    await expect(page.getByTestId(`thread-row-${ids.nightly}`)).toHaveAttribute("data-state", "failed");
    await page.mouse.move(900, 600);
    await shot(page, "states-light");
  });
});

test("New thread · Kami opens an empty thread under Kami; a send lands on that thread id", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-kami").click({ button: "right" });
  const menu = page.getByTestId("row-menu");
  await expect(menu.getByRole("menuitem").first()).toHaveText("New thread · Kami");
  await menu.getByTestId("row-new-thread").click();
  const [created] = await calls("thread.create");
  expect(created.params.bot).toBe("kami");
  const tree = page.getByTestId("threads-kami");
  const row = tree.getByRole("treeitem");
  await expect(row).toHaveCount(1);
  const id = await row.getAttribute("data-thread");
  expect(id).toBeTruthy();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", id!);
  await expect(page.getByTestId("thread-empty")).toBeVisible();
  // the composer is focused: typing goes straight in
  await page.keyboard.type("OG 대시보드 502 원인 찾기");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await calls("chat.send")).map((c) => c.params)).toEqual([{ bot: "kami", session: id, text: "OG 대시보드 502 원인 찾기" }]);
  await expect(row.locator(".th-title")).toHaveText("OG 대시보드 502 원인 찾기");
  await expect(page.getByTestId("thread-title")).toHaveText("OG 대시보드 502 원인 찾기");
  // the main chat is one click on the bot away, and the thread one click back
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("thread-chat")).toHaveCount(0);
  await row.getByTestId("thread-open").click();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", id!);
});

test("thread rows are a two-level tree under their bot, joined by a thin connector", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  await expect(page.locator(".bot-list")).toHaveAttribute("role", "tree");
  const bot = page.getByTestId("bot-row-kami");
  await expect(bot).toHaveAttribute("role", "treeitem");
  await expect(bot).toHaveAttribute("aria-level", "1");
  for (const b of ["friren", "default", "omh-tui"]) await expect(page.getByTestId(`bot-row-${b}`)).toHaveAttribute("aria-level", "1");
  // every thread row is a child of Kami's own tree group: nested in the DOM, aria-level 2
  const group = bot.locator(":scope > [role=group]");
  await expect(group).toHaveCount(1);
  await expect(bot).toHaveAttribute("aria-expanded", "true");
  const rows = group.locator(":scope > [role=treeitem]");
  await expect(rows).toHaveCount(5);
  for (const r of await rows.all()) await expect(r).toHaveAttribute("aria-level", "2");
  // two levels only: nothing nests under a thread
  await expect(group.locator("[role=treeitem] [role=group], [role=treeitem] [role=treeitem]")).toHaveCount(0);
  // newest first
  await expect(rows.first()).toHaveAttribute("data-thread", ids.og);
  // the connector: a 1px line in the thin-line gray, an elbow into every row, the stem carried past every row but the last
  const lines = await rows.evaluateAll((els) =>
    els.map((el) => {
      const b = getComputedStyle(el.querySelector(".th-branch")!);
      const stem = getComputedStyle(el, "::before");
      return { left: b.borderLeftWidth, bottom: b.borderBottomWidth, radius: b.borderBottomLeftRadius, color: b.borderLeftColor, stem: stem.content !== "none" && stem.borderLeftWidth === "1px", last: el.classList.contains("th-last") };
    }),
  );
  for (const l of lines) {
    expect(l.left).toBe("1px");
    expect(l.bottom).toBe("1px");
    expect(parseFloat(l.radius)).toBeGreaterThan(0);
  }
  expect(lines.map((l) => l.stem)).toEqual([true, true, true, true, false]);
  expect(lines.map((l) => l.last)).toEqual([false, false, false, false, true]);
  const lineGray = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.color = "var(--line-strong)";
    document.querySelector(".side")!.appendChild(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  });
  expect(new Set(lines.map((l) => l.color))).toEqual(new Set([lineGray]));
  // the branch starts under the bot's avatar column
  const av = (await bot.locator("button.bot .ui-av").first().boundingBox())!;
  const branch = (await rows.first().locator(".th-branch").boundingBox())!;
  expect(Math.abs(branch.x - (av.x + av.width / 2))).toBeLessThanOrEqual(2);
});

test("more than five threads fold under Show N more, on the same tree line", async ({ page }) => {
  await setup(page);
  await mock("mock.threads", { bot: "kami", threads: Array.from({ length: 7 }, (_, i) => ({ title: `Thread ${i + 1}`, ago: (7 - i) * 60 })) });
  await page.reload();
  const group = page.getByTestId("threads-kami");
  await expect(group.locator(":scope > [role=treeitem]")).toHaveCount(5);
  const more = page.getByTestId("thread-more");
  await expect(more).toHaveText("Show 2 more");
  const moreRow = group.locator(":scope > li.th-more");
  await expect(moreRow).toHaveClass(/th-last/);
  await expect(moreRow.locator(".th-branch")).toHaveCount(1);
  await more.click();
  await expect(group.locator(":scope > [role=treeitem]")).toHaveCount(7);
});

test("five states from events, exposed as data-state", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  const st = (id: string) => page.getByTestId(`thread-row-${id}`);
  await expect(st(ids.og)).toHaveAttribute("data-state", "running");
  await expect(st(ids.docs)).toHaveAttribute("data-state", "needs_you");
  await expect(st(ids.slack)).toHaveAttribute("data-state", "done");
  await expect(st(ids.nightly)).toHaveAttribute("data-state", "failed");
  await expect(st(ids.notes)).toHaveAttribute("data-state", "idle");
  // needs you shows in the Needs-you strip too, and names the thread
  await expect(page.getByTestId("needs-strip")).toBeVisible();
  // a stop by the person reads as failed; a new turn after it reads as running
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", session: ids.og, outcome: "interrupted" }] });
  await expect(st(ids.og)).toHaveAttribute("data-state", "failed");
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami", session: ids.og }] });
  await expect(st(ids.og)).toHaveAttribute("data-state", "running");
  // the running spinner and the needs-you pulse animate; done pops once
  const animating = await page.locator('[data-testid="thread-glyph"][data-state="running"] svg, [data-testid="thread-glyph"][data-state="needs_you"] .th-dot').evaluateAll((els) => els.map((e) => e.getAnimations().length));
  expect(animating.every((n) => n > 0)).toBe(true);
});

test("reduced motion: no glyph animates", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await setup(page);
  const ids = await seed(page);
  await expect(page.getByTestId(`thread-row-${ids.og}`)).toHaveAttribute("data-state", "running");
  await expect(page.getByTestId(`thread-row-${ids.docs}`)).toHaveAttribute("data-state", "needs_you");
  const counts = await page.getByTestId("thread-glyph").evaluateAll((els) => els.flatMap((e) => [e, ...e.querySelectorAll("*")]).map((e) => e.getAnimations().length));
  expect(counts.length).toBeGreaterThan(0);
  expect(counts.every((n) => n === 0)).toBe(true);
});

test("x -> confirm removes the row (stop + archive); Cancel keeps it and sends nothing", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  const row = page.getByTestId(`thread-row-${ids.slack}`);
  // cancel: nothing sent
  await row.hover();
  await row.getByTestId("thread-x").click();
  const confirm = page.getByTestId("thread-confirm");
  await expect(confirm).toContainText("It is archived in Hermes and can be restored.");
  await page.getByTestId("thread-cancel").click();
  await expect(confirm).toHaveCount(0);
  await expect(row).toBeVisible();
  expect(await calls("thread.remove")).toEqual([]);
  // escape cancels too
  await row.hover();
  await row.getByTestId("thread-x").click();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  expect(await calls("thread.remove")).toEqual([]);
  // confirm: the row goes
  await row.hover();
  await row.getByTestId("thread-x").click();
  await page.getByTestId("thread-confirm-remove").click();
  await expect(row).toHaveCount(0);
  expect((await calls("thread.remove")).map((c) => c.params)).toEqual([{ bot: "kami", thread: ids.slack }]);
  // a running thread asks "Stop it and remove?"; confirming ends its turn and the row goes
  const og = page.getByTestId(`thread-row-${ids.og}`);
  await og.hover();
  await og.getByTestId("thread-x").click();
  await expect(confirm).toContainText("It is still working. Stop it and remove?");
  await expect(page.getByTestId("thread-confirm-remove")).toHaveText("Stop and remove");
  await page.getByTestId("thread-confirm-remove").click();
  await expect(og).toHaveCount(0);
  // a thread waiting on an approval: removing it takes its ask out of Needs you
  const docs = page.getByTestId(`thread-row-${ids.docs}`);
  await docs.hover();
  await docs.getByTestId("thread-x").click();
  await page.getByTestId("thread-confirm-remove").click();
  await expect(docs).toHaveCount(0);
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
  // after a reload the removed threads stay gone (archived, not listed)
  await page.reload();
  await expect(page.getByTestId(`thread-row-${ids.notes}`)).toBeVisible();
  await expect(page.locator(`[data-thread="${ids.slack}"], [data-thread="${ids.og}"], [data-thread="${ids.docs}"]`)).toHaveCount(0);
});
