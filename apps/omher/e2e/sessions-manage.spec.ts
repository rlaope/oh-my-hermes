// Finding, opening and switching sessions (DAG omher-sessions/manage): the row's right-click menu, the sidebar search
// over sessions, continuing a Claude Code or Codex conversation made outside omher, ⌘N / ⌘⇧] / ⌘⇧[, and the asks count.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const CLAUDE_SESSION = "11111111-2222-4333-8444-555555555555"; // the mock Claude Code's session id
const PAST = "bbbbbbbb-1111-4222-8333-444444444444"; // host.ts MOCK_PAST: Claude Code in /Users/you/code/omher

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

type Call = { op: string; cwd?: string; agent?: string; resume?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []) as Call[]);
const rows = (page: Page) => page.locator("[data-testid=session-list] .ss-row");
/** ⌘ or Ctrl, as the page reads navigator.platform. */
const modKey = async (page: Page) => ((await page.evaluate(() => /Mac/.test(navigator.platform))) ? "Meta" : "Control");

async function open(page: Page, recent: { agent: string; cwd: string; at: number }[] = []) {
  await page.addInitScript((r) => {
    localStorage.setItem("omher.sessions.recent", JSON.stringify(r));
    localStorage.removeItem("omher.sessions.titles");
    localStorage.removeItem("omher.resume");
  }, recent);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A Claude Code chat in `folder`, started by `first`. */
async function start(page: Page, folder: string, first: string) {
  await page.evaluate((f) => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = f), folder);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the row menu: reveal and terminal take the folder, copy takes the conversation id, new session here, keyboard", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  await start(page, "/Users/you/code/web-app", "Fix the login redirect");
  const row = rows(page).first();
  await row.click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Rename", /^Show in (Finder|Explorer|file manager)$/, "Open in Terminal", "Copy conversation id", "New session here", "Close session"]);
  // the first item has the focus; arrows move, End and Home jump, Esc closes
  await expect(menu.getByTestId("session-rename")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByTestId("session-reveal")).toBeFocused();
  await page.keyboard.press("End");
  await expect(menu.getByTestId("session-menu-close")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByTestId("session-rename")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  // Reveal, then Open in Terminal: the shell gets only the folder
  await row.click({ button: "right" });
  await menu.getByTestId("session-reveal").click();
  await row.click({ button: "right" });
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByTestId("session-system-terminal")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "reveal" || c.op === "terminal")).toEqual([
    { op: "reveal", cwd: "/Users/you/code/web-app" },
    { op: "terminal", cwd: "/Users/you/code/web-app" },
  ]);

  // Copy conversation id
  await row.click({ button: "right" });
  await menu.getByTestId("session-copy-id").click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(CLAUDE_SESSION);

  // New session here: a draft on Claude Code in the same folder, opened at once
  await row.click({ button: "right" });
  await menu.getByTestId("session-new-here").click();
  await expect(rows(page)).toHaveCount(2);
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("New session");
  await expect(rows(page).first().getByTestId("session-sub")).toHaveText("~/code/web-app");
});

test("a session with no conversation id yet has no Copy item", async ({ page }) => {
  await open(page);
  // a terminal session reports no conversation id
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/api"));
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-codex").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await rows(page).first().click({ button: "right" });
  await expect(page.getByTestId("session-row-menu").getByRole("menuitem")).toHaveText(["Rename", /^Show in /, "Open in Terminal", "New session here", "Close session"]);
});

test("the sidebar search filters sessions by name and folder, and says when none match", async ({ page }) => {
  await open(page);
  await start(page, "/Users/you/code/web-app", "Fix the login redirect");
  await start(page, "/Users/you/code/api", "Add rate limits");
  await expect(rows(page)).toHaveCount(2);
  const search = page.getByRole("searchbox", { name: "Search bots and sessions" });
  await search.fill("login");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("Fix the login redirect");
  await search.fill("API");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("Add rate limits");
  await search.fill("nothing-like-this");
  await expect(rows(page)).toHaveCount(0);
  await expect(page.getByTestId("session-none-match")).toHaveText("No session matches “nothing-like-this”");
  // Esc clears it: both come back
  await search.press("Escape");
  await expect(rows(page)).toHaveCount(2);
});

for (const theme of ["dark", "light"] as const) {
  test(`a search that matches no bot leaves BOTS at its one line and SESSIONS right under it (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await open(page);
    await start(page, "/Users/you/code/web-app", "Fix the login redirect");
    await page.getByTestId("bot-search").fill("web-app");
    const empty = page.getByTestId("side-bots").locator(".bot-empty");
    await expect(empty).toHaveText("No bot named “web-app”");
    await expect(rows(page)).toHaveCount(1);
    const gap = await page.evaluate(() => {
      const line = document.querySelector("[data-testid=side-bots] .bot-empty")!.getBoundingClientRect();
      const head = document.querySelector("[data-testid=side-sessions] .side-sh")!.getBoundingClientRect();
      return head.top - line.bottom;
    });
    expect(gap).toBeLessThanOrEqual(24);
  });
}

test("continue a Claude Code conversation made in its CLI: the list, then the session with its earlier messages", async ({ page }) => {
  await open(page, [{ agent: "claude", cwd: "/Users/you/code/omher", at: 2 }]);
  await page.getByTestId("session-new").click();
  const menu = page.getByTestId("session-menu");
  // the + menu ends with one row per agent that keeps conversations
  await menu.getByTestId("session-more").click();
  await expect(menu.getByTestId("session-past-claude")).toBeVisible();
  await expect(menu.getByTestId("session-past-codex")).toBeVisible();
  await menu.getByTestId("session-past-claude").click();
  const past = page.getByTestId("session-past-menu");
  await expect(past.getByTestId(`session-past-row-${PAST}`)).toContainText("Remember the word MARIGOLD for later");
  await expect(past.getByTestId(`session-past-row-${PAST}`)).toContainText("~/code/omher · 3d");
  // only that agent's conversations in the menu's folders (the recent one and home)
  expect(await page.evaluate(() => (window as unknown as { __omherPastReads: unknown[] }).__omherPastReads)).toEqual([
    { op: "list", agent: "claude", cwds: ["/Users/you/code/omher", "/Users/you"] },
  ]);
  // the back row is one line inside the menu: ‹, the agent's mark and its name side by side, nothing outside
  const geo = await past.evaluate((el) => {
    const pop = el.getBoundingClientRect();
    const back = el.querySelector('[data-testid="session-past-back"]')!;
    const kids = [...back.children].map((c) => c.getBoundingClientRect());
    const b = back.getBoundingClientRect();
    return { inside: kids.every((k) => k.left >= pop.left - 0.5 && k.right <= pop.right + 0.5 && k.top >= b.top - 0.5 && k.bottom <= b.bottom + 0.5), height: b.height, n: kids.length };
  });
  expect(geo).toEqual({ inside: true, height: 30, n: 3 });
  // ← goes back to the agents
  await page.keyboard.press("ArrowLeft");
  await expect(menu).toBeVisible();
  await menu.getByTestId("session-past-claude").click();
  await page.getByTestId(`session-past-row-${PAST}`).click();

  // a session in that folder shows the earlier messages, and its agent continues that conversation
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("Remember the word MARIGOLD for later");
  await expect(page.getByTestId("session-chat")).toContainText("Noted: MARIGOLD.");
  await expect.poll(async () => (await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher", resume: PAST });
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("What was the word?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  // nothing was written: the mock logs no file op for it
  expect((await calls(page)).filter((c) => c.op.startsWith("file.") && c.op !== "file.prune")).toEqual([]);
});

test("an agent with no conversations in these folders says so", async ({ page }) => {
  await open(page, [{ agent: "codex", cwd: "/Users/you/code/empty", at: 1 }]);
  await page.evaluate(() => ((window as unknown as { __omherPastChats: unknown[] }).__omherPastChats = []));
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-more").click();
  await page.getByTestId("session-past-codex").click();
  await expect(page.getByTestId("session-past-none")).toHaveText("No Codex conversations in these folders");
  await page.getByTestId("session-past-back").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
});

test("⌘N opens the + menu; ⌘⇧] and ⌘⇧[ move between sessions; nothing while a Korean word is composing", async ({ page }) => {
  await open(page);
  const mod = await modKey(page);
  await start(page, "/Users/you/code/web-app", "First");
  await start(page, "/Users/you/code/api", "Second");
  // the newest is on top and open
  const names = rows(page).getByTestId("session-name");
  await expect(names).toHaveText(["Second", "First"]);
  await page.locator("body").click({ position: { x: 640, y: 12 } });
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(rows(page).nth(1)).toHaveClass(/active/);
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(rows(page).nth(0)).toHaveClass(/active/);
  await page.keyboard.press(`${mod}+Shift+BracketLeft`);
  await expect(rows(page).nth(1)).toHaveClass(/active/);
  // from a bot's chat, ⌘⇧] opens the first session
  await page.getByTestId("bot-kami").click();
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await expect(rows(page).nth(0)).toHaveClass(/active/);

  await page.keyboard.press(`${mod}+n`);
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("session-menu")).toHaveCount(0);

  // an IME composition's keydown (isComposing) is never a shortcut
  await page.evaluate((m) => {
    const init = { key: "n", code: "KeyN", bubbles: true, cancelable: true, isComposing: true, metaKey: m === "Meta", ctrlKey: m === "Control" };
    document.querySelector('[data-testid="composer"]')?.dispatchEvent(new KeyboardEvent("keydown", init));
  }, mod);
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
});

test("the asks count follows the approvals and questions waiting", async ({ page }) => {
  await open(page);
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherBadge?: number }).__omherBadge)).toBe(0);
  // a chat whose first message asks for an approval: it waits on the person ("Needs you"), not Ready
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/web-app"));
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Needs you");
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherBadge?: number }).__omherBadge)).toBe(1);
  await page.getByTestId("card-approval").getByRole("button", { name: "Allow once" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherBadge?: number }).__omherBadge)).toBe(0);
});
