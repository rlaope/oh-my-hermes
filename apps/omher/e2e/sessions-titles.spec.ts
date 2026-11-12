// SESSIONS rows name the conversation, not the folder: line 1 is the session's name (a name the person gave,
// else the agent's own title, else a summary of the first message, else the folder), line 2 the folder and the
// agent. Double-click the name or right-click › Rename to name it; Enter saves, Esc cancels, empty = automatic.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const CLAUDE_SESSION = "11111111-2222-4333-8444-555555555555"; // the mock Claude Code's session id

async function mock(op: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const out = await new Promise<{ result?: Record<string, unknown> }>((res) => {
    ws.onmessage = (m) => res(JSON.parse(String(m.data)));
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out.result ?? {};
}

async function open(page: Page, saved: Record<string, string> = {}) {
  await page.addInitScript((titles) => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.setItem("omher.sessions.titles", JSON.stringify(titles));
  }, saved);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A New session chat on `agent` in `folder`, started by its first message `first` (default: a slash command,
 *  which names nothing, so the session starts unnamed). */
async function start(page: Page, agent: string, folder: string, first = "/status") {
  await page.evaluate((f) => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = f), folder);
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  // a draft is "New session" until it starts, and cannot be renamed yet
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("New session");
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

async function say(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

const rows = (page: Page) => page.locator("[data-testid=session-list] .ss-row");

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a first message names the session as it starts it (a draft is New session until then)", async ({ page }) => {
  await open(page);
  await start(page, "codex", "/Users/you/work/api-server", "Add pagination to the users endpoint");
  const row = rows(page).first();
  await expect(row.getByTestId("session-name")).toHaveText("Add pagination to the users endpoint");
  await expect(row.getByTestId("session-name")).toHaveAttribute("data-source", "prompt");
  await expect(row.getByTestId("session-sub")).toHaveText("api-server · Codex");
  await expect(page.getByTestId("session-title")).toHaveText("Add pagination to the users endpoint");
});

test("a row shows a summary of the first message, and the folder moves to line 2", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  const row = rows(page).first();
  // no message yet: the folder is the name, line 2 the agent alone
  await expect(row.getByTestId("session-name")).toHaveText("web-app");
  await expect(row.getByTestId("session-name")).toHaveAttribute("data-source", "folder");
  await expect(row.getByTestId("session-sub")).toHaveText("Claude Code");

  // a slash command names nothing
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  await page.getByTestId("card-approval").getByRole("button", { name: "Deny" }).click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(row.getByTestId("session-name")).toHaveText("web-app");

  await say(page, "Fix the login redirect loop after OAuth sign-in. It started after the last deploy.");
  await expect(row.getByTestId("session-name")).toHaveText("Fix the login redirect loop after OAuth…");
  await expect(row.getByTestId("session-name")).toHaveAttribute("data-source", "prompt");
  await expect(row.getByTestId("session-sub")).toHaveText("web-app · Claude Code");
  // later messages do not rename it
  await say(page, "Also check the logout page");
  await expect(row.getByTestId("session-name")).toHaveText("Fix the login redirect loop after OAuth…");
  // the header shows the name, with the agent and folder after it
  await expect(page.getByTestId("session-title")).toHaveText("Fix the login redirect loop after OAuth…");
  await expect(page.getByTestId("session-agent")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/web-app");
  await expect(page.getByTestId("session-cwd").locator("..")).toHaveAttribute("title", "/Users/you/code/web-app");

  // Korean, with a command and a file reference in front
  await start(page, "codex", "/Users/you/work/api-server");
  await say(page, "/review @src/routes/users.ts 사용자 목록 API에 페이지네이션 추가해줘. 테스트도 같이");
  const ko = rows(page).first();
  await expect(ko.getByTestId("session-name")).toHaveText("사용자 목록 API에 페이지네이션 추가해줘");
  await expect(ko.getByTestId("session-sub")).toHaveText("api-server · Codex");

  // line 2 carries the folder: the muted ink (4.5:1 or better on the sidebar and the selected row), not the quiet one
  const [sub, muted] = await ko.getByTestId("session-sub").evaluate((el) => {
    const probe = document.createElement("span");
    probe.style.color = "var(--muted)";
    el.appendChild(probe);
    const out = [getComputedStyle(el).color, getComputedStyle(probe).color];
    probe.remove();
    return out;
  });
  expect(sub).toBe(muted);

  // one line each, cut with an ellipsis rather than wrapped
  for (const r of [row, ko]) {
    const [ws, h] = await r.getByTestId("session-name").evaluate((el) => [getComputedStyle(el).whiteSpace, Math.round(el.getBoundingClientRect().height)]);
    expect(ws).toBe("nowrap");
    expect(h).toBe(18);
  }
});

test("the agent's own title replaces the summary, live", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  const row = rows(page).first();
  await say(page, "Fix the login redirect loop after OAuth sign-in");
  await expect(row.getByTestId("session-name")).toHaveAttribute("data-source", "prompt");
  // Claude Code titles the conversation (session_title_changed in the stream)
  await say(page, "/title OAuth redirect loop");
  await expect(row.getByTestId("session-name")).toHaveText("OAuth redirect loop");
  await expect(row.getByTestId("session-name")).toHaveAttribute("data-source", "agent");
  await expect(page.getByTestId("session-title")).toHaveText("OAuth redirect loop");
  await expect(row.getByTestId("session-sub")).toHaveText("web-app · Claude Code");
});

test("the title Claude Code wrote in its own session file arrives after a turn (cli.title)", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  const row = rows(page).first();
  await say(page, "fix the flaky checkout test");
  await expect(row.getByTestId("session-name")).toHaveText("fix the flaky checkout test");
  await mock("mock.cliTitle", { agent: "claude", session: CLAUDE_SESSION, title: "Flaky checkout test" });
  await say(page, "and the cart test");
  await expect(row.getByTestId("session-name")).toHaveText("Flaky checkout test");
  const asked = ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === "cli.title");
  expect(asked.length).toBeGreaterThan(0);
  expect(asked[0].params).toMatchObject({ agent: "claude", session: CLAUDE_SESSION, cwd: "/Users/you/code/web-app" });
});

test("an oh-my-hermes session takes the title Hermes gives the folder chat", async ({ page }) => {
  await open(page);
  await start(page, "omh", "/Users/you/work/api");
  const row = rows(page).first();
  await expect(row.getByTestId("session-name")).toHaveText("api");
  const opened = ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).find((c) => c.op === "folder.open")!;
  expect(opened).toBeTruthy();
  const fid = await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/sessions/sessions.ts");
    const s = m.getSessions();
    return s.getState().list[0].agentSession as string;
  });
  await mock("mock.emit", { events: [{ event: "session.title", bot: "kami", session: fid, title: "Audit the API routes" }] });
  await expect(row.getByTestId("session-name")).toHaveText("Audit the API routes");
  await expect(row.getByTestId("session-sub")).toHaveText("api · oh-my-hermes");
});

test("rename inline: double-click or right-click › Rename; Enter saves, Esc cancels, empty restores the automatic name", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  const row = rows(page).first();
  const name = row.getByTestId("session-name");
  await say(page, "Fix the login redirect loop");

  // double-click → a field with the current name selected; Esc leaves it as it was
  await name.dblclick();
  const input = row.getByTestId("session-rename-input");
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("Fix the login redirect loop");
  expect(await input.evaluate((el: HTMLInputElement) => [el.selectionStart, el.selectionEnd])).toEqual([0, 27]);
  await input.fill("throwaway");
  await page.keyboard.press("Escape");
  await expect(input).toHaveCount(0);
  await expect(name).toHaveText("Fix the login redirect loop");
  // Esc in the field did not leave the session
  await expect(page.getByTestId("session-chat")).toBeVisible();

  // Enter saves; the person's name beats the agent's title
  await name.dblclick();
  await input.fill("Auth bug");
  await page.keyboard.press("Enter");
  await expect(name).toHaveText("Auth bug");
  await expect(name).toHaveAttribute("data-source", "person");
  await expect(page.getByTestId("session-title")).toHaveText("Auth bug");
  await expect(row.locator(".ss-open")).toBeFocused();
  await say(page, "/title Agent title");
  await expect(name).toHaveText("Auth bug");
  // saved on this computer, under the agent's session id
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.sessions.titles") || "{}"))).toEqual({
    [`claude:${CLAUDE_SESSION}`]: "Auth bug",
  });

  // right-click › Rename; an empty name goes back to the automatic one (now the agent's title)
  await row.click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Rename", /^Show in (Finder|Explorer|file manager)$/, "Open in Terminal", "Copy conversation id", "New session here", "Close session"]);
  await menu.getByTestId("session-rename").click();
  await expect(input).toBeFocused();
  await input.fill("   ");
  await page.keyboard.press("Enter");
  await expect(name).toHaveText("Agent title");
  await expect(name).toHaveAttribute("data-source", "agent");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.sessions.titles") || "{}"))).toEqual({});

  // Close session from the same menu still asks first
  await row.click({ button: "right" });
  await page.getByTestId("session-menu-close").click();
  await expect(page.locator("[data-testid^=session-confirm-]")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(rows(page)).toHaveCount(1);
});

test("a saved name comes back when the same conversation runs again", async ({ page }) => {
  await open(page, { [`claude:${CLAUDE_SESSION}`]: "Kept name" });
  await start(page, "claude", "/Users/you/code/web-app");
  await expect(rows(page).first().getByTestId("session-name")).toHaveText("Kept name");
});

for (const theme of ["dark", "light"] as const) {
  test(`screenshot: three named sessions in the sidebar, ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
    mkdirSync(SHOTS, { recursive: true });
    await open(page);
    await page.evaluate(async (t) => (await import(/* @vite-ignore */ "/src/state/store.ts")).getStore().actions.setTheme(t), theme);
    await start(page, "claude", "/Users/you/code/web-app");
    await say(page, "Fix the login redirect loop after OAuth sign-in. It started after the last deploy.");
    await say(page, "/title Fix OAuth login redirect loop");
    await start(page, "codex", "/Users/you/work/api-server");
    await say(page, "/review @src/routes/users.ts 사용자 목록 API에 페이지네이션 추가해줘");
    await start(page, "claude", "/Users/you/notes");
    await say(page, "```\nTODO\n```\nSummarize this week's meeting notes into action items");
    await page.mouse.move(900, 790);
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(SHOTS, `session-titles-${theme}.png`), animations: "disabled" });
  });
}
