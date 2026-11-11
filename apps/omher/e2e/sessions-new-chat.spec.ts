// SESSIONS + opens a small menu of the agents anchored to it (installed first, the last one used on top; missing
// ones dimmed with their install line). Picking one opens its New session chat at once: the agent read-only in the
// composer row, the folder in the chip under the composer (the last folder used, else home). Nothing starts until
// the first message, which goes to the agent as its first prompt, in the folder shown. A draft closes without
// starting anything.
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

type Call = { op: string; id?: number; agent?: string; cwd?: string; input?: { kind: string; text?: string } };

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
    // the + menu: the last agent used (Codex) on top and focused; Enter picks it
    const plusMenu = page.getByTestId("session-menu");
    await expect(plusMenu.getByTestId("session-agent-codex")).toBeFocused();
    expect(await started(page)).toEqual([]);
    await page.keyboard.press("Enter");
    await expect(plusMenu).toHaveCount(0);

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
    await expect(page.getByTestId("session-agent-fixed")).toHaveText("Codex");
    const chip = page.getByTestId("session-folder");
    await expect(chip).toHaveText("web-app");
    await expect(chip).toHaveAttribute("title", "/Users/you/code/web-app");
    await expect(page.getByTestId("draft-note")).toHaveText("Codex starts in web-app with your first message");
    // the chip sits under the composer, on its left edge; the agent (read-only) in the composer row
    const box = (await page.getByTestId("composer-box").boundingBox())!;
    const c = (await chip.boundingBox())!;
    expect(c.y).toBeGreaterThanOrEqual(box.y + box.height);
    expect(Math.abs(c.x - box.x)).toBeLessThanOrEqual(2);
    await expect(page.getByTestId("session-agent-fixed").locator("button")).toHaveCount(0);
    expect(await page.getByTestId("session-agent-fixed").evaluate((e) => e.tagName)).toBe("SPAN");
    const pick = (await page.getByTestId("session-agent-fixed").boundingBox())!;
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
    // another agent, from the + menu: the open draft takes it and keeps its folder
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-claude").click();
    await expect(rows(page)).toHaveCount(1);
    await expect(chip).toHaveText("api-server");
    await expect(page.getByTestId("session-agent-fixed")).toHaveText("Claude Code");
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
    await expect(page.getByTestId("session-agent-fixed")).toHaveCount(1);
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

    // the next New session: Claude Code is on top of the menu now, in the folder just used, first in the recents (once)
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu").locator("[role=menuitem]").first()).toHaveAttribute("data-testid", "session-agent-claude");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("session-agent-fixed")).toHaveText("Claude Code");
    await expect(page.getByTestId("session-folder")).toHaveText("api-server");
    await page.getByTestId("session-folder").click();
    expect(await page.getByTestId("session-recent").locator(".ss-n").allTextContents()).toEqual(["api-server", "web-app", "mobile", "notes", "datasets"]);
  });
}

test("with no recent folder the chat opens in home; Choose folder… sets the folder, cancelling it changes nothing", async ({ page }) => {
  await open(page, { recent: [] });
  await page.getByTestId("session-start").click();
  await page.getByTestId("session-agent-claude").click();
  const chip = page.getByTestId("session-folder");
  await expect(chip).toHaveText("you");
  await expect(chip).toHaveAttribute("title", "/Users/you");
  // the first installed agent, in menu order
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("Claude Code");
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
  await page.keyboard.press("Enter");
  await page.getByTestId("composer").fill("not sent");
  await page.getByTestId("session-new").click();
  await page.keyboard.press("Enter");
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

test("the + menu: installed agents first (the last one used on top), missing ones dimmed with their install line; keys work", async ({ page }) => {
  await open(page, { installed: ["claude", "codex", "omo", "dsh"], recent: [{ agent: "dsh", cwd: "/Users/you/code/bot", at: 1 }] });
  const plus = page.getByTestId("session-new");
  await plus.click();
  await expect(plus).toHaveAttribute("aria-expanded", "true");
  const menu = page.getByTestId("session-menu");
  await expect(menu).toHaveAttribute("role", "menu");
  // no chat opens until an agent is picked
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  const items = menu.locator("[role=menuitem]");
  // the first row has the focus, so Enter picks the agent on top
  await expect(menu.getByTestId("session-agent-dsh")).toBeFocused();
  expect(await items.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(
    ["dsh", "claude", "codex", "omo", "omh", "pi", "omp", "grok"].map((a) => `session-agent-${a}`),
  );
  expect(await items.locator(".ss-l").allTextContents()).toEqual(["DSH", "Claude Code", "Codex", "OmO", "oh-my-hermes", "pi", "oh-my-pi", "Grok"]);
  // each with its official mark, never a letter
  for (const a of ["omo", "omp", "omh"]) await expect(menu.getByTestId(`session-agent-${a}`).locator(`img[data-mark="${a}"]`)).toHaveCount(1);
  // DeepSeek Harness's own mark (its whale), drawn in the text colour
  await expect(menu.getByTestId("session-agent-dsh").locator('svg[data-mark="dsh"] path')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-claude").locator('svg[data-mark="claude"]')).toHaveCount(1);
  // missing: dimmed, marked, with the install line in the tooltip; picking one does nothing
  for (const a of ["omh", "pi", "omp", "grok"]) {
    const row = menu.getByTestId(`session-agent-${a}`);
    await expect(row).toHaveAttribute("aria-disabled", "true");
    await expect(row).toHaveClass(/\boff\b/);
    await expect(row).toContainText("Not installed");
  }
  await expect(menu.getByTestId("session-agent-pi")).toHaveAttribute("title", "pi was not found on this computer · install: npm i -g @mariozechner/pi-coding-agent");
  const dim = await menu.getByTestId("session-agent-pi").evaluate((e) => [getComputedStyle(e).color, getComputedStyle(e.querySelector(".ss-ic")!).opacity]);
  const lit = await menu.getByTestId("session-agent-claude").evaluate((e) => [getComputedStyle(e).color, getComputedStyle(e.querySelector(".ss-ic")!).opacity]);
  expect(dim[0]).not.toBe(lit[0]);
  expect(Number(dim[1])).toBeLessThan(1);
  // (aria-disabled, not disabled: the row keeps its tooltip and arrow-key focus)
  await menu.getByTestId("session-agent-pi").click({ force: true });
  await expect(menu).toBeVisible();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  // anchored to the +: it opens right under it, inside the sidebar
  const pb = (await plus.boundingBox())!;
  const pop = (await menu.locator("..").boundingBox())!;
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  expect(pop.y).toBeGreaterThanOrEqual(pb.y + pb.height - 1);
  expect(pop.y - (pb.y + pb.height)).toBeLessThan(12);
  expect(pop.x).toBeGreaterThanOrEqual(side.x);
  expect(pop.x + pop.width).toBeLessThanOrEqual(side.x + side.width);
  // keys: Home goes to the top, arrows move (and wrap), Esc closes and gives the focus back to +
  await page.keyboard.press("Home");
  await expect(menu.getByTestId("session-agent-dsh")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByTestId("session-agent-claude")).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(menu.getByTestId("session-agent-grok")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(plus).toBeFocused();
  await expect(page.getByTestId("session-chat")).toHaveCount(0);
  // ArrowDown twice from the top, then Enter: Codex's New session chat opens at once
  await plus.click();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByTestId("session-agent-codex")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("Codex");
  await expect(page.getByTestId("session-folder")).toHaveText("bot");
  await expect(page.getByTestId("composer")).toBeFocused();
  expect(await started(page)).toEqual([]);
});

test("OmO opens as a chat that answers; DSH opens DeepSeek Harness as a chat with no terminal view", async ({ page }) => {
  await open(page, { installed: ["omo", "dsh"], recent: [] });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omo").click();
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("OmO");
  await expect(page.getByTestId("draft-note")).toHaveText("OmO starts in you with your first message");
  await page.getByTestId("composer").fill("hi");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot")).toHaveText("(mock OmO) You said: hi");
  expect((await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "omo", cwd: "/Users/you" });

  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-dsh").click();
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("DSH");
  await expect(page.getByTestId("draft-note")).toHaveText("DSH starts in you with your first message");
  await page.getByTestId("composer").fill("Remember PLUM-42.");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("(mock DSH) You said: Remember PLUM-42.");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("What was the codeword?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toHaveText("(mock DSH) You said: What was the codeword?");
  // a chat, never a terminal: no Terminal toggle, no PTY start, and one chat that the second message continued
  await expect(page.getByTestId("session-terminal-toggle")).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  const all = await calls(page);
  expect(all.filter((c) => c.op === "start")).toHaveLength(0);
  const dsh = all.filter((c) => c.op === "chat.start" && c.agent === "dsh");
  expect(dsh).toHaveLength(1);
  expect(dsh[0]).toMatchObject({ cwd: "/Users/you" });
  expect(all.filter((c) => c.op === "chat.input" && c.id === dsh[0].id)).toHaveLength(2);
});

test("the last agent used is no longer installed: the first installed one takes its place", async ({ page }) => {
  await open(page, { installed: ["claude", "codex", "omh"], recent: [{ agent: "pi", cwd: "/Users/you/code/web-app", at: 1 }] });
  await page.getByTestId("session-new").click();
  // pi is not installed any more: Claude Code tops the menu
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("Claude Code");
  await expect(page.getByTestId("composer")).toBeEnabled();
});

test("a terminal agent (Grok) starts in the folder on Start and gets no prompt", async ({ page }) => {
  await open(page, { installed: ["claude", "grok"], recent: [{ agent: "grok", cwd: "/Users/you/code/tui", at: 1 }] });
  await page.getByTestId("session-new").click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent-fixed")).toHaveText("Grok");
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
  await page.keyboard.press("Enter");
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
