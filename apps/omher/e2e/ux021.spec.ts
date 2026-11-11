// omher 0.2.1 usability fixes from the SESSIONS QA (U10–U14), one short test each: the Terminal toggle is an icon
// button, the collapsed Needs-you strip names the newest ask, same-named folders show their parent, a clean exit
// reads "Ended" in grey, and a missing agent's tooltip carries its install line.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "u1", op, ...params }));
  });
  ws.close();
}

async function open(page: Page, installed = ["claude", "codex", "omh"]) {
  await page.addInitScript((agents) => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.pinned");
    localStorage.removeItem("omher.hidden");
    (window as unknown as { __omherMockAgents: string[] }).__omherMockAgents = agents;
  }, installed);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function start(page: Page, agent: string, folder: string) {
  await page.evaluate((f) => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = f), folder);
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("U10: the Terminal toggle is a 24px icon button named Open in Terminal, unlike the model chip", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  const toggle = page.getByTestId("session-terminal-toggle");
  await expect(toggle).toHaveText("");
  await expect(toggle).toHaveAttribute("aria-label", "Open in Terminal");
  await expect(toggle).toHaveAttribute("title", "Open in Terminal");
  await expect(toggle.locator("svg")).toHaveCount(1);
  const box = (await toggle.boundingBox())!;
  expect([box.width, box.height]).toEqual([24, 24]);
  // no fill at rest: the model chip next to it is the filled one
  const bg = (sel: string) => page.getByTestId(sel).evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await bg("session-terminal-toggle")).toBe("rgba(0, 0, 0, 0)");
  expect(await bg("model-pill")).not.toBe("rgba(0, 0, 0, 0)");
  await toggle.click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-label", "Back to the chat");
  await toggle.click();
  await expect(page.getByTestId("session-chat")).toBeVisible();
});

test("U11: the collapsed strip names the newest ask's bot and its first words; expanding and ⌘J are unchanged", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toContainText("updater");
  const strip = page.getByTestId("needs-strip");
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await expect(page.getByTestId("needs-line")).toHaveText("1 needs you · Friren: Allow rm -rf build/?");
  await mock("mock.ask", { bot: "default", kind: "clarify" });
  // the newest ask, cut at 32 characters
  await expect(page.getByTestId("needs-line")).toHaveText("2 need you · Hermes: Which environment should I depl…");
  await expect(page.getByTestId("needs-line")).toHaveAttribute("title", "2 need you · Hermes: Which environment should I depl…");
  // one line: the sidebar cuts it again rather than wrapping
  const line = page.getByTestId("needs-line");
  expect(await line.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
  expect((await strip.boundingBox())!.height).toBe(28);
  await strip.click();
  await expect(page.getByTestId("needs-item")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("needs-list")).toHaveCount(0);
  const key = (await page.evaluate(() => /Mac/.test(navigator.platform))) ? "Meta" : "Control";
  await page.keyboard.press(`${key}+j`);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
});

test("U12: two sessions in folders of the same name show their parent folder; a unique name stays alone", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/work/web-app");
  const rows = page.locator("[data-testid=session-list] .ss-row");
  await expect(rows.first().getByTestId("session-where")).toHaveCount(0);
  await start(page, "codex", "/Users/you/oss/web-app");
  await start(page, "claude", "/Users/you/notes");
  // newest first: notes, oss/web-app, work/web-app
  await expect(rows.nth(0).locator(".bot-n")).toHaveText("notes");
  await expect(rows.nth(0).getByTestId("session-where")).toHaveCount(0);
  await expect(rows.nth(1).locator(".bot-n")).toHaveText("web-app · ~/oss");
  await expect(rows.nth(2).locator(".bot-n")).toHaveText("web-app · ~/work");
  // the parent is muted next to the name
  const [name, where] = await rows.nth(1).locator(".bot-n").evaluate((el) => [getComputedStyle(el).color, getComputedStyle(el.querySelector(".ss-where")!).color]);
  expect(where).not.toBe(name);
});

test("U13: an agent that exits with code 0 reads Ended in grey, never Failed", async ({ page }) => {
  await open(page);
  await start(page, "claude", "/Users/you/code/web-app");
  await page.getByTestId("composer").fill("/exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  const act = page.getByTestId("activity").last();
  await expect(act).toHaveAttribute("data-state", "ended");
  await expect(act.getByTestId("activity-text")).toHaveText(/^Ended after \d+s$/);
  await expect(page.getByTestId("timeline")).not.toContainText("Failed");
  // grey, not the danger red
  const [r, g, b] = rgb(await act.locator(".act-ic").evaluate((el) => getComputedStyle(el).color));
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(30);
  expect(rgb(await page.getByTestId("session-status").evaluate((el) => getComputedStyle(el).color))).not.toEqual(rgb("rgb(240, 138, 138)"));
});

test("U14: a missing agent's Not installed tooltip carries its install line, as text only", async ({ page }) => {
  await open(page, ["claude"]);
  await page.getByTestId("session-new").click();
  const lines: Record<string, string> = {
    codex: "npm i -g @openai/codex",
    omo: "npm i -g omo-ai",
    dsh: "npm i -g @deepseek-ai/dsh",
    pi: "npm i -g @mariozechner/pi-coding-agent",
    omp: "npm i -g @oh-my-pi/pi-coding-agent",
    grok: "see grok docs",
  };
  for (const [agent, line] of Object.entries(lines)) {
    const row = page.getByTestId(`session-agent-${agent}`);
    await expect(row).toHaveAttribute("aria-disabled", "true");
    await expect(row).toContainText("Not installed");
    const program = agent === "dsh" ? "DeepSeek Harness \\(dsh\\)" : agent;
    await expect(row).toHaveAttribute("title", new RegExp(`${program} was not found on this computer · .*${line.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")}`));
  }
  // an installed agent keeps its path as the tooltip
  await expect(page.getByTestId("session-agent-claude")).toHaveAttribute("title", "/usr/local/bin/claude");
  expect((await page.evaluate(() => (window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? [])).filter((c) => c.op === "start")).toHaveLength(0);
});
