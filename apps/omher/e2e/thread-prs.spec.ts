// A thread's pull requests (src/threads/prs.ts, ThreadPrs.tsx; BOUNDARY rule 40), against the mock bridge:
// 1. each thread row shows its newest PR's mark: the number, GitHub's state and the checks (open/draft only);
//    a PR gh cannot say anything about shows the number alone;
// 2. the transcript shows a card under the answer that named each PR (never under the person's own link), with the
//    repository, state and checks; a click opens the PR's page through the app's opener, Refresh asks GitHub again;
// 3. an open PR with failing checks puts its thread in Needs you ("checks failing on #n") and rings once for that
//    head; it leaves when the checks pass; the thread's own state never moves;
// 4. a bot's answer naming a PR at the end of a turn brings the mark and card;
// 5. a peer bot's thread (the mock lists one; the real bridge lists none over SSH) is never read: number, no state.
// Shots: OMHER_SHOTS=<dir> -> thread-prs-{rows,card,needs}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(SHOTS, `thread-prs-${name}.png`), caret: "initial" });
}

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

const SHA = "0123456789abcdef0123456789abcdef01234567";
const url = (n: number, repo = "acme/web") => `https://github.com/${repo}/pull/${n}`;

/** Kami's threads, oldest first in this list (the sidebar shows them newest first). */
const SEED = [
  { title: "No PR yet", ago: 600, messages: [["user", "look at the logs"], ["assistant", "The logs are clean."]] },
  { title: "Offline PR", ago: 500, messages: [["assistant", `Opened ${url(105)}.`]] },
  { title: "Draft PR", ago: 400, messages: [["assistant", `Draft: ${url(103)}`]] },
  { title: "Merged PR", ago: 300, messages: [["assistant", `Merged ${url(102)}`]] },
  {
    title: "Failing PR",
    ago: 200,
    messages: [
      ["user", `the old attempt was ${url(99)}`],
      ["assistant", `First try: ${url(100)}`],
      ["user", "try again"],
      ["assistant", `Opened ${url(101)}, checks are running.`],
    ],
  },
];

async function seed() {
  await mock("mock.prs", {
    prs: {
      "acme/web#100": { state: "closed", checks: "failing" },
      "acme/web#101": { state: "open", checks: "failing", head: SHA },
      "acme/web#102": { state: "merged", checks: "passing" },
      "acme/web#103": { state: "draft", checks: "running" },
    },
  });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: SEED });
  return Object.fromEntries(SEED.map((s, i) => [s.title, threads[i] as string]));
}

async function open(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __notes: string[]; __opened: string[]; __watched: boolean; Notification: unknown; open: unknown };
    w.__notes = [];
    w.__opened = [];
    w.__watched = true;
    w.Notification = class {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string } = {}) {
        w.__notes.push(`${title}|${opts.body ?? ""}`);
      }
      close() {}
    };
    w.open = (u: string) => {
      w.__opened.push(u);
      return null;
    };
    Object.defineProperty(document, "visibilityState", { get: () => (w.__watched ? "visible" : "hidden") });
    document.hasFocus = () => w.__watched;
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const row = (page: Page, id: string) => page.getByTestId(`thread-row-${id}`);
const notes = (page: Page) => page.evaluate(() => (window as unknown as { __notes: string[] }).__notes.slice());

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("each row shows its newest PR: number, state and checks; no gh answer shows the number alone", async ({ page }) => {
  const id = await seed();
  await open(page);
  const mark = (t: string) => row(page, id[t]).getByTestId("thread-pr");
  await expect(mark("Failing PR")).toHaveAttribute("data-state", "open");
  await expect(mark("Failing PR")).toHaveAttribute("data-checks", "failing");
  await expect(mark("Failing PR")).toContainText("#101"); // the newest of the bot's two, not the person's #99
  await expect(mark("Merged PR")).toHaveAttribute("data-state", "merged");
  await expect(mark("Merged PR")).toHaveAttribute("data-checks", "none"); // checks only for an open PR or a draft
  await expect(mark("Draft PR")).toHaveAttribute("data-state", "draft");
  await expect(mark("Draft PR")).toHaveAttribute("data-checks", "running");
  await expect(mark("Offline PR")).toHaveAttribute("data-state", "unknown");
  await expect(mark("Offline PR")).toHaveText("#105");
  await expect(row(page, id["No PR yet"]).getByTestId("thread-pr")).toHaveCount(0);
  await shot(page, "rows");
  // the row's name carries it for a screen reader, and the row stays one keyboard stop
  await expect(row(page, id["Failing PR"]).getByTestId("thread-open")).toHaveAccessibleName(/#101 · Open · Checks failing/);
  // read once per thread in view: never a second time within five minutes, and never the thread's run state
  await expect.poll(async () => (await calls("thread.prs")).length).toBe(5);
  await expect(row(page, id["Failing PR"])).toHaveAttribute("data-state", "idle");
  await page.waitForTimeout(500);
  expect((await calls("thread.prs")).length).toBe(5);
});

test("the transcript's card: under the answer that named it, opens the PR page on a click, Refresh asks again", async ({ page }) => {
  const id = await seed();
  await open(page);
  await row(page, id["Failing PR"]).getByTestId("thread-open").click();
  const chat = page.getByTestId("thread-chat");
  const cards = chat.getByTestId("thread-pr-card");
  await expect(cards).toHaveCount(2); // #101 and #100, the bot's own; the person's #99 has none
  const newest = cards.filter({ hasText: "#101" });
  await expect(newest).toContainText("acme/web");
  await expect(newest).toContainText("Open");
  await expect(newest).toContainText("Checks failing");
  await expect(newest).toHaveAttribute("data-checks", "failing");
  await expect(cards.filter({ hasText: "#100" })).toContainText("Closed");
  await expect(cards.filter({ hasText: "#99" })).toHaveCount(0);
  await shot(page, "card");
  // keyboard: the card's open button and Refresh are reachable and named
  await newest.getByTestId("thread-pr-open").focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(() => (window as unknown as { __opened: string[] }).__opened)).toEqual([url(101)]);
  const before = (await calls("thread.prs")).filter((c) => c.params.thread === id["Failing PR"]);
  await mock("mock.prs", { prs: { "acme/web#101": { state: "open", checks: "passing", head: SHA } } });
  await newest.getByTestId("thread-pr-refresh").click();
  await expect(newest).toContainText("Checks passing");
  const after = (await calls("thread.prs")).filter((c) => c.params.thread === id["Failing PR"]);
  expect(after.length).toBe(before.length + 1);
  expect(after[after.length - 1].params.fresh).toBe(true);
});

test("Needs you lists an open PR with failing checks, rings once for that head, and lets it go when they pass", async ({ page }) => {
  const id = await seed();
  await open(page);
  const strip = page.getByTestId("needs-strip");
  await expect(strip).toBeVisible();
  await expect(page.getByTestId("needs-line")).toContainText("1 needs you");
  await expect(page.getByTestId("needs-line")).toHaveText("1 needs you · Failing PR");
  await expect.poll(() => notes(page)).toEqual(["Failing PR: checks failing on #101|acme/web"]);
  await strip.click();
  const item = page.getByTestId("needs-pr");
  await expect(item).toContainText("Checks");
  await expect(item).toContainText("checks failing on #101");
  await shot(page, "needs");
  await item.click();
  await expect(page.getByTestId("thread-title")).toHaveText("Failing PR");
  // the same failing head read again (Refresh): no second notification
  const card = page.getByTestId("thread-pr-card").filter({ hasText: "#101" });
  await card.getByTestId("thread-pr-refresh").click();
  await page.waitForTimeout(300);
  expect(await notes(page)).toHaveLength(1);
  // the checks pass: the thread leaves Needs you
  await mock("mock.prs", { prs: { "acme/web#101": { state: "open", checks: "passing", head: SHA } } });
  await card.getByTestId("thread-pr-refresh").click();
  await expect(strip).toHaveCount(0);
  await expect(row(page, id["Failing PR"]).getByTestId("thread-pr")).toHaveAttribute("data-checks", "passing");
  // a draft with failing checks, a merged one, a closed one: never a Needs reason
  await mock("mock.prs", { prs: { "acme/web#103": { state: "draft", checks: "failing" } } });
  await row(page, id["Draft PR"]).getByTestId("thread-open").click();
  await expect(page.getByTestId("thread-pr-card")).toHaveAttribute("data-checks", "failing");
  await expect(strip).toHaveCount(0);
  expect(await notes(page)).toHaveLength(1);
});

test("a bot answer naming a PR at the end of a turn brings its mark and card", async ({ page }) => {
  const id = await seed();
  await open(page);
  await row(page, id["No PR yet"]).getByTestId("thread-open").click();
  await expect(page.getByTestId("thread-pr-card")).toHaveCount(0);
  await mock("mock.prs", { prs: { "acme/web#110": { state: "open", checks: "running" } } });
  await mock("mock.threadAnswer", { bot: "kami", thread: id["No PR yet"], text: `Opened ${url(110)} for the log fix.` });
  const card = page.getByTestId("thread-pr-card");
  await expect(card).toContainText("#110");
  await expect(card).toContainText("Checks running");
  await expect(row(page, id["No PR yet"]).getByTestId("thread-pr")).toHaveAttribute("data-checks", "running");
});

test("a bot on another computer: its thread's PR shows the number with no state, and nothing is read", async ({ page }) => {
  await open(page);
  await page.evaluate(() => localStorage.removeItem("omher.mockPeers"));
  await page.reload();
  // connect the mock "other computer" the way the person does (peers.spec.ts): sidebar + > Connect over SSH
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-ssh").click();
  const peerCard = page.getByTestId("peer-card");
  await peerCard.getByTestId("peer-host").fill("demo@host.example");
  await peerCard.getByTestId("peer-label").fill("Mac mini");
  await peerCard.getByTestId("peer-check").click();
  await expect(peerCard.getByTestId("peer-found")).toBeVisible();
  await peerCard.getByTestId("peer-connect").click();
  const peerRow = page.locator('button.bot[data-testid$=":mini"]');
  await expect(peerRow).toBeVisible();
  const key = (await peerRow.getAttribute("data-testid"))!.replace(/^bot-/, "");
  // the mock lists a thread under it so the page's rule can be seen; the real bridge lists none over SSH (rule 31)
  const { threads } = await mock("mock.threads", { bot: key, threads: [{ title: "Remote PR", ago: 60, messages: [["assistant", `Opened ${url(120)}`]] }] });
  await mock("mock.prs", { prs: { "acme/web#120": { state: "open", checks: "failing" } } });
  const r = row(page, threads[0]);
  await expect(r).toBeVisible();
  await r.getByTestId("thread-open").click();
  const card = page.getByTestId("thread-pr-card");
  await expect(card).toContainText("#120");
  await expect(card).toHaveAttribute("data-state", "unknown");
  await expect(card).toContainText("another computer");
  await expect(card.getByTestId("thread-pr-refresh")).toHaveCount(0);
  await expect(r.getByTestId("thread-pr")).toHaveText("#120");
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
  expect((await calls("thread.prs")).filter((c) => c.params.bot === key)).toEqual([]);
});
