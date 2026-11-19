// A bot and a TERMINALS session it holds a link to (mock host): omher keeps the session's status file for the bot to
// read, and a bot's request to type into it shows as a card on its terminal. Nothing is typed unless the person
// presses Allow once on that request's own card; Deny, or no answer, types nothing.
// Shots: OMHER_SHOTS=<dir> -> term-link-bot-card-{dark,light}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const FOLDER = "/home/you/code/web-app";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "tb1") res(msg);
    };
    ws.send(JSON.stringify({ id: "tb1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

async function open(page: Page, theme?: "dark" | "light") {
  await page.addInitScript(
    ([folder, th]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "__omherMockHistory"]) localStorage.removeItem(k);
        sessionStorage.setItem("__kept", "1");
      }
      if (th) localStorage.setItem("omher.theme", th);
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = folder;
      w.__omherMockAgents = ["claude", "codex", "grok", "omh", "pi"];
    },
    [FOLDER, theme ?? ""] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function newTerm(page: Page, agent: string): Promise<string> {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows").last()).toContainText("(mock)");
  return (await page.getByTestId("terminal").getAttribute("data-session"))!;
}

type W = {
  __omherSessions: { linkOf(id: string): string | null; rename(id: string, n: string): void; ptyOf(id: string): number | null; close(id: string): void };
  __omherShareFiles?: Record<string, { title: string; agent: string; cwd: string; state: string; lastLine: string; started: number }>;
  __omherMockInbox?: { id: string; link: string; prompt: string; from: string; session: string }[];
  __omherSessionCalls?: { op: string; id?: number; data?: string }[];
  __omherShellCalls?: { op: string; id?: number; data?: string }[];
  __omherBadge?: number;
};

const linkId = async (page: Page, id: string) => (await page.evaluate((i) => (window as unknown as W).__omherSessions.linkOf(i), id))!.slice(-10);
const files = (page: Page) => page.evaluate(() => (window as unknown as W).__omherShareFiles ?? {});
/** What the page sent to session `id`'s program. */
const writes = (page: Page, id: string) =>
  page.evaluate((i) => {
    const w = window as unknown as W;
    const pty = w.__omherSessions.ptyOf(i);
    // a CLI row runs on the agent host, a Shell row on the login-shell host: what either was sent
    return [...(w.__omherSessionCalls ?? []), ...(w.__omherShellCalls ?? [])].filter((c) => c.op === "write" && c.id === pty).map((c) => c.data ?? "");
  }, id);
/** A bot puts a request in the session's inbox (what the OMH tool writes). */
const ask = (page: Page, link: string, prompt: string, from = "Kami") =>
  page.evaluate(([l, p, f]) => ((window as unknown as W).__omherMockInbox ??= []).push({ id: `${Date.now()}`, link: l!, prompt: p!, from: f!, session: "s-1" }), [link, prompt, from] as const);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a TERMINALS session has a status file with its title, CLI, folder, state and last line, gone when it closes", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  const link = await linkId(page, id);
  await page.evaluate(([i]) => (window as unknown as W).__omherSessions.rename(i!, "checkout build"), [id] as const);
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.type("hello there");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await files(page))[link]?.title).toBe("checkout build");
  const f = (await files(page))[link]!;
  expect(f.agent).toBe("claude");
  expect(f.cwd).toBe(FOLDER);
  expect(["working", "waiting"]).toContain(f.state);
  await expect.poll(async () => (await files(page))[link]?.lastLine).toContain("hello there");
  await page.evaluate(([i]) => (window as unknown as W).__omherSessions.close(i!), [id] as const);
  await expect.poll(async () => Object.keys(await files(page))).not.toContain(link);
});

test("a bot's request shows a card and types nothing until Allow; Deny types nothing", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "shell");
  const link = await linkId(page, id);
  await expect.poll(async () => Object.keys(await files(page))).toContain(link);
  const before = await writes(page, id);
  await ask(page, link, "rm -rf build\nmake");
  const card = page.getByTestId("term-share-card");
  await expect(card).toHaveCount(1);
  await expect(card.locator(".card-title")).toHaveText("Kami wants to type into Shell");
  await expect(card.getByTestId("term-share-prompt")).toHaveText("rm -rf build\nmake");
  await expect(card.locator("button")).toHaveText(["Deny", "Allow once"]);
  // Deny has the focus: a stray Enter is not an Allow
  await expect(card.locator("button").first()).toBeFocused();
  // the row and the Dock count show it waits on the person
  await expect(page.getByTestId(`session-${id}`)).toHaveAttribute("data-term-status", "bell");
  await expect.poll(() => page.evaluate(() => (window as unknown as W).__omherBadge)).toBeGreaterThan(0);
  // several looks later, still nothing typed
  await page.waitForTimeout(3500);
  expect(await writes(page, id)).toEqual(before);
  await card.getByRole("button", { name: "Deny" }).click();
  await expect(card).toHaveCount(0);
  await page.waitForTimeout(2000);
  expect(await writes(page, id)).toEqual(before);
  await expect(page.locator(".xterm-rows").last()).not.toContainText("rm -rf build");
});

test("Allow once types the prompt and Enter once; the next request asks again", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "shell");
  const link = await linkId(page, id);
  await expect.poll(async () => Object.keys(await files(page))).toContain(link);
  const before = (await writes(page, id)).length;
  // a control sequence in the prompt never reaches the program
  await ask(page, link, "echo hi\x1b[2J\x07");
  await page.getByTestId("term-share-card").getByRole("button", { name: "Allow once" }).click();
  await expect.poll(async () => (await writes(page, id)).slice(before)).toEqual(["echo hi[2J\r"]);
  await ask(page, link, "second");
  await expect(page.getByTestId("term-share-card")).toHaveCount(1);
  await page.waitForTimeout(2000);
  expect((await writes(page, id)).slice(before)).toEqual(["echo hi[2J\r"]);
});

test("every request asks: two from Kami are two cards, and the second types nothing until its own Allow", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "shell");
  const la = await linkId(page, a);
  await expect.poll(async () => Object.keys(await files(page))).toContain(la);
  const ours = async () => (await writes(page, a)).filter((d) => d === "one\r" || d === "two\r");
  await ask(page, la, "one");
  const card = page.getByTestId("term-share-card");
  await expect(card.locator("button")).toHaveText(["Deny", "Allow once"]);
  await card.getByRole("button", { name: "Allow once" }).click();
  await expect.poll(ours).toEqual(["one\r"]);
  await expect(card).toHaveCount(0);
  // the same sender name again: its own card, nothing typed while it waits
  await ask(page, la, "two");
  await expect(card).toHaveCount(1);
  await expect(card.locator(".card-title")).toHaveText("Kami wants to type into Shell");
  await expect(card.getByTestId("term-share-prompt")).toHaveText("two");
  await page.waitForTimeout(3500);
  expect(await ours()).toEqual(["one\r"]);
  await card.getByRole("button", { name: "Allow once" }).click();
  await expect.poll(ours).toEqual(["one\r", "two\r"]);
  await expect(card).toHaveCount(0);
});

test("an allowed many-line prompt is one bracketed paste while its terminal is parked", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "shell");
  const la = await linkId(page, a);
  await expect.poll(async () => Object.keys(await files(page))).toContain(la);
  // the program turns bracketed paste on
  await page.evaluate((i) => {
    const w = window as unknown as W & { __omherMockOut(id: number, d: string): boolean };
    w.__omherMockOut(w.__omherSessions.ptyOf(i)!, "\x1b[?2004h");
  }, a);
  await ask(page, la, "first prompt");
  await page.getByTestId("term-share-card").getByRole("button", { name: "Allow once" }).click();
  await expect.poll(async () => (await writes(page, a)).filter((d) => d.includes("prompt"))).toEqual(["\x1b[200~first prompt\x1b[201~\r"]);
  // another session on the page; the first one is parked (short thresholds, as the park tests use)
  await newTerm(page, "shell");
  await page.evaluate(() => (window as unknown as { __omherPark: { set(o: object): void } }).__omherPark.set({ hiddenMs: 200, idleMs: 200, sweepMs: 100 }));
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherPark: { parked(): number } }).__omherPark.parked())).toBe(1);
  await ask(page, la, "first line\nsecond line");
  await page.getByTestId("term-share-card").getByRole("button", { name: "Allow once" }).click();
  await expect.poll(async () => (await writes(page, a)).filter((d) => d.includes("line"))).toEqual(["\x1b[200~first line\nsecond line\x1b[201~\r"]);
});

test("a request to a paused terminal shows its card there: Deny, or Resume and send, which types it once", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "shell");
  const la = await linkId(page, a);
  await expect.poll(async () => Object.keys(await files(page))).toContain(la);
  // omher restarts: the shell comes back paused, nothing runs
  await page.reload();
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await expect.poll(async () => (await files(page))[la]?.state).toBe("ended");
  await ask(page, la, "first request");
  const card = page.getByTestId("term-share-card");
  await expect(card).toHaveCount(1);
  await expect(page.getByTestId(`session-${a}`)).toHaveAttribute("data-term-status", "bell");
  // no Allow once where nothing runs: only Resume and send
  await expect(card.locator("button")).toHaveText(["Deny", "Resume and send"]);
  await expect(card.locator("button").first()).toBeFocused();
  await card.getByRole("button", { name: "Deny" }).click();
  await expect(card).toHaveCount(0);
  expect(await page.evaluate(() => ((window as unknown as W).__omherShellCalls ?? []).filter((c) => c.op === "start").length)).toBe(0);
  await ask(page, la, "second request");
  await card.getByRole("button", { name: "Resume and send" }).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect.poll(async () => (await writes(page, a)).filter((d) => d.includes("request")), { timeout: 15_000 }).toEqual(["second request\r"]);
  await expect(card).toHaveCount(0);
  await page.waitForTimeout(1500);
  expect((await writes(page, a)).filter((d) => d.includes("request"))).toEqual(["second request\r"]);
});

test.describe("shots", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const theme of ["dark", "light"] as const) {
    test(`shots: a bot's request card on a terminal (${theme})`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      await open(page, theme);
      const id = await newTerm(page, "claude");
      await page.evaluate(([i]) => (window as unknown as W).__omherSessions.rename(i!, "checkout build"), [id] as const);
      const link = await linkId(page, id);
      await expect.poll(async () => Object.keys(await files(page))).toContain(link);
      await ask(page, link, "Run the payment tests again and tell me which one fails:\npnpm test payments --reporter=dot");
      await expect(page.getByTestId("term-share-card")).toBeVisible();
      await shot(page, `term-link-bot-card-${theme}`);
    });
    test(`shots: a request card on a paused terminal (${theme})`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      await open(page, theme);
      const id = await newTerm(page, "shell");
      const link = await linkId(page, id);
      await expect.poll(async () => Object.keys(await files(page))).toContain(link);
      await page.reload();
      await page.getByTestId(`session-${id}`).locator(".ss-open").click();
      await expect(page.getByTestId("session-paused")).toBeVisible();
      await ask(page, link, "Run the payment tests again and tell me which one fails:\npnpm test payments --reporter=dot");
      await expect(page.getByTestId("term-share-card")).toBeVisible();
      await shot(page, `term-link-bot-paused-card-${theme}`);
    });
  }
});
