// The update confirm and picking up where you left off after a restart. No Tauri here: `__omherUpdateHost`
// stands in for the updater (as in update.spec.ts), and a reload stands in for omher restarting (the page loads
// again with the same storage, and the mock session host starts empty, as the shell does after a restart).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

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

type Call = { op: string; agent?: string; cwd?: string; resume?: string; account?: string };
const sessionCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const updCalls = (page: Page) => page.evaluate(() => (window as unknown as { __updCalls: string[] }).__updCalls);

/** The updater stand-in (announces 0.2.3; install waits for `__updGo()`) and the folder the picker returns. */
async function setup(page: Page, folders: string[] = []) {
  await page.addInitScript((folders: string[]) => {
    const w = window as unknown as Record<string, unknown>;
    const calls: string[] = [];
    w.__updCalls = calls;
    let go: () => void = () => {};
    const gate = new Promise<void>((r) => (go = r));
    w.__updGo = () => go();
    w.__omherUpdateHost = {
      check: async () => {
        calls.push("check");
        return {
          version: "0.2.3",
          install: async (onProgress: (p: { done: number; total: number | null }) => void) => {
            calls.push("install");
            onProgress({ done: 300, total: 1000 });
            await gate;
          },
        };
      },
      relaunch: async () => {
        calls.push("relaunch");
      },
    };
    w.__omherMockAgents = ["claude", "codex", "omh", "pi", "grok"];
    // the next folder the native picker "returns" (one per session started)
    const queue = [...folders];
    Object.defineProperty(w, "__omherPickFolder", { configurable: true, get: () => queue.shift() ?? "/Users/you/code/x" });
    if (!sessionStorage.getItem("__kept")) {
      sessionStorage.setItem("__kept", "1");
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.resume");
    }
  }, folders);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A New session chat on `agent` in the picker's next folder, started: a chat agent by its first message
 *  (`first`), Grok by Start. */
async function start(page: Page, agent: string, first = "/status") {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-pick").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  if (agent === "grok") await page.getByTestId("session-go").click();
  else {
    await page.getByTestId("composer").fill(first);
    await page.keyboard.press("Enter");
  }
  await expect(page.getByTestId("session-chat").or(page.getByTestId("terminal"))).not.toHaveAttribute("data-draft", "true");
}

/** Wait for the debounced snapshot to land. */
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of ["dark", "light"] as const) {
  test.describe(theme, () => {
    test.use({ colorScheme: theme });
    test(`update asks first: Cancel keeps the app as it is, the confirm installs (${theme})`, async ({ page }) => {
      await setup(page, ["/Users/you/code/web-app", "/Users/you/code/api"]);
      await start(page, "claude");
      await expect(page.getByTestId("session-status")).toHaveText("Ready");
      await start(page, "codex");
      await expect(page.getByTestId("session-status")).toHaveText("Ready");
      await page.getByTestId("bot-kami").click();
      await page.getByTestId("composer").fill("draft before the update");

      const btn = page.getByTestId("update-btn");
      await expect(btn).toHaveText("Update to 0.2.3");
      if (SHOTS && theme === "dark") {
        mkdirSync(SHOTS, { recursive: true });
        await page.mouse.move(700, 400);
        await page.waitForTimeout(300);
        await page.screenshot({ path: join(SHOTS, "update-resume-before.png"), animations: "disabled" });
      }
      await btn.click();
      const dlg = page.getByTestId("update-confirm");
      await expect(dlg).toBeVisible();
      await expect(dlg.getByRole("heading")).toHaveText("Update to 0.2.3?");
      await expect(dlg).toContainText("omher will restart. Your chats, panels and sessions pick up where you left off.");
      // each "folder (Agent)" is kept on one line (no-break spaces)
      expect((await page.getByTestId("update-running").textContent())!.replace(/\u00a0/g, " ")).toBe(
        "2 sessions running: api (Codex), web-app (Claude Code). They resume after the restart.",
      );
      await expect(dlg).toHaveAttribute("aria-modal", "true");
      // keyboard: the primary has the focus, Tab stays inside, Esc closes and gives the focus back
      await expect(page.getByTestId("update-go")).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByTestId("update-cancel")).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByTestId("update-go")).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      await expect(page.getByTestId("update-cancel")).toBeFocused();
      const box = (await dlg.boundingBox())!;
      expect(box.width).toBeLessThanOrEqual(380);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await dlg.getByRole("heading").click();
        await page.screenshot({ path: join(SHOTS, `update-confirm-${theme}.png`), animations: "disabled" });
      }
      await page.keyboard.press("Escape");
      await expect(dlg).toHaveCount(0);
      await expect(btn).toBeFocused();
      expect(await updCalls(page)).toEqual(["check"]);

      // Cancel: nothing installs, the app is as it was
      await btn.click();
      await page.getByTestId("update-cancel").click();
      await expect(dlg).toHaveCount(0);
      expect(await updCalls(page)).toEqual(["check"]);
      await expect(btn).toHaveText("Update to 0.2.3");
      await expect(page.getByTestId("composer")).toHaveValue("draft before the update");
      expect((await sessionCalls(page)).filter((c) => c.op === "chat.close")).toEqual([]);

      // a click on the dimmed app closes it too; Enter on the primary installs
      await btn.click();
      await page.mouse.click(5, 5);
      await expect(dlg).toHaveCount(0);
      await btn.click();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("update-progress")).toHaveText("Updating 30%");
      expect(await updCalls(page)).toEqual(["check", "install"]);
      await page.evaluate(() => (window as unknown as { __updGo: () => void }).__updGo());
      await expect.poll(() => updCalls(page)).toEqual(["check", "install", "relaunch"]);
      // right before the restart the snapshot holds what was open
      const snap = await saved(page);
      expect(snap).toMatchObject({ v: 1, bot: "kami", drafts: { kami: "draft before the update" } });
      expect(snap.sessions.map((s: Call & { running: boolean }) => [s.agent, s.running])).toEqual([
        ["codex", true],
        ["claude", true],
      ]);
    });
  });
}

test.use({ colorScheme: "dark" });

test("no session running: the confirm has no sessions line", async ({ page }) => {
  await setup(page);
  await page.getByTestId("update-btn").click();
  await expect(page.getByTestId("update-confirm")).toBeVisible();
  await expect(page.getByTestId("update-running")).toHaveCount(0);
});

test("after a restart: the bot, its draft and the open panel come back", async ({ page }) => {
  await setup(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("composer").fill("unsent line\nand a second");
  await page.getByTestId("who").click();
  await page.getByTestId("panel-tab-schedule").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  // another bot's draft is kept too
  await page.getByTestId("bot-kami").click();
  await page.getByTestId("composer").fill("kami note");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("composer")).toHaveValue("unsent line\nand a second");
  await expect.poll(async () => (await saved(page))?.drafts).toEqual({ friren: "unsent line\nand a second", kami: "kami note" });

  await page.reload();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("composer")).toHaveValue("unsent line\nand a second");
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("panel-tab-schedule")).toHaveAttribute("aria-selected", "true");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("composer")).toHaveValue("kami note");
});

test("a saved bot that is gone, or a bad snapshot, opens the app as a fresh start", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("__step") === "2") localStorage.setItem("omher.resume", "{not json");
    else
      localStorage.setItem(
        "omher.resume",
        JSON.stringify({ v: 1, at: 1, bot: "ghost", view: "chat", session: null, panelOpen: true, panelTab: "runs", runsFull: true, runId: null, drafts: { ghost: "x" }, sessions: [] }),
      );
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("runs-full")).toHaveCount(0);
  await page.evaluate(() => sessionStorage.setItem("__step", "2"));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("composer")).toHaveValue("");
});

test("after a restart: Claude Code and Codex continue by themselves, pi waits for Resume, an ended one stays ended", async ({ page }) => {
  await setup(page, ["/Users/you/code/web-app", "/Users/you/code/api", "/Users/you/code/pi-work", "/Users/you/code/old"]);
  await start(page, "claude", "hello before");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("You said: hello before");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await start(page, "codex");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await start(page, "pi");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await start(page, "codex");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").fill("/exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  // a draft in a session chat, and the Claude Code session open
  await page.locator("[data-testid=session-list] .ss-row").filter({ hasText: "web-app" }).locator(".ss-open").click();
  await page.getByTestId("composer").fill("next step, not sent");
  const before = (await sessionCalls(page)).filter((c) => c.op === "chat.start");
  const claudeId = before.find((c) => c.agent === "claude")!.resume;
  expect(claudeId).toBeUndefined();
  await expect.poll(async () => (await saved(page))?.sessions?.length).toBe(4);
  if (SHOTS) {
    await page.mouse.move(700, 400);
    await page.waitForTimeout(300);
  }

  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  // the session keeps its name (a summary of its first message) and its agent and folder across the restart
  await expect(page.getByTestId("session-title")).toHaveText("hello before");
  await expect(page.getByTestId("session-agent")).toHaveText("Claude Code");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/web-app");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("composer")).toHaveValue("next step, not sent");
  // the chat shows what was said before the restart
  await expect(page.getByTestId("bubble-user").first()).toHaveText("hello before");

  const rows = page.locator("[data-testid=session-list] .ss-row");
  await expect(rows).toHaveCount(4);
  const calls = (await sessionCalls(page)).filter((c) => c.op === "chat.start");
  // exactly the two that continue by themselves, each once, in its own folder, continuing its conversation
  expect(calls.map((c) => [c.agent, c.cwd])).toEqual(
    expect.arrayContaining([
      ["claude", "/Users/you/code/web-app"],
      ["codex", "/Users/you/code/api"],
    ]),
  );
  expect(calls).toHaveLength(2);
  expect(calls.find((c) => c.agent === "claude")!.resume).toBe("11111111-2222-4333-8444-555555555555");
  expect(calls.find((c) => c.agent === "codex")!.resume).toMatch(/^codex-mock-/);

  const pi = rows.filter({ hasText: "pi-work" });
  await expect(pi.getByTestId("session-sub")).toHaveText("pi · Paused");
  const old = rows.filter({ hasText: "old" });
  await expect(old.getByTestId("session-sub")).toHaveText("Codex · Ended");
  if (SHOTS) {
    await page.mouse.move(700, 400);
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, "update-resume-after.png"), animations: "disabled" });
  }

  // pi: one click starts it again in the same folder, once
  await pi.locator(".ss-open").click();
  await expect(page.getByTestId("session-status")).toHaveText("Paused");
  await expect(page.getByTestId("session-paused")).toContainText("Paused when omher restarted");
  await page.getByTestId("session-resume").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-paused")).toHaveCount(0);
  const piStarts = (await sessionCalls(page)).filter((c) => c.op === "chat.start" && c.agent === "pi");
  expect(piStarts).toEqual([expect.objectContaining({ cwd: "/Users/you/code/pi-work" })]);

  // the ended one still offers its usual Restart, and nothing started it
  await old.locator(".ss-open").click();
  await expect(page.getByTestId("session-ended")).toBeVisible();
  expect((await sessionCalls(page)).filter((c) => c.op === "chat.start")).toHaveLength(3);
});

test("a terminal session that was running comes back paused and starts only on Resume", async ({ page }) => {
  await setup(page, ["/Users/you/code/g"]);
  await start(page, "grok");
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await expect.poll(async () => (await saved(page))?.sessions?.[0]?.running).toBe(true);
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await expect(page.getByTestId("session-agent")).toHaveText("Grok");
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  expect((await sessionCalls(page)).filter((c) => c.op === "start")).toEqual([]);
  await page.getByTestId("session-resume").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect((await sessionCalls(page)).filter((c) => c.op === "start")).toEqual([expect.objectContaining({ agent: "grok", cwd: "/Users/you/code/g" })]);
});

test("a New session chat that never started comes back as a draft after a restart, and nothing starts", async ({ page }) => {
  await setup(page, ["/Users/you/code/web-app"]);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-pick").click();
  await page.getByTestId("session-agent-codex").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("session-folder")).toHaveText("web-app");
  await page.getByTestId("composer").fill("half a thought");
  await expect.poll(async () => (await saved(page))?.sessions?.[0]).toMatchObject({ agent: "codex", cwd: "/Users/you/code/web-app", draft: true, running: false });

  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-agent-pick")).toHaveText("Codex");
  await expect(page.getByTestId("session-folder")).toHaveText("web-app");
  await expect(page.getByTestId("composer")).toHaveValue("half a thought");
  await expect(page.locator("[data-testid=session-list] .ss-row .bot-n")).toHaveText(["New session"]);
  await page.waitForTimeout(200);
  expect((await sessionCalls(page)).filter((c) => c.op !== "reset")).toEqual([]);
  // the update confirm does not count it as running
  await page.getByTestId("update-btn").click();
  await expect(page.getByTestId("update-running")).toHaveCount(0);
  await page.keyboard.press("Escape");
  // it is still a draft: the first message starts it there, with that text
  await page.getByTestId("composer").press("Enter");
  await expect.poll(async () => (await sessionCalls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "codex", cwd: "/Users/you/code/web-app" });
  await expect(page.getByTestId("bubble-user")).toHaveText("half a thought");
});
