// Terminal links (mock host): every TERMINALS session has a link id, kept across a restart, and a link
// `omher://terminal/<id>`. The row menu's "Copy link" and ⌘⇧C (Alt+Shift+C off macOS) in its terminal copy it, and
// the terminal says "Link copied" for a moment.
// A link in a message is an omher chip: the omher face, the session's CLI mark, its title and its live state; a click
// opens it; an id this computer does not have reads "Terminal not on this computer".
// Shots: OMHER_SHOTS=<dir> -> term-link-{menu,copied,chip}-{dark,light}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const FOLDER = "/home/you/code/web-app";
const LINK = /^omher:\/\/terminal\/[a-z2-7]{10}$/;

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "tl1") res(msg);
    };
    ws.send(JSON.stringify({ id: "tl1", op, ...params }));
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

const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));
const linkOf = (page: Page, id: string) => page.evaluate((i) => (window as unknown as { __omherSessions: { linkOf(id: string): string | null } }).__omherSessions.linkOf(i), id);
const clip = (page: Page) => page.evaluate(() => navigator.clipboard.readText());

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("each TERMINALS session gets its own link id, saved with it and the same after a restart", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "shell");
  const b = await newTerm(page, "claude");
  const la = await linkOf(page, a);
  const lb = await linkOf(page, b);
  expect(la).toMatch(LINK);
  expect(lb).toMatch(LINK);
  expect(la).not.toBe(lb);
  await expect
    .poll(async () => ((await saved(page))?.sessions ?? []).map((s: { id: string; linkId?: string }) => [s.id, s.linkId]).sort())
    .toEqual([[a, la!.slice(-10)], [b, lb!.slice(-10)]].sort());
  await page.reload();
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  expect(await linkOf(page, a)).toBe(la);
  expect(await linkOf(page, b)).toBe(lb);
});

test("the row menu's Copy link copies the link, and the terminal says so", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  const id = await newTerm(page, "shell");
  const row = page.getByTestId(`session-${id}`);
  await row.click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Rename", /^Show in (Finder|Explorer|file manager)$/, "Open in Terminal", "Copy link", "New terminal here", "Close session"]);
  await menu.getByTestId("session-copy-link").click();
  await expect.poll(() => clip(page)).toBe(await linkOf(page, id));
  await expect(page.getByTestId("term-link-copied")).toHaveText("Link copied");
  await expect(page.getByTestId("term-link-copied")).toHaveCount(0, { timeout: 4000 });
});

test("⌘⇧C (Alt+Shift+C off macOS) in a terminal copies its link and types nothing into it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  const id = await newTerm(page, "shell");
  await page.evaluate(() => navigator.clipboard.writeText("before"));
  const before = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).filter((c) => c.op === "write").length);
  const mac = await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));
  await page.locator(".xterm-helper-textarea").last().focus();
  await page.keyboard.press(mac ? "Meta+Shift+KeyC" : "Alt+Shift+KeyC");
  await expect.poll(() => clip(page)).toBe(await linkOf(page, id));
  await expect(page.getByTestId("term-link-copied")).toBeVisible();
  const after = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).filter((c) => c.op === "write").length);
  expect(after).toBe(before);
});

// ---- the omher chip -------------------------------------------------------------------------------------------

/** A bot answer in Kami's chat holding `text`. */
async function answer(page: Page, id: string, text: string) {
  await page.getByTestId("bot-kami").click();
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id, text }] });
}

test("a terminal link in a bot's answer is an omher chip with the session's mark, title and live state; a click opens it", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude");
  const link = (await linkOf(page, id))!;
  await page.evaluate(([i]) => (window as unknown as { __omherSessions: { rename(id: string, n: string): void } }).__omherSessions.rename(i!, "checkout build"), [id] as const);
  await answer(page, "tl-a1", `The build runs in ${link} now.`);
  const chip = page.getByTestId("bubble-bot").filter({ hasText: "The build runs in" }).getByTestId("term-link-chip");
  await expect(chip).toHaveCount(1);
  await expect(chip).toHaveAttribute("data-session", id);
  await expect(chip.locator(".lk-t")).toHaveText("checkout build");
  await expect(chip.locator(".lk-term-omh")).toHaveCount(1);
  await expect(chip.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
  expect(await chip.getAttribute("title")).toContain(link);
  // live: output flowing is working, then it settles to waiting at its prompt
  const pty = (await page.evaluate((i) => (window as unknown as { __omherSessions: { ptyOf(id: string): number | null } }).__omherSessions.ptyOf(i), id))!;
  await page.evaluate(([p]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p!, "compiling…\r\n"), [pty] as const);
  await expect(chip).toHaveAttribute("data-state", "working");
  await expect(chip).toHaveAttribute("data-state", "waiting", { timeout: 6000 });
  // a click opens the session's terminal
  await chip.click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
});

test("a link to a terminal this computer does not have reads so and opens nothing", async ({ page }) => {
  await open(page);
  await answer(page, "tl-a2", "Old one: omher://terminal/zzzzzzzzzz");
  const chip = page.getByTestId("bubble-bot").filter({ hasText: "Old one:" }).getByTestId("term-link-chip");
  await expect(chip).toHaveAttribute("data-state", "gone");
  await expect(chip).toHaveText("Terminal not on this computer");
  await chip.click();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
});

test.describe("shots", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const theme of ["dark", "light"] as const) {
    test(`shots: the row menu with Copy link (${theme})`, async ({ page, context }) => {
      test.skip(!SHOTS, "no shot folder");
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      await open(page, theme);
      const id = await newTerm(page, "claude");
      const row = page.getByTestId(`session-${id}`);
      await row.click({ button: "right" });
      await page.getByTestId("session-copy-link").hover();
      await shot(page, `term-link-menu-${theme}`);
      await page.getByTestId("session-copy-link").click();
      await expect(page.getByTestId("term-link-copied")).toBeVisible();
      await shot(page, `term-link-copied-${theme}`);
      // the chip in a bot answer: one live, one not on this computer
      await page.evaluate(([i]) => (window as unknown as { __omherSessions: { rename(id: string, n: string): void } }).__omherSessions.rename(i!, "checkout build"), [id] as const);
      await answer(page, "tl-shot", `The build runs in ${await linkOf(page, id)}; last week's was omher://terminal/zzzzzzzzzz.`);
      await expect(page.getByTestId("term-link-chip")).toHaveCount(2);
      await page.getByTestId("bubble-bot").filter({ hasText: "The build runs in" }).scrollIntoViewIfNeeded();
      await shot(page, `term-link-chip-${theme}`);
    });
  }
});
