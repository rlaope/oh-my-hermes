// The bot opens threads itself (bridge `split`), against the mock bridge with recorded answers (mock.answer); no model:
// 1. a main-chat answer with two ```omher-thread``` blocks -> two rows appear under the bot, the main chat shows two
//    link lines under the answer, and no raw block text is ever on screen (not while it streams either); each task
//    went to its own thread; the main-chat send carried the threads note;
// 2. an answer with an ```omher-thread-route``` block -> "Send this to <title>?" card; nothing moves until Send there;
//    Send there -> the person's message lands in that thread (chat.send session=<id>), a link line, still two rows;
// 3. Keep here moves nothing; a simple answer has no block and opens nothing.
// Shots (taken first): OMHER_SHOTS=<dir> -> split-{links,route-card}.png
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
type Submit = { bot: string; session_id: string; session?: string; text: string; hint?: boolean };
const submits = async (): Promise<Submit[]> => (await mock("mock.submits")).submits;
/** What went to the bot's threads (session set), in order: the bridge's own task sends and the person's. */
const threadSubmits = async () => (await submits()).filter((x) => x.session).map((x) => ({ session: x.session!, text: x.text }));

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(SHOTS, `split-${name}.png`), caret: "initial" });
}

async function setup(page: Page) {
  await page.addInitScript(() => localStorage.setItem("omher.theme", "dark"));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // the app has read Kami's threads (so its main-chat turns carry the note)
  await expect.poll(async () => (await calls("thread.list")).some((c) => c.params.bot === "kami")).toBe(true);
  // a watcher: did any raw block text ever show in the timeline (while streaming too)?
  await page.evaluate(() => {
    const w = window as unknown as { __rawSeen: boolean };
    w.__rawSeen = false;
    const check = () => {
      const tl = document.querySelector("[data-testid=timeline]");
      if (tl && /omher-thread|"task":/.test((tl as HTMLElement).innerText)) w.__rawSeen = true;
    };
    new MutationObserver(check).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
}
const rawSeen = (page: Page) => page.evaluate(() => (window as unknown as { __rawSeen: boolean }).__rawSeen);

async function send(page: Page, text: string) {
  const box = page.getByTestId("composer");
  await box.click();
  await box.fill(text);
  await page.keyboard.press("Enter");
}

const fence = (kind: string, obj: unknown) => "```" + kind + "\n" + JSON.stringify(obj) + "\n```";
const SPLIT_ANSWER = [
  "두 갈래로 나눠서 스레드 두 개에서 진행할게요.",
  "",
  fence("omher-thread", { title: "OG 대시보드 502 원인 찾기", task: "OG 대시보드 /v1/responses 502 원인을 gateway 로그에서 찾아줘" }),
  "",
  fence("omher-thread", { title: "v0.3 릴리스 노트 초안", task: "v0.3 릴리스 노트 초안을 docs/RELEASE.md에 써줘" }),
].join("\n");
const MAIN_ASK = "502 원인 찾고, 릴리스 노트 초안도 써줘";

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function splitIntoTwo(page: Page) {
  await setup(page);
  await mock("mock.answer", { bot: "kami", text: SPLIT_ANSWER });
  await send(page, MAIN_ASK);
  const tree = page.getByTestId("threads-kami");
  await expect(tree.getByRole("treeitem")).toHaveCount(2);
  const links = page.getByTestId("thread-link");
  await expect(links).toHaveCount(2);
  return { tree, links };
}

test("two omher-thread blocks: two rows under Kami, two link lines, no raw block text, tasks sent to each", async ({ page }) => {
  const { tree, links } = await splitIntoTwo(page);
  await expect(links.nth(0)).toContainText("OG 대시보드 502 원인 찾기");
  await expect(links.nth(1)).toContainText("v0.3 릴리스 노트 초안");
  await expect(page.getByTestId("timeline")).toContainText("두 갈래로 나눠서 스레드 두 개에서 진행할게요.");
  await page.mouse.move(900, 600);
  await shot(page, "links");
  // never a raw block on screen, while streaming or after
  expect(await rawSeen(page)).toBe(false);
  await expect(page.getByTestId("timeline")).not.toContainText("omher-thread");
  // the main send carried the threads note; each task went to its own thread, with no note
  const main = (await submits()).filter((x) => !x.session);
  expect(main.map((x) => [x.text, x.hint])).toEqual([[MAIN_ASK, true]]);
  const ids = await tree.getByRole("treeitem").evaluateAll((els) => els.map((e) => e.getAttribute("data-thread")));
  const tasks = await threadSubmits();
  expect(tasks.map((x) => x.text)).toEqual(["OG 대시보드 /v1/responses 502 원인을 gateway 로그에서 찾아줘", "v0.3 릴리스 노트 초안을 docs/RELEASE.md에 써줘"]);
  expect(new Set(tasks.map((x) => x.session))).toEqual(new Set(ids));
  // the app itself sent only the main message
  expect((await calls("chat.send")).map((c) => c.params)).toEqual([{ bot: "kami", text: MAIN_ASK }]);
  // a link opens its thread
  await links.nth(0).click();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", tasks[0].session);
  await expect(page.getByTestId("thread-title")).toHaveText("OG 대시보드 502 원인 찾기");
});

test("the real model's layout (JSON on the opening fence line, close on the next) opens two threads, no raw text", async ({ page }) => {
  await setup(page);
  const openLine = (obj: unknown) => "```omher-thread " + JSON.stringify(obj) + "\n```";
  const answer = [
    openLine({ title: "Settings dark-mode toggle", task: "Add a dark-mode toggle; check the theme with `pnpm dev`" }),
    "",
    openLine({ title: "v0.3 release notes", task: "Write the v0.3 release notes from git log" }),
    "",
    "두 작업은 서로 독립적이라 thread 두 개로 나눴습니다.",
  ].join("\n");
  await mock("mock.answer", { bot: "kami", text: answer });
  await send(page, "설정 페이지 dark-mode toggle 추가하고 v0.3 release notes도 써줘");
  const tree = page.getByTestId("threads-kami");
  await expect(tree.getByRole("treeitem")).toHaveCount(2);
  const links = page.getByTestId("thread-link");
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toContainText("Settings dark-mode toggle");
  await expect(links.nth(1)).toContainText("v0.3 release notes");
  await expect(page.getByTestId("timeline")).toContainText("두 작업은 서로 독립적이라 thread 두 개로 나눴습니다.");
  expect(await rawSeen(page)).toBe(false);
  await expect(page.getByTestId("timeline")).not.toContainText("omher-thread");
  expect((await threadSubmits()).map((x) => x.text)).toEqual([
    "Add a dark-mode toggle; check the theme with `pnpm dev`",
    "Write the v0.3 release notes from git log",
  ]);
});

test("a route block asks first; Send there moves the message into that thread; still two rows", async ({ page }) => {
  const { tree } = await splitIntoTwo(page);
  const ids = await tree.getByRole("treeitem").evaluateAll((els) => els.map((e) => e.getAttribute("data-thread")!));
  const ogId = (await threadSubmits()).find((x) => x.text.includes("502"))!.session;
  expect(ids).toContain(ogId);
  // wait for both thread turns to finish before the next main turn
  await expect.poll(async () => (await tree.getByRole("treeitem").evaluateAll((els) => els.map((e) => e.getAttribute("data-state"))))).toEqual(["done", "done"]);
  const before = (await calls("chat.send")).length;
  const ask = "로그 보니까 14:31부터 keep-alive 리셋이 몰려 있어";
  await mock("mock.answer", { bot: "kami", text: "이건 OG 대시보드 502 스레드에서 이어가는 게 좋겠어요.\n" + fence("omher-thread-route", { thread: ogId }) });
  await send(page, ask);
  const card = page.getByTestId("thread-route");
  await expect(card).toBeVisible();
  await expect(card).toContainText("OG 대시보드 502 원인 찾기");
  await expect(card).toContainText(ask);
  await page.mouse.move(900, 600);
  await shot(page, "route-card");
  // nothing moved yet: only the main-chat send of this turn
  await page.waitForTimeout(300);
  expect((await calls("chat.send")).slice(before).map((c) => c.params.session)).toEqual([undefined]);
  expect(await rawSeen(page)).toBe(false);
  await card.getByTestId("thread-route-send").click();
  await expect.poll(async () => (await calls("chat.send")).slice(before + 1).map((c) => c.params)).toEqual([{ bot: "kami", session: ogId, text: ask }]);
  await expect(page.getByTestId("thread-route-done")).toBeVisible();
  await expect(page.getByTestId("thread-link")).toHaveCount(3);
  await expect(tree.getByRole("treeitem")).toHaveCount(2); // a route never makes a thread
  expect(((await mock("thread.list", { bot: "kami" })).threads as unknown[]).length).toBe(2);
  // the message is in that thread
  await page.getByTestId("thread-link").last().click();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", ogId);
  await expect(page.getByTestId("thread-chat").getByTestId("timeline")).toContainText(ask);
});

test("Keep here moves nothing; a simple answer opens nothing; a route to an unknown id shows no card", async ({ page }) => {
  await setup(page);
  // a simple question: answered directly, no block, no thread
  await mock("mock.answer", { bot: "kami", text: "지금은 14:32예요." });
  await send(page, "지금 몇 시야?");
  await expect(page.getByTestId("timeline")).toContainText("지금은 14:32예요.");
  await expect(page.getByTestId("thread-link")).toHaveCount(0);
  // a route to an id that is not an open thread: no card, nothing moves
  await mock("mock.answer", { bot: "kami", text: "그 스레드 이야기예요.\n" + fence("omher-thread-route", { thread: "stored-th-404" }) });
  await send(page, "그거 이어서 해줘");
  await expect(page.getByTestId("timeline")).toContainText("그 스레드 이야기예요.");
  await page.waitForTimeout(300);
  await expect(page.getByTestId("thread-route")).toHaveCount(0);
  // a real thread, then a route to it: Keep here closes the card and sends nothing
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "Nightly 빌드 실패 원인", ago: 60 }] });
  await expect(page.getByTestId("threads-kami").getByRole("treeitem")).toHaveCount(1);
  const before = (await calls("chat.send")).length;
  await mock("mock.answer", { bot: "kami", text: "Nightly 스레드 이야기 같아요.\n" + fence("omher-thread-route", { thread: threads[0] }) });
  await send(page, "캐시 키 바꾼 뒤로 다시 깨졌어");
  await page.getByTestId("thread-route-keep").click();
  await expect(page.getByTestId("thread-route-done")).toContainText(/Kept here|여기 뒀어요/);
  await page.waitForTimeout(300);
  expect((await calls("chat.send")).slice(before).map((c) => c.params.session)).toEqual([undefined]);
  expect(((await mock("thread.list", { bot: "kami" })).threads as unknown[]).length).toBe(1);
  expect(await rawSeen(page)).toBe(false);
});
