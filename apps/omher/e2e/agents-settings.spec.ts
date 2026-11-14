// Settings › Agents (mock host): the built-ins listed read-only by tier in four languages; Add agent -> Save opens a
// confirm card with the exact command and nothing is written until Add; Cancel writes nothing; the new agent appears
// in the SESSIONS + menu after the generic ACP agents and opens a session chat (the mock speaks what the generic ACP
// adapter emits), whose view says once that approvals follow the agent's own settings; Remove asks once, then ends
// its open session. Shots with OMHER_SHOTS=<dir> (OMHER_SHOT_TAG=after by default).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, args: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...args }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Call = { op: string; agent?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const file = (page: Page) => page.evaluate(() => (window as unknown as { __omherCustomFile?: unknown[] }).__omherCustomFile ?? null);

async function open(page: Page, opts: { theme?: string; lang?: string; file?: unknown[] } = {}) {
  await page.addInitScript(
    ([t, l, f]) => {
      localStorage.setItem("omher.theme", t as string);
      if (l) localStorage.setItem("omher.lang", l as string);
      localStorage.removeItem("omher.sessions.recent");
      const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[]; __omherCustomFile?: unknown[] };
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "omh", "opencode", "gemini"];
      if (f) w.__omherCustomFile = f as unknown[];
    },
    [opts.theme ?? "dark", opts.lang ?? "", opts.file ?? null] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function agentsPage(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await expect(page.getByTestId("agents-page")).toBeVisible();
  await expect(page.getByTestId("agents-row-cline")).toBeVisible();
}

async function fill(page: Page, label: string, program: string, args = "acp") {
  await page.getByTestId("agents-add").click();
  await page.getByTestId("agent-form-label").fill(label);
  await page.getByTestId("agent-form-program").fill(program);
  await page.getByTestId("agent-form-args").fill(args);
}

async function plus(page: Page) {
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

test("the page lists every offered agent read-only with its tier and whether it is installed", async ({ page }) => {
  await open(page);
  await agentsPage(page);
  const rows = page.locator("[data-testid=agents-builtins] [data-testid^=agents-row-]");
  await expect(rows).toHaveCount(14);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.slice("agents-row-".length)))).toEqual([
    "claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "qwen", "kimi", "copilot", "cline",
  ]);
  await expect(page.getByTestId("agents-tier-claude")).toHaveText("Main");
  await expect(page.getByTestId("agents-tier-dsh")).toHaveText("Built-in");
  await expect(page.getByTestId("agents-tier-gemini")).toHaveText("ACP");
  await expect(page.getByTestId("agents-row-gemini")).toContainText("Installed");
  await expect(page.getByTestId("agents-row-qwen")).toContainText("Not installed");
  // nothing on the built-in rows can be changed
  await expect(page.locator("[data-testid=agents-builtins] button, [data-testid=agents-builtins] input")).toHaveCount(0);
  await expect(page.getByTestId("agents-mine")).toContainText("No agents of your own yet");
  // the page sits between Terminal and Providers
  const names = await page.locator(".st-nav button").allTextContents();
  expect(names.indexOf("Agents")).toBe(names.indexOf("Terminal") + 1);
  expect(names.indexOf("Providers")).toBe(names.indexOf("Agents") + 1);
});

test("Save opens the confirm card with the exact command; Cancel writes nothing", async ({ page }) => {
  await open(page);
  await agentsPage(page);
  await fill(page, "Cursor Agent", "cursor-agent");
  await expect(page.getByTestId("agent-form-nokeys")).toHaveText("No keys, tokens or environment variables here: the agent signs in on its own.");
  await expect(page.getByTestId("agent-form-args")).toHaveValue("acp");
  await page.getByTestId("agent-form-save").click();
  const card = page.getByTestId("agent-confirm");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("/opt/homebrew/bin/cursor-agent acp");
  await expect(card).toContainText("In the folder you pick for each session.");
  // Cancel comes first, Add second
  expect(await card.locator("button").allTextContents()).toEqual(["Cancel", "Add"]);
  expect(await file(page)).toBeNull();
  await page.getByTestId("agent-confirm-cancel").click();
  await expect(card).toHaveCount(0);
  expect(await file(page)).toBeNull();
  expect((await calls(page)).filter((c) => c.op === "custom.confirm")).toEqual([]);
  // a program that is not on the search path: the card shows it as typed with every argument, and says it is missing
  await page.getByTestId("agent-form-program").fill("not-here");
  await page.getByTestId("agent-form-args").fill("--unshown");
  await page.getByTestId("agent-form-save").click();
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("not-here --unshown");
  await expect(page.getByTestId("agent-confirm-missing")).toHaveText("not-here: not found on the search path");
  await page.getByTestId("agent-confirm-cancel").click();
  // OpenCode and Kilo Code are refused with one line, no card
  for (const [program, line] of [["opencode", "Use the built-in OpenCode."], ["kilo", "Kilo Code is not offered."], ["cursor-agent; rm -rf ~", "Give a program name on your search path or a full path, with no shell characters."]]) {
    await page.getByTestId("agent-form-program").fill(program);
    await page.getByTestId("agent-form-save").click();
    await expect(page.getByTestId("agents-error")).toHaveText(line);
    await expect(page.getByTestId("agent-confirm")).toHaveCount(0);
  }
  expect(await file(page)).toBeNull();
});

test("Add writes it; it appears in the + menu after the generic ACP agents and opens a session chat; Remove ends it", async ({ page }) => {
  await open(page);
  await agentsPage(page);
  await fill(page, "Stub ACP", "stub-acp");
  await page.getByTestId("agent-form-save").click();
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("/usr/local/bin/stub-acp acp");
  await page.getByTestId("agent-confirm-add").click();
  await expect(page.getByTestId("agent-confirm")).toHaveCount(0);
  expect(await file(page)).toEqual([{ id: "stub-acp", label: "Stub ACP", program: "stub-acp", args: ["acp"], install: "" }]);
  await expect(page.getByTestId("agents-mine-stub-acp")).toContainText("/usr/local/bin/stub-acp acp");

  // the + menu: installed, after Gemini CLI (the generic ACP tier)
  await page.getByRole("button", { name: "Close settings" }).click();
  await plus(page);
  const items = await page.locator("[data-testid=session-menu-list] > [data-testid^=session-agent-]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(items.indexOf("session-agent-stub-acp")).toBe(items.indexOf("session-agent-gemini") + 1);
  await page.getByTestId("session-agent-stub-acp").click();
  await expect(page.getByTestId("session-agent-fixed")).toContainText("Stub ACP");
  await expect(page.getByTestId("session-own-approvals")).toHaveText("Approvals follow this agent's own settings");
  await page.getByTestId("composer").fill("hello");
  await page.getByTestId("composer").press("Enter");
  await expect(page.locator("[data-testid=timeline]")).toContainText("(mock Stub ACP) You said: hello", { timeout: 10_000 });
  expect((await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "stub-acp" });
  // said once in the session view
  await expect(page.getByTestId("session-own-approvals")).toHaveCount(1);
  const session = await page.evaluate(() => document.querySelector("[data-testid=session-chat]")?.getAttribute("data-pane"));

  // remove: one confirm, then gone; its open session ends cleanly
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await page.getByTestId("agents-remove-stub-acp").click();
  await expect(page.getByTestId("agents-remove-confirm")).toContainText("Remove Stub ACP? Its open sessions end.");
  await page.getByTestId("agents-remove-yes").click();
  await expect(page.getByTestId("agents-mine-stub-acp")).toHaveCount(0);
  expect(await file(page)).toEqual([]);
  expect((await calls(page)).some((c) => c.op === "chat.close")).toBe(true);
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.locator(`[data-testid="session-${session!.slice("agent:".length)}"] .ss-open`).click();
  await expect(page.locator(`[data-pane="${session}"]`).getByTestId("session-ended")).toBeVisible();
  await plus(page);
  await expect(page.getByTestId("session-agent-stub-acp")).toHaveCount(0);
});

test("a broken entry of the file is listed as broken, never offered, and can be removed", async ({ page }) => {
  await open(page, { file: [{ id: "evil", label: "Evil", program: "sh", args: ["-c", "rm -rf ~"], install: "" }, { id: "cursor", label: "Cursor", program: "cursor-agent", args: ["acp"], install: "" }] });
  await agentsPage(page);
  await expect(page.getByTestId("agents-broken-evil")).toContainText("evil cannot run");
  await expect(page.getByTestId("agents-mine-cursor")).toBeVisible();
  await page.getByRole("button", { name: "Close settings" }).click();
  await plus(page);
  await expect(page.getByTestId("session-agent-evil")).toHaveCount(0);
  await expect(page.getByTestId("session-agent-cursor")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await page.getByTestId("agents-remove-evil").click();
  await page.getByTestId("agents-remove-yes").click();
  await expect(page.getByTestId("agents-broken-evil")).toHaveCount(0);
  expect(await file(page)).toEqual([{ id: "cursor", label: "Cursor", program: "cursor-agent", args: ["acp"], install: "" }]);
});

for (const [lang, title, main, add, card] of [
  ["en", "Agents", "Main", "Add agent", "Add Cursor?"],
  ["ko", "에이전트", "메인", "에이전트 추가", "Cursor을(를) 추가할까요?"],
  ["ja", "エージェント", "メイン", "エージェントを追加", "Cursor を追加しますか？"],
  ["zh", "智能体", "主要", "添加智能体", "添加 Cursor？"],
] as const) {
  test(`the page and its card read in ${lang}`, async ({ page }) => {
    await open(page, { lang });
    await page.getByTestId("nav-settings").click();
    await expect(page.getByTestId("settings-nav-agents")).toHaveText(title);
    await page.getByTestId("settings-nav-agents").click();
    await expect(page.getByTestId("agents-tier-claude")).toHaveText(main);
    await expect(page.getByTestId("agents-add")).toHaveText(add);
    await fill(page, "Cursor", "cursor-agent");
    await page.getByTestId("agent-form-save").click();
    await expect(page.getByTestId("agent-confirm")).toContainText(card);
    await expect(page.getByTestId("agent-confirm-command")).toHaveText("/opt/homebrew/bin/cursor-agent acp");
  });
}

// ---- shots --------------------------------------------------------------------------------------

const FILE = [{ id: "cursor-agent", label: "Cursor Agent", program: "cursor-agent", args: ["acp"], install: "" }];

for (const theme of ["dark", "light"]) {
  test(`shots: Settings › Agents, the confirm card and the + menu (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
    await mock("bots.rename", { bot: "default", name: "Milo" });
    await page.setViewportSize({ width: 1280, height: 820 });
    await open(page, { theme, file: FILE });
    mkdirSync(SHOTS, { recursive: true });
    await agentsPage(page);
    await expect(page.getByTestId("agents-mine-cursor-agent")).toBeVisible();
    // the end of the page: the last built-in rows, Your agents and Add agent
    await page.getByTestId("agents-add").scrollIntoViewIfNeeded();
    await page.mouse.move(1200, 780);
    await page.screenshot({ path: join(SHOTS, `agents-settings-${TAG}-${theme}.png`), animations: "disabled" });
    await fill(page, "Stub ACP", "stub-acp");
    await page.getByTestId("agent-form-save").click();
    await expect(page.getByTestId("agent-confirm")).toBeVisible();
    await page.getByTestId("agent-confirm").locator("b").first().click();
    await page.screenshot({ path: join(SHOTS, `agents-confirm-${TAG}-${theme}.png`), animations: "disabled" });
    await page.getByTestId("agent-confirm-cancel").click();
    await page.getByRole("button", { name: "Close settings" }).click();
    await plus(page);
    await page.mouse.move(900, 400);
    await page.screenshot({ path: join(SHOTS, `agents-menu-custom-${TAG}-${theme}.png`), animations: "disabled" });
  });
}
