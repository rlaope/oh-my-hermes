// What a session row says about a session the person is not looking at, and the notification that goes with it:
// amber when it waits for them (its terminal rang its bell or sent an OSC 9 message; an open ask), red when it
// stopped on an error, green when it finished. On the mock host: its terminal takes `after <ms> bell|osc9|progress`
// and `after <ms> exit [code]`.
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

type Note = { title: string; body: string };
const notes = (page: Page) =>
  page.evaluate(() => (window as unknown as { __notes: Note[] }).__notes.map((n) => ({ title: n.title, body: n.body })));

async function open(page: Page) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.sessions.open");
    localStorage.removeItem("omher.resume");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[]; __notes: unknown[]; Notification: unknown };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "opencode"];
    // record system notifications instead of showing them
    w.__notes = [];
    class FakeNotification {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string } = {}) {
        w.__notes.push({ title, body: opts.body, n: this });
      }
      close() {}
    }
    w.Notification = FakeNotification;
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const folder = (page: Page, path: string) => page.evaluate((v) => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = v), path);

/** A session of `agent` opened as its terminal, in the picker's folder. */
async function terminal(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

/** Type a line at the shown terminal's prompt. */
async function type(page: Page, line: string) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(line);
  await page.keyboard.press("Enter");
}

const row = (page: Page, name: string) => page.locator("[data-testid=session-list] .ss-row").filter({ hasText: name });
const elsewhere = (page: Page) => page.getByTestId("bot-kami").click();

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a terminal that rings while you are elsewhere turns its row amber and notifies once; opening it clears that", async ({ page }) => {
  await open(page);
  await terminal(page, "claude");
  const r = row(page, "web-app");
  const mark = r.getByTestId("session-mark");

  // while you watch it, a ring is just a ring
  await type(page, "after 200 bell");
  await page.waitForTimeout(900);
  await expect(mark).toHaveCount(0);
  expect(await notes(page)).toEqual([]);

  // a progress report (OSC 9;4) is not a ring, wherever you are
  await type(page, "after 1500 progress");
  await elsewhere(page);
  await page.waitForTimeout(2300);
  await expect(mark).toHaveCount(0);
  expect(await notes(page)).toEqual([]);

  // the bell, from elsewhere
  await r.locator(".ss-open").click();
  await type(page, "after 1500 bell");
  await elsewhere(page);
  await expect(r).toHaveAttribute("data-mark", "needs", { timeout: 8000 });
  await expect(mark).toHaveAttribute("data-mark", "needs");
  await expect(mark).toHaveAttribute("title", "Rang for your attention");
  await expect(r.getByTestId("bot-time")).toHaveText("waiting");
  await expect(r.getByTestId("session-sub")).toHaveText("Claude Code");
  expect(await notes(page)).toEqual([{ title: "web-app · Claude Code wants your attention", body: "It rang its terminal's bell." }]);
  // the dot sits inside the row, before the view mark, and covers no text
  const fit = await mark.evaluate((el) => {
    const d = el.getBoundingClientRect();
    const sub = el.parentElement!.querySelector("[data-testid=session-sub]")!.getBoundingClientRect();
    const view = el.parentElement!.querySelector("[data-testid=session-view]")!.getBoundingClientRect();
    return { afterSub: d.left >= sub.right - 0.5, beforeView: d.right <= view.left + 0.5, w: d.width };
  });
  expect(fit).toEqual({ afterSub: true, beforeView: true, w: 8 });

  // opening the session sees it
  await r.locator(".ss-open").click();
  await expect(mark).toHaveCount(0);
  await expect(r).not.toHaveAttribute("data-mark", "needs");
  await expect(r.getByTestId("session-sub")).toHaveText("Claude Code");

  // an OSC 9 message counts as a ring too; its text is not shown
  await type(page, "after 1500 osc9");
  await elsewhere(page);
  await expect(r).toHaveAttribute("data-mark", "needs", { timeout: 8000 });
  const all = await notes(page);
  expect(all).toHaveLength(2);
  expect(all[1]).toEqual({ title: "web-app · Claude Code wants your attention", body: "It rang its terminal's bell." });

  // a bot row never carries a session mark
  await expect(page.locator("[data-testid=bot-kami] [data-testid=session-mark]")).toHaveCount(0);
  await expect(page.locator("[data-testid=bot-friren] [data-testid=session-mark]")).toHaveCount(0);
});

test("a terminal session that ends while you are elsewhere: green after a clean exit, red after a failing one, a notification each", async ({ page }) => {
  await open(page);
  await terminal(page, "claude");
  await type(page, "after 1500 exit");
  await folder(page, "/Users/you/code/api-server");
  await terminal(page, "opencode");
  await type(page, "after 1500 exit 3");
  await elsewhere(page);

  const clean = row(page, "web-app");
  const failed = row(page, "api-server");
  await expect(clean).toHaveAttribute("data-mark", "done", { timeout: 8000 });
  await expect(failed).toHaveAttribute("data-mark", "error", { timeout: 8000 });
  await expect(clean.getByTestId("session-sub")).toHaveText("Claude Code · Ended");
  await expect(failed.getByTestId("session-sub")).toHaveText("OpenCode · Ended · exit 3");
  await expect(clean.getByTestId("bot-time")).toHaveText("done");
  await expect(failed.getByTestId("bot-time")).toHaveText("error");
  await expect(clean.getByTestId("session-mark")).toHaveAttribute("title", "Done");
  await expect(failed.getByTestId("session-mark")).toHaveAttribute("title", "Error");
  // a session nothing runs in steps back
  await expect(clean).toHaveClass(/\bover\b/);
  await expect(failed).toHaveClass(/\bover\b/);
  const got = (await notes(page)).sort((a, b) => a.title.localeCompare(b.title));
  expect(got).toEqual([
    { title: "api-server · OpenCode ended", body: "Ended · exit 3" },
    { title: "web-app · Claude Code ended", body: "Its program finished." },
  ]);

  // seeing a finished one clears its green dot; an error stays an error
  await clean.locator(".ss-open").click();
  await expect(clean.getByTestId("session-mark")).toHaveCount(0);
  await expect(clean).toHaveClass(/\bover\b/);
  await failed.locator(".ss-open").click();
  await expect(failed.getByTestId("session-mark")).toHaveAttribute("data-mark", "error");

  // Restart: a running session again, no dot
  await page.getByTestId("session-restart").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await expect(failed.getByTestId("session-mark")).toHaveCount(0);
  await expect(failed).not.toHaveClass(/\bover\b/);
});

test("a chat session: an answer you did not watch turns its row green, a failed turn red, an open ask amber", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await elsewhere(page);
  const r = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(r).toHaveAttribute("data-mark", "done", { timeout: 8000 });
  await expect(r.getByTestId("bot-time")).toHaveText("done");
  await expect(r).not.toHaveClass(/\bover\b/);

  // opened: seen
  await r.locator(".ss-open").click();
  await expect(r.getByTestId("session-mark")).toHaveCount(0);
  await expect(r.getByTestId("bot-time")).not.toHaveText("done");

  // watched to the end: no dot
  await page.getByTestId("composer").fill("hello again");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(r).not.toHaveAttribute("data-mark", /.+/);

  // a turn that fails leaves the row red until the next turn, watched or not
  await page.getByTestId("composer").fill("/signedout");
  await page.keyboard.press("Enter");
  await expect(r).toHaveAttribute("data-mark", "error", { timeout: 8000 });
  await expect(r.getByTestId("bot-time")).toHaveText("error");

  // an open ask is amber, as before, and outranks the red
  await page.getByTestId("composer").fill("/approve");
  await page.keyboard.press("Enter");
  await expect(r).toHaveAttribute("data-mark", "needs", { timeout: 8000 });
  await expect(r.getByTestId("needs")).toBeVisible();
  await expect(r.getByTestId("session-mark")).toHaveCount(0);
});
