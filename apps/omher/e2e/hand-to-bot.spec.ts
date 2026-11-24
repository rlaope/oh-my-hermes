// Hand to <bot> (src/handover/), against the mock bridge:
// 1. a TERMINALS row's menu -> Hand to a bot… opens a card that shows the first message before anything is sent: the
//    session's folder, the branch, git status and diff stat of the bot's worktree that holds it, and the goal line;
//    Open thread makes a thread under the picked bot (thread.create) whose first message is exactly that text
//    (chat.send session=<thread>); nothing is typed into the terminal and the session stays;
// 2. a folder outside the picked bot's worktrees is handed with no git facts; Cancel sends nothing;
// 3. a Worktrees row's menu -> Hand to a bot… does the same from the right panel, read as the panel's bot (the
//    card's default) and sent to the bot picked on the card;
// 4. a removed worktree: the card says it is gone and sends nothing;
// 5. no Hand where nothing may be sent: a bot over SSH (its rows are folders on another computer), and no bot of this
//    computer online (no menu, and no read);
// 6. one bot of this computer online: the item names it and the card has no picker; with several, Escape in the bot
//    list closes only the list; the keyboard's context-menu key opens a Worktrees row's menu at the row;
// 7. a terminal in a split (a cell of the split card) hands its folder as a row does: the same item, the same reads,
//    the same thread and message; reached from the keyboard; no Hand with no bot of this computer online;
// 8. focus order (WCAG 2.4.3), for a row and a cell alike: the menu opened from the keyboard and closed with Escape,
//    and the Hand card closed with Escape, Cancel or Open thread, give the keyboard back to the row's or cell's face;
//    a press outside the card leaves it where that press put it.
import { expect, test, type Page } from "@playwright/test";
import { dragRowOnto } from "./split-drag-helpers";

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
  // the row's own bot by default; read as Kami, whose tab lists it, whichever bot it goes to
  await expect(page.getByTestId("handover-bot")).toContainText("Kami");
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

async function openWorktrees(page: Page) {
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-worktrees").click();
}

test("a worktree removed since the list was read: the card says so and Open thread sends nothing", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await openWorktrees(page);
  await expect(page.getByTestId("panel-tree")).toHaveCount(2);
  await mock("mock.treeGone", { path: "/w/gateway-keepalive" });
  await page.getByTestId("panel-tree").nth(0).click({ button: "right" });
  await page.getByTestId("session-hand").click();
  await expect(page.getByTestId("handover-gone")).toHaveText("This worktree is no longer there. Nothing was sent.");
  await expect(page.getByTestId("handover-preview")).toHaveCount(0);
  await expect(page.getByTestId("handover-send")).toBeDisabled();
  await page.getByTestId("handover-goal").press("Enter");
  await page.waitForTimeout(300);
  expect(await calls("thread.create")).toHaveLength(0);
  expect(await calls("chat.send")).toHaveLength(0);
});

test("a Worktrees row whose diff cannot be read at all (removed inside the bridge's scan) sends nothing", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await openWorktrees(page);
  await expect(page.getByTestId("panel-tree")).toHaveCount(2);
  await mock("mock.treeGone", { path: "/w/gateway-keepalive", code: "unavailable" });
  await page.getByTestId("panel-tree").nth(0).click({ button: "right" });
  await page.getByTestId("session-hand").click();
  await expect(page.getByTestId("handover-unreadable")).toHaveText("omher could not read this worktree, so nothing was sent. Refresh the Worktrees tab and try again.");
  await expect(page.getByTestId("handover-preview")).toHaveCount(0);
  await expect(page.getByTestId("handover-send")).toBeDisabled();
  await page.getByTestId("handover-goal").press("Enter");
  await page.waitForTimeout(300);
  expect(await calls("thread.create")).toHaveLength(0);
  expect(await calls("chat.send")).toHaveLength(0);
});

test("no Hand on a Worktrees row of a bot over SSH", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-ssh").click();
  const peer = page.getByTestId("peer-card");
  await peer.getByTestId("peer-host").fill("demo@host.example");
  await peer.getByTestId("peer-label").fill("Mac mini");
  await peer.getByTestId("peer-check").click();
  await expect(peer.getByTestId("peer-found")).toBeVisible();
  await peer.getByTestId("peer-connect").click();
  await expect(peer).toHaveCount(0);
  await page.getByTestId("bot-mac-mini:mini").click();
  // a bot with no other places opens its panel from its name in the header
  await page.getByTestId("places").or(page.getByTestId("who")).first().click();
  await page.getByTestId("panel-tab-worktrees").click();
  const row = page.getByTestId("panel-tree");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("main");
  await row.click({ button: "right" });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("session-row-menu")).toHaveCount(0);
  await expect(page.getByTestId("handover")).toHaveCount(0);
  expect(await calls("panel.diff")).toHaveLength(0);
});

test("with no bot of this computer online, no Hand is offered and nothing is read", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  const id = await newShell(page);
  await page.getByTestId("bot-kami").click();
  await openWorktrees(page);
  await expect(page.getByTestId("panel-tree")).toHaveCount(2);
  for (const bot of ["kami", "friren", "default", "omh-tui"]) await mock("mock.botStatus", { bot, status: "offline" });
  await expect(page.getByTestId("bot-kami").getByTestId("bot-sub")).toHaveText("Not connected");
  await page.getByTestId("panel-tree").nth(0).click({ button: "right" });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("session-row-menu")).toHaveCount(0);
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByTestId("session-hand")).toHaveCount(0);
  await page.keyboard.press("Escape");
  expect(await calls("panel.diff")).toHaveLength(0);
});

test("with one bot of this computer online the item names it and the card has no picker", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const id = await newShell(page);
  for (const bot of ["friren", "default", "omh-tui"]) await mock("mock.botStatus", { bot, status: "offline" });
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toHaveText("Not connected");
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await expect(page.getByTestId("session-hand")).toHaveText("Hand to Kami…");
  await page.getByTestId("session-hand").click();
  const card = page.getByTestId("handover");
  await expect(card.locator(".ho-head")).toHaveText("Hand to Kami");
  await expect(page.getByTestId("handover-bot")).toHaveCount(0);
  await expect(card.getByTestId("handover-preview")).toContainText("- Branch: `fix/keepalive`");
});

test("Escape in the bot list closes only the list; the next Escape closes the card", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  const id = await newShell(page);
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  await page.getByTestId("session-hand").click();
  await expect(page.getByTestId("handover-preview")).toBeVisible();
  await page.getByTestId("handover-bot").click();
  await expect(page.getByTestId("handover-bot-friren")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("handover-bot-friren")).toHaveCount(0);
  await expect(page.getByTestId("handover")).toBeVisible();
  await page.getByTestId("handover-goal").press("Escape");
  await expect(page.getByTestId("handover")).toHaveCount(0);
  expect(await calls("thread.create")).toHaveLength(0);
});

test("the context-menu key opens a Worktrees row's menu at the row, not in the corner", async ({ page }) => {
  await open(page, "/home/you/code/web-app");
  await openWorktrees(page);
  const row = page.getByTestId("panel-tree").nth(1);
  await row.focus();
  await row.dispatchEvent("contextmenu", { clientX: 0, clientY: 0, button: 0 });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu).toBeVisible();
  const r = (await row.boundingBox())!;
  const m = (await menu.boundingBox())!;
  expect(Math.abs(m.y - (r.y + r.height))).toBeLessThan(8);
  expect(m.x).toBeGreaterThan(r.x);
});

const cell = (page: Page, id: string) => page.locator(`[data-testid="split-cell"][data-session="${id}"]`);

/** Sessions `a` and `b` in one split: `a` opened, `b`'s row dragged onto its right side. */
async function split(page: Page, a: string, b: string) {
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await dragRowOnto(page, b, a, "right");
  await expect(page.locator(`[data-testid="split-pane"][data-session="${b}"]`)).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("split-cell")).toHaveCount(2);
}

/** The bridge calls made since `from` of the ops a hand-over can make, `thread.create`'s fresh key and `chat.send`'s
 *  thread left out (each hand-over makes its own thread). */
const handCalls = async (from: number) =>
  (await calls())
    .slice(from)
    .filter((c) => c.op.startsWith("panel.") || c.op === "thread.create" || c.op === "chat.send")
    .map((c) => ({ op: c.op, params: c.op === "chat.send" ? { ...c.params, session: "<thread>" } : c.op === "thread.create" ? { ...c.params, key: "<key>" } : c.params }));

test("a terminal in a split hands its folder from its cell exactly as its row does", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const a = await newShell(page);
  const b = await newShell(page);
  const c = await newShell(page);
  await split(page, a, b);
  const before = await typed(page);
  // c is a row: hand it over first
  let from = (await calls()).length;
  await page.getByTestId(`session-${c}`).click({ button: "right" });
  await page.getByTestId("session-row-menu").getByTestId("session-hand").click();
  await expect(page.getByTestId("handover-preview")).toHaveText([...KEEPALIVE, CLOSING].join("\n\n"));
  await page.getByTestId("handover-goal").fill("finish the keepalive fix");
  await page.getByTestId("handover-send").click();
  await expect(page.getByTestId("handover")).toHaveCount(0);
  await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
  const fromRow = await handCalls(from);
  // a's cell: the row's menu, item for item, Hand included
  from = (await calls()).length;
  await cell(page, a).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Rename", /^Show in (Finder|Explorer|file manager)$/, "Open in Terminal", "Copy link", "Hand to a bot…", "New terminal here", "Close session"]);
  await menu.getByTestId("session-hand").click();
  const card = page.getByTestId("handover");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("handover-goal")).toBeFocused();
  await expect(card.getByTestId("handover-preview")).toHaveText([...KEEPALIVE, CLOSING].join("\n\n"));
  // a press or a right click inside the card is the card's: no cell menu, no drag, and no cell takes the focus
  const focusBefore = await page.getByTestId("split-cell").evaluateAll((cs) => cs.map((c) => c.getAttribute("data-focused")));
  await card.getByTestId("handover-preview").click({ button: "right" });
  await card.getByTestId("handover-preview").click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("split-drop")).toHaveCount(0);
  expect(await page.getByTestId("split-cell").evaluateAll((cs) => cs.map((c) => c.getAttribute("data-focused")))).toEqual(focusBefore);
  await page.getByTestId("handover-goal").fill("finish the keepalive fix");
  await page.getByTestId("handover-send").click();
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await calls("chat.send")).length).toBe(2);
  const fromCell = await handCalls(from);
  // the same thread and first message; the same diff (the worktree list may come from the 10 s cache)
  const writes = (l: typeof fromRow) => l.filter((x) => !x.op.startsWith("panel."));
  expect(writes(fromCell)).toEqual(writes(fromRow));
  expect(writes(fromCell).map((x) => x.op)).toEqual(["thread.create", "chat.send"]);
  expect(fromCell.find((x) => x.op === "chat.send")!.params.text).toBe([...KEEPALIVE, "Goal: finish the keepalive fix", CLOSING].join("\n\n"));
  const reads = (l: typeof fromRow) => l.filter((x) => x.op.startsWith("panel."));
  expect(reads(fromCell).filter((x) => x.op === "panel.diff")).toEqual(reads(fromRow).filter((x) => x.op === "panel.diff"));
  for (const x of reads(fromCell)) expect(["panel.worktrees", "panel.diff"]).toContain(x.op);
  // nothing typed into a terminal; the split and its sessions stay
  expect(await typed(page)).toBe(before);
  await expect(page.getByTestId("split-cell")).toHaveCount(2);
  await expect(cell(page, a)).toBeVisible();
});

test("each cell of a split of two folders hands its own folder, focused or not", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const a = await newShell(page);
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/home/you/code/web-app"));
  const b = await newShell(page);
  await split(page, a, b);
  // a (the first cell) takes the focus: b is now the second cell and not the focused one
  await cell(page, a).locator(".sc-open").click();
  await expect(cell(page, a)).toHaveAttribute("data-focused", "true");
  await expect(cell(page, b)).toHaveAttribute("data-focused", "false");
  const card = page.getByTestId("handover");
  const WEB_APP = [
    "Handover from omher: pick up the work in this folder.",
    "- Folder: `/home/you/code/web-app`\n- Git: omher did not read this folder's status; check it with `git status` and `git diff --stat` there.",
  ];
  // b's cell: its own folder, outside the bot's worktrees, so no git facts and no diff read
  let from = (await calls()).length;
  await cell(page, b).click({ button: "right" });
  await page.getByTestId("session-row-menu").getByTestId("session-hand").click();
  await expect(card.getByTestId("handover-preview")).toHaveText([...WEB_APP, CLOSING].join("\n\n"));
  await page.getByTestId("handover-send").click();
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
  let made = await handCalls(from);
  expect(made.filter((x) => x.op === "panel.diff")).toEqual([]);
  expect(made.find((x) => x.op === "chat.send")!.params.text).toBe([...WEB_APP, CLOSING].join("\n\n"));
  expect(made.find((x) => x.op === "thread.create")!.params.title).not.toContain("gateway-keepalive");
  // handing b over did not focus b (Open thread opened the new thread instead)
  await expect(cell(page, b)).toHaveAttribute("data-focused", "false");
  // a's cell (the first, the one that held the focus): its own folder, with the git facts of the bot's worktree
  // that holds it
  from = (await calls()).length;
  await cell(page, a).click({ button: "right" });
  await page.getByTestId("session-row-menu").getByTestId("session-hand").click();
  await expect(card.getByTestId("handover-preview")).toHaveText([...KEEPALIVE, CLOSING].join("\n\n"));
  await page.getByTestId("handover-send").click();
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await calls("chat.send")).length).toBe(2);
  made = await handCalls(from);
  expect(made.find((x) => x.op === "thread.create")!.params.title).toBe("gateway-keepalive (fix/keepalive)");
  expect(made.find((x) => x.op === "chat.send")!.params.text).toBe([...KEEPALIVE, CLOSING].join("\n\n"));
  const diffs = made.filter((y) => y.op === "panel.diff");
  expect(diffs.length).toBeGreaterThan(0);
  for (const x of diffs) expect(x.params.path).toBe("/w/gateway-keepalive");
});

test("a cell's Hand item is reached from the keyboard and named for assistive technology", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const a = await newShell(page);
  const b = await newShell(page);
  await split(page, a, b);
  // the keyboard's context-menu key on the cell
  const face = cell(page, a).locator(".sc-open");
  await face.focus();
  await face.dispatchEvent("contextmenu", { clientX: 0, clientY: 0, button: 0 });
  const menu = page.getByRole("menu", { name: /actions/i });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Rename" })).toBeFocused();
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  const hand = menu.getByRole("menuitem", { name: "Hand to a bot…" });
  await expect(hand).toBeFocused();
  await page.keyboard.press("Enter");
  const card = page.getByRole("dialog", { name: "Hand to Kami" });
  await expect(card).toBeVisible();
  await expect(page.getByTestId("handover-goal")).toBeFocused();
  await expect(card.getByTestId("handover-preview")).toContainText("- Folder: `/w/gateway-keepalive`");
  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);
  expect(await calls("thread.create")).toHaveLength(0);
  expect(await calls("chat.send")).toHaveLength(0);
});

test("with no bot of this computer online, a cell offers no Hand and nothing is read", async ({ page }) => {
  await open(page, "/w/gateway-keepalive");
  const a = await newShell(page);
  const b = await newShell(page);
  await split(page, a, b);
  for (const bot of ["kami", "friren", "default", "omh-tui"]) await mock("mock.botStatus", { bot, status: "offline" });
  await expect(page.getByTestId("bot-kami").getByTestId("bot-sub")).toHaveText("Not connected");
  await cell(page, a).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Rename", /^Show in (Finder|Explorer|file manager)$/, "Open in Terminal", "Copy link", "New terminal here", "Close session"]);
  await expect(menu.getByTestId("session-hand")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  expect(await calls("panel.diff")).toHaveLength(0);
  expect(await calls("panel.worktrees")).toHaveLength(0);
});

/** Whether `face` holds the keyboard: document.activeElement itself, not a class or an attribute. */
const holds = (face: ReturnType<Page["locator"]>) => face.evaluate((el) => el === document.activeElement);

/** The TERMINALS row's face, or the split card cell's, of session `id`. */
const faceOf = (page: Page, kind: "row" | "cell", id: string) => (kind === "row" ? page.getByTestId(`session-${id}`).locator(".ss-open") : cell(page, id).locator(".sc-open"));

/** A shell in /w/gateway-keepalive whose `kind` face is drawn: a row, or a cell of a split with a second shell. */
async function faceFor(page: Page, kind: "row" | "cell") {
  await open(page, "/w/gateway-keepalive");
  const a = await newShell(page);
  if (kind === "cell") {
    const b = await newShell(page);
    await split(page, a, b);
    // the drop gives the new pane the keyboard on the next frame (focusSplitPane); let that land first, or it takes
    // the keyboard from the menu opened right after
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    await expect.poll(() => page.evaluate((id) => document.activeElement === document.querySelector(`[data-testid="terminal"][data-session="${id}"] .xterm-helper-textarea`), b)).toBe(true);
  }
  return faceOf(page, kind, a);
}

/** The menu opened from the keyboard on `face` (the context-menu key), its Hand item chosen with the arrows and Enter:
 *  the card is open with the goal field holding the keyboard. */
async function handFromKeys(page: Page, face: ReturnType<Page["locator"]>) {
  await face.focus();
  await face.dispatchEvent("contextmenu", { clientX: 0, clientY: 0, button: 0 });
  const menu = page.getByRole("menu", { name: /actions/i });
  await expect(menu.getByRole("menuitem", { name: "Rename" })).toBeFocused();
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(menu.getByRole("menuitem", { name: "Hand to a bot…" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("handover")).toBeVisible();
  await expect(page.getByTestId("handover-goal")).toBeFocused();
  await expect(menu).toHaveCount(0);
}

for (const kind of ["row", "cell"] as const) {
  test(`a ${kind}'s menu closed with Escape gives the keyboard back to the ${kind}`, async ({ page }) => {
    const face = await faceFor(page, kind);
    await face.focus();
    await face.dispatchEvent("contextmenu", { clientX: 0, clientY: 0, button: 0 });
    const menu = page.getByRole("menu", { name: /actions/i });
    await expect(menu.getByRole("menuitem", { name: "Rename" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect.poll(() => holds(face)).toBe(true);
  });

  test(`a ${kind}'s Hand card gives the keyboard back to the ${kind} on Escape, Cancel and Open thread, not after a press outside`, async ({ page }) => {
    const face = await faceFor(page, kind);
    const card = page.getByTestId("handover");
    // Escape
    await handFromKeys(page, face);
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
    await expect.poll(() => holds(face)).toBe(true);
    // Cancel, reached with the keyboard
    await handFromKeys(page, face);
    await page.getByTestId("handover-cancel").focus();
    await page.keyboard.press("Enter");
    await expect(card).toHaveCount(0);
    await expect.poll(() => holds(face)).toBe(true);
    expect(await calls("thread.create")).toHaveLength(0);
    // a press outside: on the terminal, which takes the keyboard; the card does not take it back for the face
    await handFromKeys(page, face);
    await page.getByTestId("terminal").first().click();
    await expect(card).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.activeElement?.classList.contains("xterm-helper-textarea") ?? false)).toBe(true);
    await page.waitForTimeout(200);
    expect(await holds(face)).toBe(false);
    expect(await page.evaluate(() => document.activeElement?.classList.contains("xterm-helper-textarea") ?? false)).toBe(true);
    // Open thread (Enter in the goal field): the thread starts and the keyboard is back on the face
    await handFromKeys(page, face);
    await expect(card.getByTestId("handover-preview")).toContainText("- Folder: `/w/gateway-keepalive`");
    await page.keyboard.press("Enter");
    await expect(card).toHaveCount(0);
    await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
    await expect.poll(() => holds(face)).toBe(true);
  });
}
