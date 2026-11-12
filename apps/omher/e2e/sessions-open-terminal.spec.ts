// A New session opens as omher's chat or as the agent's own terminal (Chat | Terminal beside the agent, on the mock
// host): the choice and its memory, Start running the program in a terminal and never a chat, how a session opened
// as a terminal ends, restarts and comes back after omher restarts, and OpenCode both ways.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

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

type Call = { op: string; agent?: string; cwd?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const count = async (page: Page, op: string, agent?: string) => (await calls(page)).filter((c) => c.op === op && (!agent || c.agent === agent)).length;

async function open(page: Page, installed = ["claude", "codex", "omh", "dsh", "grok", "opencode"]) {
  await page.addInitScript((list) => {
    // the first load starts clean; a reload (the restart) keeps what the first one stored
    if (!sessionStorage.getItem("__kept")) {
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.sessions.open");
      localStorage.removeItem("omher.resume");
    }
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = list;
  }, installed);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A New session draft on `agent`, in the picker's folder (nothing is started). */
async function draft(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("session-way")).toBeVisible();
}

const terminalClaude = async (page: Page) => {
  await draft(page, "claude");
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
};

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Claude Code: pick Terminal, press Start: its terminal runs and no chat starts", async ({ page }) => {
  await open(page);
  await draft(page, "claude");
  // Chat is the default; the picked word is gray
  await expect(page.getByTestId("session-way-chat")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("session-way-terminal").click();
  await expect(page.getByTestId("session-way-terminal")).toHaveAttribute("aria-checked", "true");
  // a terminal draft behaves as Grok's: composer off, a Start button, the note
  await expect(page.getByTestId("composer")).toBeDisabled();
  await expect(page.getByTestId("draft-note")).toContainText("opens in its terminal in web-app when you press Start");
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  const starts = (await calls(page)).filter((c) => c.op === "start");
  expect(starts).toHaveLength(1);
  expect(starts[0]).toMatchObject({ agent: "claude", cwd: "/Users/you/code/web-app" });
  expect(await count(page, "chat.start")).toBe(0);
  // nothing was typed into the program
  expect(await count(page, "write")).toBe(0);
});

test("OpenCode both ways: Chat sends a first message and starts the chat; a second draft as Terminal starts the program", async ({ page }) => {
  await open(page);
  await draft(page, "opencode");
  await page.getByTestId("composer").fill("Add a dark mode toggle");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("(mock OpenCode) You said: Add a dark mode toggle");
  expect(await count(page, "chat.start", "opencode")).toBe(1);
  expect(await count(page, "start")).toBe(0);

  await draft(page, "opencode");
  await expect(page.getByTestId("session-way-chat")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("opencode");
  expect(await count(page, "start", "opencode")).toBe(1);
  expect(await count(page, "chat.start", "opencode")).toBe(1); // still only the first one
});

test("an agent without a way shows it dimmed with a reason: DSH has no terminal, Grok has no chat", async ({ page }) => {
  await open(page);
  await draft(page, "dsh");
  const term = page.getByTestId("session-way-terminal");
  await expect(term).toHaveAttribute("aria-disabled", "true");
  await expect(term).toHaveAttribute("title", /no terminal here/);
  await expect(page.getByTestId("session-way-chat")).toHaveAttribute("aria-checked", "true");
  await term.click(); // dimmed, so nothing changes
  await expect(page.getByTestId("session-way-chat")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("composer")).toBeEnabled();

  await draft(page, "grok");
  const chat = page.getByTestId("session-way-chat");
  await expect(chat).toHaveAttribute("aria-disabled", "true");
  await expect(chat).toHaveAttribute("title", /no chat here/);
  await expect(page.getByTestId("session-way-terminal")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("session-go")).toBeVisible();
});

test("the last pick is remembered per agent; typed text is kept across Terminal and back to Chat", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  // the next Claude Code draft has Terminal preselected; another agent is still on Chat
  await draft(page, "claude");
  await expect(page.getByTestId("session-way-terminal")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("session-go")).toBeVisible();
  await page.getByTestId("session-way-chat").click();
  await page.getByTestId("composer").fill("fix the 502s");
  await page.getByTestId("session-way-terminal").click();
  await expect(page.getByTestId("composer")).toBeDisabled();
  // the terminal starts without the text: one quiet line says so
  await expect(page.getByTestId("composer-held")).toContainText("starts without this text");
  await page.getByTestId("session-way-chat").click();
  await expect(page.getByTestId("composer")).toBeEnabled();
  await expect(page.getByTestId("composer")).toHaveValue("fix the 502s");
  await expect(page.getByTestId("composer-held")).toHaveCount(0);
  await draft(page, "codex");
  await expect(page.getByTestId("session-way-chat")).toHaveAttribute("aria-checked", "true");
});

test("a session opened as a terminal ends with its program, shows the ended line and Restart starts a fresh terminal", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-ended")).toBeVisible();
  await expect(page.getByTestId("session-restart")).toBeVisible();
  await expect(page.getByTestId("session-status")).not.toHaveText("Starting");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  expect(await count(page, "chat.start")).toBe(0);

  await page.getByTestId("session-restart").click();
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await expect(page.getByTestId("session-status")).toHaveText("Running");
  const starts = (await calls(page)).filter((c) => c.op === "start");
  expect(starts).toHaveLength(2);
  expect(starts[1]).toMatchObject({ agent: "claude", cwd: "/Users/you/code/web-app" });
  expect(await count(page, "chat.start")).toBe(0);
});

test("after omher restarts it comes back as a terminal session that is not running; nothing starts until Resume", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  await expect.poll(async () => (await page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null")))?.sessions?.[0]?.open).toBe("terminal");
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await expect(page.getByTestId("session-idle")).toBeVisible();
  await expect(page.getByTestId("session-resume")).toBeVisible();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("session-terminal-toggle")).toHaveCount(0);
  await page.waitForTimeout(400);
  expect(await count(page, "start")).toBe(0);
  expect(await count(page, "chat.start")).toBe(0);

  await page.getByTestId("session-resume").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect(await count(page, "start", "claude")).toBe(1);
  expect(await count(page, "chat.start")).toBe(0);
});

test("a terminal-opened session has no Chat toggle and its row shows the live dot; a chat-opened Claude Code keeps the toggle", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  const rows = page.locator("[data-testid=session-list] .ss-row");
  await expect(page.getByTestId("session-terminal-toggle")).toHaveCount(0);
  await expect(page.getByTestId("model-pill")).toHaveCount(0);
  await expect(rows.first().getByTestId("live-dot")).toBeVisible();

  await draft(page, "claude");
  await page.getByTestId("session-way-chat").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-terminal-toggle")).toBeVisible();
  await expect(page.getByTestId("model-pill")).toBeVisible();
  await expect(rows.first().getByTestId("live-dot")).toHaveCount(0);
  expect(await count(page, "chat.start", "claude")).toBe(1);
});
