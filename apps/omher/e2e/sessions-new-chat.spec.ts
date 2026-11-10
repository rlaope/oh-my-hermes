// SESSIONS + opens a New session chat at once (Codex-style): the agent is picked in the composer row, the folder in
// the chip under the composer (the last folder used, else home). Nothing starts until the first message, which
// goes to the agent as its first prompt, in the folder shown; afterwards both are shown read-only. A draft closes
// without starting anything. (The old two-step + menu, agent then folder, is gone.)
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
/** Where the PR shots go (unset: none are taken). */
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

/** Seven folders, newest first, as the app saves them (the chip offers five). */
const RECENT = [
  { agent: "codex", cwd: "/Users/you/code/web-app", at: 7 },
  { agent: "claude", cwd: "/Users/you/work/api-server", at: 6 },
  { agent: "claude", cwd: "/Users/you/code/mobile", at: 5 },
  { agent: "omh", cwd: "/Users/you/notes", at: 4 },
  { agent: "codex", cwd: "/Volumes/data/datasets", at: 3 },
  { agent: "claude", cwd: "/Users/you/code/old-one", at: 2 },
  { agent: "claude", cwd: "/Users/you/code/older", at: 1 },
];

type Call = { op: string; agent?: string; cwd?: string; input?: { kind: string; text?: string } };

async function open(page: Page, { theme = "dark", recent = RECENT as unknown[], installed = ["claude", "codex", "omh"] } = {}) {
  await page.addInitScript(
    ([t, r, a]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.setItem("omher.sessions.recent", r as string);
      (window as unknown as Record<string, unknown>).__omherPickFolder = "/Users/you/code/new-app";
      (window as unknown as Record<string, unknown>).__omherMockAgents = a;
    },
    [theme, JSON.stringify(recent), installed] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const started = async (page: Page) => (await calls(page)).filter((c) => c.op === "chat.start" || c.op === "start");
const rows = (page: Page) => page.locator("[data-testid=session-list] .ss-row");

/** Rows fade (0.12s), popovers fade in: no pointer on a row, then wait, before a screenshot. */
async function settle(page: Page) {
  await page.mouse.move(700, 300);
  await page.waitForTimeout(400);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of ["dark", "light"] as const) {
  test(`+ opens a New session chat on the last agent and folder; a recent folder, then the first message starts it there (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, { theme });
    await page.getByTestId("session-new").click();

    // the chat is open at once: no popover, a draft row, the composer focused
    const chat = page.getByTestId("session-chat");
    await expect(chat).toHaveAttribute("data-draft", "true");
    await expect(page.locator(".ui-pop")).toHaveCount(0);
    await expect(page.getByTestId("composer")).toBeFocused();
    await expect(page.getByTestId("session-title")).toHaveText("New session");
    const row = rows(page).first();
    await expect(row.getByTestId("session-name")).toHaveText("New session");
    await expect(row.getByTestId("session-sub")).toHaveText("~/code/web-app");
    // the last agent (Codex) in the composer row, the last folder under the composer, its path in the tooltip
    await expect(page.getByTestId("session-agent-pick")).toHaveText("Codex");
    const chip = page.getByTestId("session-folder");
    await expect(chip).toHaveText("web-app");
    await expect(chip).toHaveAttribute("title", "/Users/you/code/web-app");
    await expect(page.getByTestId("draft-note")).toHaveText("Codex starts in web-app with your first message");
    // the chip sits under the composer, on its left edge; the picker in the composer row
    const box = (await page.getByTestId("composer-box").boundingBox())!;
    const c = (await chip.boundingBox())!;
    expect(c.y).toBeGreaterThanOrEqual(box.y + box.height);
    expect(Math.abs(c.x - box.x)).toBeLessThanOrEqual(2);
    const pick = (await page.getByTestId("session-agent-pick").boundingBox())!;
    expect(pick.y).toBeGreaterThan(box.y);
    expect(pick.y + pick.height).toBeLessThan(box.y + box.height);
    expect(await started(page)).toEqual([]);
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await settle(page);
      await page.screenshot({ path: join(SHOTS, `new-session-chat-${theme}-after.png`) });
    }

    // the folder menu: five recents newest first, the current one checked, then Choose folder… and Home
    await chip.click();
    const menu = page.getByTestId("session-folder-menu");
    const recents = menu.getByTestId("session-recent");
    await expect(recents).toHaveCount(5);
    expect(await recents.locator(".ss-n").allTextContents()).toEqual(["web-app", "api-server", "mobile", "notes", "datasets"]);
    expect(await recents.locator(".ss-path").allTextContents()).toEqual(["~/code", "~/work", "~/code", "~", "/Volumes/data"]);
    await expect(recents.first()).toHaveAttribute("aria-pressed", "true");
    await expect(menu.getByTestId("session-choose")).toHaveText("Choose folder…");
    await expect(menu.getByTestId("session-home")).toHaveAttribute("title", "/Users/you");
    // it opens above the composer, on its left edge, and never covers the box
    const pop = (await menu.locator("..").boundingBox())!;
    expect(pop.y + pop.height).toBeLessThanOrEqual(box.y);
    expect(Math.abs(pop.x - box.x)).toBeLessThanOrEqual(1);
    if (SHOTS && theme === "dark") {
      await settle(page);
      await page.screenshot({ path: join(SHOTS, "new-session-folder-menu-dark.png") });
    }
    await recents.filter({ hasText: "api-server" }).click();
    await expect(menu).toHaveCount(0);
    await expect(chip).toHaveText("api-server");
    await expect(row.getByTestId("session-sub")).toHaveText("~/work/api-server");
    // and the agent, from the composer row
    await page.getByTestId("session-agent-pick").click();
    await page.getByTestId("session-agent-claude").click();
    await expect(page.getByTestId("session-agent-pick")).toHaveText("Claude Code");
    expect(await started(page)).toEqual([]);

    // the first message starts Claude Code in ~/work/api-server and is its first prompt
    await page.getByTestId("composer").fill("run the tests");
    await page.keyboard.press("Enter");
    await expect(chat).not.toHaveAttribute("data-draft", "true");
    await expect(page.getByTestId("bubble-user")).toHaveText("run the tests");
    // the sent text leaves the composer (it is not kept as unsent text)
    await expect(page.getByTestId("composer")).toHaveValue("");
    await expect(page.getByTestId("bubble-bot")).toHaveText("(mock Claude Code) You said: run the tests");
    const all = await calls(page);
    const st = all.find((x) => x.op === "chat.start")!;
    expect(st).toMatchObject({ agent: "claude", cwd: "/Users/you/work/api-server" });
    const first = all.find((x) => x.op === "chat.input")!;
    expect(first.input).toEqual({ kind: "send", text: "run the tests" });
    expect(all.indexOf(st)).toBeLessThan(all.indexOf(first));
    // fixed now: the folder and the agent are read-only, in the same places, the path in the tooltip
    await expect(page.getByTestId("session-folder")).toHaveText("api-server");
    await expect(page.getByTestId("session-folder")).toHaveAttribute("title", "/Users/you/work/api-server");
    expect(await page.getByTestId("session-folder").evaluate((e) => e.tagName)).toBe("SPAN");
    await expect(page.getByTestId("session-agent-pick")).toHaveCount(0);
    await expect(page.getByTestId("session-agent-fixed")).toHaveText("Claude Code");
    // the first message names the session (SESSIONS titles); the folder and agent move to line 2 and the header
    await expect(page.getByTestId("session-title")).toHaveText("run the tests");
    await expect(page.getByTestId("session-agent")).toHaveText("Claude Code");
    await expect(row.getByTestId("session-name")).toHaveText("run the tests");
    await expect(row.getByTestId("session-sub")).toHaveText("api-server · Claude Code");
    if (SHOTS) {
      await settle(page);
      await page.screenshot({ path: join(SHOTS, `new-session-started-${theme}.png`) });
    }

    // the next New session opens on what was just used, with that folder first in the recents (once)
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-agent-pick")).toHaveText("Claude Code");
    await expect(page.getByTestId("session-folder")).toHaveText("api-server");
    await page.getByTestId("session-folder").click();
    expect(await page.getByTestId("session-recent").locator(".ss-n").allTextContents()).toEqual(["api-server", "web-app", "mobile", "notes", "datasets"]);
  });
}

test("with no recent folder the chat opens in home; Choose folder… sets the folder, cancelling it changes nothing", async ({ page }) => {
  await open(page, { recent: [] });
  await page.getByTestId("session-start").click();
  const chip = page.getByTestId("session-folder");
  await expect(chip).toHaveText("you");
  await expect(chip).toHaveAttribute("title", "/Users/you");
  // the first installed agent, in menu order
  await expect(page.getByTestId("session-agent-pick")).toHaveText("Claude Code");
  await chip.click();
  await expect(page.getByTestId("session-recent")).toHaveCount(0);
  await expect(page.getByTestId("session-home")).toHaveCount(1);
  await page.evaluate(() => ((window as unknown as Record<string, unknown>).__omherPickFolder = null));
  await page.getByTestId("session-choose").click();
  await expect(chip).toHaveText("you");
  await page.evaluate(() => ((window as unknown as Record<string, unknown>).__omherPickFolder = "/Users/you/code/new-app"));
  await chip.click();
  await page.getByTestId("session-choose").click();
  await expect(chip).toHaveText("new-app");
  expect(await started(page)).toEqual([]);
  // and Home brings it back
  await chip.click();
  await page.getByTestId("session-home").click();
  await expect(chip).toHaveText("you");
});

test("closing a draft starts nothing; + while a draft is open reuses it", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("composer").fill("not sent");
  await page.getByTestId("session-new").click();
  await expect(rows(page)).toHaveCount(1);
  const row = rows(page).first();
  await row.hover();
  await row.getByTestId("session-close").click();
  // no stop question for a draft: it simply goes
  await expect(page.locator("[data-testid^=session-confirm-]")).toHaveCount(0);
  await expect(rows(page)).toHaveCount(0);
  await expect(page.getByTestId("session-none")).toBeVisible();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  await page.waitForTimeout(200);
  expect((await calls(page)).filter((c) => c.op !== "reset")).toEqual([]);
});

test("the agent picker disables missing agents with their install line", async ({ page }) => {
  await open(page, { installed: ["claude", "omh"], recent: [] });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-pick").click();
  const menu = page.getByTestId("session-menu");
  expect(await menu.locator("[data-testid^=session-agent-]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(
    ["claude", "codex", "omh", "pi", "omp", "grok"].map((a) => `session-agent-${a}`),
  );
  for (const a of ["claude", "omh"]) await expect(menu.getByTestId(`session-agent-${a}`)).toBeEnabled();
  for (const a of ["codex", "pi", "omp", "grok"]) {
    await expect(menu.getByTestId(`session-agent-${a}`)).toBeDisabled();
    await expect(menu.getByTestId(`session-agent-${a}`)).toContainText("Not installed");
  }
  await expect(menu.getByTestId("session-agent-codex")).toHaveAttribute("title", /codex was not found on this computer · install: npm i -g @openai\/codex/);
  // the official marks, never letters
  await expect(menu.getByTestId("session-agent-claude").locator('svg[data-mark="claude"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-omh").locator('[data-mark="omh"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-claude")).toHaveAttribute("aria-pressed", "true");
  // the menu opens above the composer, at its right edge
  const box = (await page.getByTestId("composer-box").boundingBox())!;
  const pop = (await menu.locator("..").boundingBox())!;
  expect(pop.y + pop.height).toBeLessThanOrEqual(box.y);
  expect(Math.abs(pop.x + pop.width - (box.x + box.width))).toBeLessThanOrEqual(1);
  await menu.getByTestId("session-agent-omh").click();
  await expect(page.getByTestId("session-agent-pick")).toHaveText("oh-my-hermes");
});

test("the last agent used is no longer installed: the first installed one takes its place", async ({ page }) => {
  await open(page, { installed: ["claude", "codex", "omh"], recent: [{ agent: "pi", cwd: "/Users/you/code/web-app", at: 1 }] });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-pick")).toHaveText("Claude Code");
  await expect(page.getByTestId("composer")).toBeEnabled();
});

test("a terminal agent (Grok) starts in the folder on Start and gets no prompt", async ({ page }) => {
  await open(page, { installed: ["claude", "grok"], recent: [{ agent: "grok", cwd: "/Users/you/code/tui", at: 1 }] });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-pick")).toHaveText("Grok");
  await expect(page.getByTestId("composer")).toBeDisabled();
  await expect(page.getByTestId("draft-note")).toHaveText("Grok opens in its terminal in tui when you press Start");
  await expect(page.getByTestId("send")).toHaveCount(0);
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  // the terminal starts once xterm has loaded and measured itself
  await expect.poll(() => started(page)).toHaveLength(1);
  expect((await started(page))[0]).toMatchObject({ op: "start", agent: "grok", cwd: "/Users/you/code/tui" });
  expect((await calls(page)).filter((c) => c.op === "write" || c.op === "chat.input")).toEqual([]);
});

test("a draft speaks Korean too, and waits in the sidebar while a bot chat is open", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await open(page);
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("draft-note")).toHaveText("첫 메시지를 보내면 Codex가 web-app에서 시작해요");
  await page.getByTestId("session-folder").click();
  await expect(page.getByTestId("session-choose")).toHaveText("폴더 선택…");
  await page.keyboard.press("Escape");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(rows(page)).toHaveCount(1);
  await rows(page).first().locator(".ss-open").click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  expect(await started(page)).toEqual([]);
});
