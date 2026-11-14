// A bot drafts an agent, the person confirms it (mock bridge + mock host): a bot reply with an ```omher-agent block
// keeps its code block and gets one "Add agent" chip; the chip opens Settings › Agents' own confirm card, filled from
// the draft, checked again and naming the bot; Add writes it and it appears in the SESSIONS + menu; Cancel writes
// nothing; a refused draft's chip is disabled with the reason; a SESSIONS agent's reply with a draft shows no chip;
// "Ask the bot" fills the composer and sends nothing. Shots with OMHER_SHOTS=<dir> (OMHER_SHOT_TAG=after by default).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, args: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "bc1") res(msg);
    };
    ws.send(JSON.stringify({ id: "bc1", op, ...args }));
  });
  ws.close();
  return reply.result;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Call = { op: string; agent?: string; path?: string };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const file = (page: Page) => page.evaluate(() => (window as unknown as { __omherCustomFile?: unknown[] }).__omherCustomFile ?? null);

const fence = (o: unknown) => "```omher-agent\n" + JSON.stringify(o) + "\n```";
const STUB = { name: "Stub ACP", program: "stub-acp", args: ["acp"], install: "npm install -g stub-acp", note: "unknown keys are ignored" };

async function open(page: Page, theme = "dark") {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "opencode", "gemini"];
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

/** Kami answers with `text` in its main chat. */
async function reply(text: string, id = "bc-draft") {
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id, text }] });
}

async function plus(page: Page) {
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

test("a bot reply with a draft: chip -> the same card, filled and naming the bot -> Add -> the agent is in the + menu", async ({ page }) => {
  await open(page);
  await reply(`Here is the agent you asked for:\n\n${fence(STUB)}\n\nPress Add agent to see the exact command.`);
  const bubble = page.getByTestId("bubble-bot").last();
  // the block still renders as code, and one chip sits under the reply
  await expect(bubble.locator("pre")).toContainText('"program":"stub-acp"');
  const chip = bubble.getByTestId("agent-chip");
  await expect(chip).toHaveCount(1);
  await expect(chip).toContainText("Add agent");
  await expect(chip).toContainText("Stub ACP");
  await expect(chip).toBeEnabled();
  expect(await file(page)).toBeNull();

  await chip.click();
  const card = page.getByTestId("agent-confirm");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Add Stub ACP?");
  await expect(page.getByTestId("agent-confirm-by")).toHaveText("Proposed by Kami");
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("/usr/local/bin/stub-acp acp");
  expect(await card.locator("button").allTextContents()).toEqual(["Cancel", "Add"]);
  // the shell checked the draft again (the bot's stricter preview); nothing written yet
  expect((await calls(page)).filter((c) => c.op === "custom.botPreview")).toHaveLength(1);
  expect(await file(page)).toBeNull();

  await page.getByTestId("agent-confirm-add").click();
  await expect(card).toHaveCount(0);
  expect(await file(page)).toEqual([{ id: "stub-acp", label: "Stub ACP", program: "stub-acp", args: ["acp"], install: "npm install -g stub-acp" }]);
  await expect(chip).toContainText("Added");
  await expect(chip).toBeDisabled();
  await plus(page);
  const items = await page.locator("[data-testid=session-menu-list] > [data-testid^=session-agent-]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(items.indexOf("session-agent-stub-acp")).toBe(items.indexOf("session-agent-gemini") + 1);
});

test("a draft whose program is not installed yet: the card still shows every argument, and says it is missing", async ({ page }) => {
  await open(page);
  await reply(`Try this:\n\n${fence({ name: "X", program: "not-here", args: ["--unshown"] })}`, "bc-missing");
  await page.getByTestId("bubble-bot").last().getByTestId("agent-chip").click();
  await expect(page.getByTestId("agent-confirm")).toBeVisible();
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("not-here --unshown");
  await expect(page.getByTestId("agent-confirm-missing")).toHaveText("not-here: not found on the search path");
  await page.getByTestId("agent-confirm-cancel").click();
  expect(await file(page)).toBeNull();
});

test("Cancel writes nothing; two blocks make two chips; a refused draft's chip is disabled with its reason", async ({ page }) => {
  await open(page);
  await reply(
    [
      "Two options:",
      fence({ name: "Cursor Agent", program: "cursor-agent", args: ["acp"] }),
      fence({ name: "Stub ACP", program: "stub-acp", args: ["acp"] }),
      "and these I should not have proposed:",
      fence({ name: "Shell", program: "/bin/bash", args: ["-c", "id"] }),
      fence({ name: "Open", program: "opencode", args: ["acp"] }),
      fence({ name: "Meta", program: "stub-acp", args: ["acp; rm -rf ~"] }),
      "```omher-agent\n{not json}\n```",
    ].join("\n\n"),
  );
  const chips = page.getByTestId("bubble-bot").last().getByTestId("agent-chip");
  await expect(chips).toHaveCount(6);
  await expect(chips.nth(0)).toBeEnabled();
  await expect(chips.nth(1)).toBeEnabled();
  for (const [i, why] of [
    [2, "A bot may not propose a shell or an interpreter as the program."],
    [3, "Use the built-in OpenCode."],
    [4, "Up to 8 arguments of letters, digits and . _ = / : -, with no shell characters."],
    [5, "The draft is not one JSON object."],
  ] as const) {
    await expect(chips.nth(i)).toBeDisabled();
    await expect(chips.nth(i)).toHaveAttribute("title", why);
  }
  await chips.nth(0).click();
  await expect(page.getByTestId("agent-confirm-command")).toHaveText("/opt/homebrew/bin/cursor-agent acp");
  await page.getByTestId("agent-confirm-cancel").click();
  await expect(page.getByTestId("agent-confirm")).toHaveCount(0);
  // Escape and a click outside close it too; none of them wrote
  await chips.nth(1).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("agent-confirm")).toHaveCount(0);
  expect(await file(page)).toBeNull();
  expect((await calls(page)).filter((c) => c.op === "custom.confirm")).toEqual([]);
});

test("a SESSIONS agent's reply with a draft shows no chip", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/draft");
  await page.keyboard.press("Enter");
  const chat = page.getByTestId("session-chat");
  await expect(chat.locator("pre")).toContainText('"program": "stub-acp"', { timeout: 10_000 });
  await expect(chat.getByTestId("agent-chip")).toHaveCount(0);
  await expect(page.getByTestId("agent-chip")).toHaveCount(0);
});

test("Ask the bot fills the current bot's composer and sends nothing", async ({ page }) => {
  await open(page);
  const before = (await mock("mock.submits")).submits.length;
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-agents").click();
  await expect(page.getByTestId("agents-ask-bot")).toHaveText("Ask the bot");
  await page.getByTestId("agents-ask-bot").click();
  // back in the chat, the request is in the composer, focused, not sent
  await expect(page.getByTestId("settings")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveValue(/^Add an ACP coding agent to omher SESSIONS for me \(reply with one omher-agent block/);
  await expect(page.getByTestId("composer")).toBeFocused();
  await page.waitForTimeout(300);
  expect((await mock("mock.submits")).submits.length).toBe(before);
});

// ---- shots --------------------------------------------------------------------------------------

for (const theme of ["dark", "light"]) {
  test(`shots: a bot's draft chip and its confirm card (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "set OMHER_SHOTS to take the shots");
    await mock("bots.rename", { bot: "kami", name: "Milo" });
    await page.setViewportSize({ width: 1280, height: 820 });
    await open(page, theme);
    mkdirSync(SHOTS, { recursive: true });
    await reply(`Cursor's agent speaks ACP. This is what I would add:\n\n${fence({ name: "Cursor Agent", program: "cursor-agent", args: ["acp"], install: "npm install -g @cursor/agent" })}\n\nPress Add agent to check the exact command first.`);
    const chip = page.getByTestId("bubble-bot").last().getByTestId("agent-chip");
    await expect(chip).toBeVisible();
    await chip.scrollIntoViewIfNeeded();
    await page.mouse.move(1200, 120);
    await page.screenshot({ path: join(SHOTS, `agents-botchip-${TAG}-${theme}.png`), animations: "disabled" });
    await chip.click();
    await expect(page.getByTestId("agent-confirm")).toBeVisible();
    await page.getByTestId("agent-confirm").locator("b").first().click();
    await page.screenshot({ path: join(SHOTS, `agents-botcard-${TAG}-${theme}.png`), animations: "disabled" });
  });
}
