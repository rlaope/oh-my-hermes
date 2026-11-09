// SESSIONS: the sidebar half under BOTS, the + menu of agent CLIs, a mock terminal session (the browser
// build has no Tauri shell, so the MockHost echoes), switching between a bot chat and a session, closing.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

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

async function open(page: Page, folder = "/Users/you/code/oh-my-hermes") {
  await page.addInitScript((f) => {
    if (!sessionStorage.getItem("__kept")) localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = f;
  }, folder);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** Row backgrounds fade (0.12s) and the pointer must not hover a row before a screenshot. */
async function settle(page: Page) {
  await page.mouse.move(900, 780);
  await page.waitForTimeout(350);
}

const calls = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string; agent?: string; cwd?: string; data?: string; id?: number }[] }).__omherSessionCalls ?? []));

async function startSession(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("bots and sessions split the sidebar about half and half", async ({ page }) => {
  await open(page);
  const bots = await page.getByTestId("side-bots").boundingBox();
  const sess = await page.getByTestId("side-sessions").boundingBox();
  expect(bots && sess).toBeTruthy();
  expect(sess!.y).toBeGreaterThan(bots!.y + bots!.height - 1); // SESSIONS sits under BOTS
  const ratio = bots!.height / sess!.height;
  expect(ratio).toBeGreaterThan(0.85);
  expect(ratio).toBeLessThan(1.18);
  await expect(page.getByTestId("side-sessions")).toContainText("Sessions");
  await expect(page.getByTestId("session-none")).toBeVisible();
  // the top + is still "Add a bot"; the sessions + is its own button
  await expect(page.getByRole("button", { name: "Add a bot" })).toBeVisible();
  await expect(page.getByTestId("session-new")).toHaveAttribute("aria-label", "New session");
  // each half scrolls on its own
  expect(await page.locator("[data-testid=side-bots] .bot-list").evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
});

test("+ lists the agent CLIs with their marks; missing ones are disabled", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  const menu = page.getByTestId("session-menu");
  await expect(menu).toBeVisible();
  const rows = menu.locator("[data-testid^=session-agent-]");
  await expect(rows).toHaveCount(6);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(
    ["claude", "codex", "omh", "pi", "omp", "grok"].map((a) => `session-agent-${a}`),
  );
  await expect(menu.getByTestId("session-agent-claude")).toContainText("Claude Code");
  await expect(menu.getByTestId("session-agent-claude").locator('svg[data-mark="claude"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-codex").locator('svg[data-mark="openai"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-omh").locator('[data-mark="omh"]')).toHaveCount(1);
  for (const a of ["claude", "codex", "omh"]) await expect(menu.getByTestId(`session-agent-${a}`)).toBeEnabled();
  for (const a of ["pi", "omp", "grok"]) {
    await expect(menu.getByTestId(`session-agent-${a}`)).toBeDisabled();
    await expect(menu.getByTestId(`session-agent-${a}`)).toContainText("Not installed");
  }
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
});

test("start a mock session, type, see the echo, then switch to a bot chat and back", async ({ page }) => {
  await open(page);
  await startSession(page, "claude");
  const header = page.getByTestId("header");
  await expect(page.getByTestId("session-title")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/oh-my-hermes");
  await expect(header.locator("button")).toHaveCount(0); // no extra header icons
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row).toContainText("oh-my-hermes");
  await expect(row.locator(".bot-p")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-status")).toHaveText("Running");
  await expect(row.getByTestId("live-dot")).toBeVisible();
  await expect(row).toHaveClass(/active/);
  await expect(page.getByTestId("bot-kami")).not.toHaveAttribute("aria-current", "true");

  // only the agent id and folder went to the host: no command line
  const start = (await calls(page)).find((c) => c.op === "start")!;
  expect(start).toMatchObject({ agent: "claude", cwd: "/Users/you/code/oh-my-hermes" });
  expect(Object.keys(start).sort()).toEqual(["agent", "cols", "cwd", "id", "op", "rows"]);

  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("hello omher");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("you said: hello omher");
  // Ctrl+C passes through to the program
  await page.keyboard.press("Control+c");
  await expect.poll(async () => (await calls(page)).some((c) => c.op === "write" && c.data === "\x03")).toBe(true);
  await expect(page.locator(".xterm-rows")).toContainText("^C");

  // to the bot chat: the composer is back, the session keeps running
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(row).not.toHaveClass(/active/);
  await expect(row.getByTestId("live-dot")).toBeVisible();

  // and back: the same terminal, with what was typed before
  await row.locator(".ss-open").click();
  await expect(page.locator(".xterm-rows")).toContainText("you said: hello omher");
  expect((await calls(page)).filter((c) => c.op === "start")).toHaveLength(1);
});

test("a second session, recent folders, and exit ends a session", async ({ page }) => {
  await open(page);
  await startSession(page, "claude");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api"));
  await startSession(page, "codex");
  const rows = page.locator("[data-testid=session-list] .ss-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("api");
  await expect(rows.first()).toContainText("Codex");
  await expect(page.getByTestId("session-title")).toHaveText("Codex");

  // the + menu opens inside the sidebar, and offers the recent agent+folder pairs
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-recent")).toHaveCount(2);
  const pop = (await page.getByTestId("session-menu").locator("..").boundingBox())!;
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  expect(pop.x).toBeGreaterThanOrEqual(side.x);
  expect(pop.x + pop.width).toBeLessThanOrEqual(side.x + side.width);
  await expect(page.getByTestId("session-recent").first()).toContainText("api");
  await expect(page.getByTestId("session-recent").first().locator(".ss-path")).toHaveText("~/work");
  await page.keyboard.press("Escape");

  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  await expect(rows.first()).toContainText("Codex · Ended");
  await expect(rows.first().getByTestId("live-dot")).toHaveCount(0);
  await expect(page.locator(".xterm-rows")).toContainText("Codex ended");
});

test("loading the page stops sessions an earlier load left running, before anything starts", async ({ page }) => {
  await open(page);
  await expect.poll(async () => (await calls(page)).map((c) => c.op)).toEqual(["reset"]);
  await startSession(page, "claude");
  const ops = (await calls(page)).map((c) => c.op);
  expect(ops.filter((o) => o === "reset")).toHaveLength(1);
  expect(ops.indexOf("reset")).toBeLessThan(ops.indexOf("start"));
  // a reload is a new page load: it resets again
  await page.reload();
  await expect.poll(async () => (await calls(page)).map((c) => c.op)).toEqual(["reset"]);
});

test("xterm loads only when a session opens", async ({ page }) => {
  const scripts: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "script") scripts.push(r.url());
  });
  await open(page);
  await page.waitForLoadState("networkidle");
  expect(scripts.filter((u) => u.includes("xterm"))).toEqual([]);
  await startSession(page, "claude");
  expect(scripts.some((u) => u.includes("xterm"))).toBe(true);
});

test("the stop question is shown whole, and Esc cancels it", async ({ page }) => {
  await open(page);
  await startSession(page, "claude");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  const id = (await row.getAttribute("data-testid"))!.replace("session-", "");
  await row.hover();
  await row.getByTestId("session-close").click();
  const confirm = page.getByTestId(`session-confirm-${id}`);
  const q = confirm.locator(".ss-q");
  await expect(q).toHaveText("Stop Claude Code?");
  expect(await q.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(row.locator(".ss-open")).toBeFocused();
  expect((await calls(page)).some((c) => c.op === "close")).toBe(false);
  await expect(page.getByTestId("session-status")).toHaveText("Running");
});

test("closing a running session asks first and stops the program", async ({ page }) => {
  await open(page);
  await startSession(page, "omh");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  const id = (await row.getAttribute("data-testid"))!.replace("session-", "");
  await row.hover();
  await row.getByTestId("session-close").click();
  const confirm = page.getByTestId(`session-confirm-${id}`);
  await expect(confirm).toContainText("Stop oh-my-hermes?");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toBeVisible();
  expect((await calls(page)).some((c) => c.op === "close")).toBe(false);

  // right-click is the other way to close
  await row.click({ button: "right" });
  await page.getByTestId("session-stop").click();
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "close").length).toBe(1);
  // back to the bot chat, empty section hint again
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("composer").or(page.locator("textarea")).first()).toBeVisible();
  await expect(page.getByTestId("session-none")).toBeVisible();
});

test("an ended session closes without asking", async ({ page }) => {
  await open(page);
  await startSession(page, "claude");
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await row.hover();
  await row.getByTestId("session-close").click();
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(0);
});

test("the terminal follows the light theme", async ({ page }) => {
  await open(page);
  await startSession(page, "claude");
  // what shows: the theme background on the scrollable element, through a transparent viewport
  expect(await page.locator(".xterm-viewport").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  const bg = () => page.locator(".xterm-scrollable-element").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await bg()).toBe("rgb(11, 9, 13)");
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await expect.poll(bg).toBe("rgb(255, 255, 255)");
});

test("screenshots: sidebar with sessions and an open session, dark and light", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  await open(page, "/Users/you/code/oh-my-hermes");
  await startSession(page, "codex");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api-server"));
  await startSession(page, "omh");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher"));
  await startSession(page, "claude");
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("explain the sessions feature");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("you said");
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "session-dark.png") });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.waitForTimeout(300); // the popover fades in
  await page.screenshot({ path: join(SHOTS, "menu-dark.png") });
  await page.keyboard.press("Escape");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "chat-dark.png") });
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "chat-light.png") });
  await page.locator("[data-testid=session-list] .ss-row").first().locator(".ss-open").click();
  await expect(page.locator(".xterm-rows")).toContainText("you said");
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "session-light.png") });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.waitForTimeout(300); // the popover fades in
  await page.screenshot({ path: join(SHOTS, "menu-light.png") });
});
