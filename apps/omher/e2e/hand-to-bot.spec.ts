// Hand to <bot> (src/handover/), against the mock bridge:
// 1. a TERMINALS row's menu -> Hand to a bot… opens a card that shows the first message before anything is sent: the
//    session's folder, the branch, git status and diff stat of the bot's worktree that holds it, and the goal line;
//    Open thread makes a thread under the picked bot (thread.create) whose first message is exactly that text
//    (chat.send session=<thread>); nothing is typed into the terminal and the session stays;
// 2. a folder outside the picked bot's worktrees is handed with no git facts; Cancel sends nothing;
// 3. a Worktrees row's menu -> Hand to a bot… does the same from the right panel, read as the panel's bot and sent
//    to the bot picked on the card.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "h1") res(msg);
    };
    ws.send(JSON.stringify({ id: "h1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
type Call = { op: string; params: Record<string, any> };
const calls = async (op?: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => !op || c.op === op);

/** The app with the folder dialog answering `folder`. */
async function open(page: Page, folder: string) {
  await page.addInitScript((f) => {
    for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "__omherMockHistory"]) localStorage.removeItem(k);
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = f;
    w.__omherMockAgents = ["claude", "codex", "omh"];
  }, folder);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function newShell(page: Page): Promise<string> {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-shell").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  return (await page.getByTestId("terminal").getAttribute("data-session"))!;
}

/** Everything the page wrote to a terminal's program (typing, a paste). */
const typed = (page: Page) =>
  page.evaluate(() =>
    ((window as unknown as { __omherSessionCalls?: { op: string; data?: string }[] }).__omherSessionCalls ?? [])
      .filter((c) => c.op === "write")
      .map((c) => c.data ?? "")
      .join(""),
  );

const KEEPALIVE = [
  "Handover from omher: pick up the work in this folder.",
  [
    "- Folder: `/w/gateway-keepalive`",
    "- Branch: `fix/keepalive` at 3f2c1a9",
    "- Status: 2 changed files, 1 untracked",
    "- Diff stat (uncommitted, vs HEAD): 2 files, +4 -1",
    "  - `gateway/upstream.py` +1 -1",
    "  - `tests/test_upstream.py` +3 -0",
    "  - `notes/재시도.md` untracked",
  ].join("\n"),
];
const CLOSING = "Nothing was moved or closed: the folder, its files and any terminal open in it stay as they are. Work there with your own tools.";

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a TERMINALS row hands its folder to a bot: the card shows the first message, Open thread sends exactly it", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const id = await newShell(page);
  const before = await typed(page);
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await page.getByTestId("session-row-menu").getByTestId("session-hand").click();
  const card = page.getByTestId("handover");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("handover-goal")).toBeFocused();
  // read from the picked bot's (Kami's) worktree that holds the folder: its branch, status and diff stat
  await expect(card.getByTestId("handover-preview")).toHaveText([...KEEPALIVE, CLOSING].join("\n\n"));
  await page.getByTestId("handover-goal").fill("finish the keepalive fix and open a PR");
  await expect(card.getByTestId("handover-preview")).toContainText("Goal: finish the keepalive fix and open a PR");
  expect(await calls("thread.create")).toHaveLength(0);

  await page.getByTestId("handover-send").click();
  await expect(card).toHaveCount(0);
  const made = await calls("thread.create");
  expect(made).toHaveLength(1);
  expect(made[0].params.bot).toBe("kami");
  expect(made[0].params.title).toBe("gateway-keepalive (fix/keepalive)");
  await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
  const sent = (await calls("chat.send"))[0].params;
  expect(sent.bot).toBe("kami");
  expect(sent.session).toBeTruthy();
  expect(sent.text).toBe([...KEEPALIVE, "Goal: finish the keepalive fix and open a PR", CLOSING].join("\n\n"));
  // the thread is open with that message; the terminal got nothing and is still listed
  await expect(page.getByTestId("bubble-user").last()).toContainText("Handover from omher");
  await expect(page.locator('[role="treeitem"][aria-level="2"]', { hasText: "gateway-keepalive (fix/keepalive)" })).toBeVisible();
  expect(await typed(page)).toBe(before);
  await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  // only reads besides the one thread: the worktree list and one diff
  const ops = (await calls()).map((c) => c.op);
  expect(ops.filter((op) => op.startsWith("panel."))).toEqual(expect.arrayContaining(["panel.worktrees", "panel.diff"]));
  for (const op of ["chat.interrupt", "approval.respond", "folder.open", "thread.remove"]) expect(ops).not.toContain(op);
});

test("a folder outside the picked bot's worktrees goes with no git facts; Cancel sends nothing", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  const id = await newShell(page);
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await page.getByTestId("session-hand").click();
  const prev = page.getByTestId("handover-preview");
  await expect(prev).toHaveText(
    [
      "Handover from omher: pick up the work in this folder.",
      "- Folder: `/home/you/code/web-app`\n- Git: omher did not read this folder's status; check it with `git status` and `git diff --stat` there.",
      CLOSING,
    ].join("\n\n"),
  );
  // another bot: its own worktrees are looked at (Friren has none)
  await page.getByTestId("handover-bot").click();
  await page.getByTestId("handover-bot-friren").click();
  await expect(page.getByTestId("handover-bot")).toContainText("Friren");
  await expect(prev).toContainText("omher did not read");
  // a right click or a press inside the card is the card's, not the row's (no row menu, no drag)
  await prev.click({ button: "right" });
  await expect(page.getByTestId("session-row-menu")).toHaveCount(0);
  await expect(page.getByTestId("handover")).toBeVisible();
  await page.getByTestId("handover-cancel").click();
  await expect(page.getByTestId("handover")).toHaveCount(0);
  // Escape closes it too
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await page.getByTestId("session-hand").click();
  await expect(page.getByTestId("handover")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("handover")).toHaveCount(0);
  expect(await calls("thread.create")).toHaveLength(0);
  expect(await calls("chat.send")).toHaveLength(0);
});

test("a Worktrees row hands its worktree to the bot picked on the card", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-worktrees").click();
  const trees = page.getByTestId("panel-tree");
  await expect(trees).toHaveCount(2);
  await trees.nth(0).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Hand to a bot…"]);
  await menu.getByTestId("session-hand").click();
  const card = page.getByTestId("handover");
  // read as Kami, whose tab lists it, whichever bot it goes to
  await page.getByTestId("handover-bot").click();
  await page.getByTestId("handover-bot-friren").click();
  await expect(card.getByTestId("handover-preview")).toHaveText([...KEEPALIVE, CLOSING].join("\n\n"));
  await page.getByTestId("handover-goal").fill("review the timeout change");
  await page.getByTestId("handover-goal").press("Enter");
  await expect(card).toHaveCount(0);
  const made = await calls("thread.create");
  expect(made).toHaveLength(1);
  expect(made[0].params.bot).toBe("friren");
  await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
  const sent = (await calls("chat.send"))[0].params;
  expect(sent.bot).toBe("friren");
  expect(sent.text).toBe([...KEEPALIVE, "Goal: review the timeout change", CLOSING].join("\n\n"));
  const diffs = await calls("panel.diff");
  expect(diffs.every((c) => c.params.bot === "kami" && c.params.path === "/w/gateway-keepalive")).toBe(true);
  await expect(page.locator('[role="treeitem"][aria-level="2"]', { hasText: "gateway-keepalive (fix/keepalive)" })).toBeVisible();
  await expect(page.getByTestId("bubble-user").last()).toContainText("Goal: review the timeout change");
});
