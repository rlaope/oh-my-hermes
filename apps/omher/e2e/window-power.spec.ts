// Settings › General › System (tray + keep awake, src/lib/power.ts):
// 1. both rows render with their defaults (keep running in the tray; keep awake on), each choice survives a reload,
//    and the window choice reaches the shell (`window_prefs`, recorded by the mock as `__omherWindowPrefs`);
// 2. a TERMINALS agent printing sends one `power.busy(true)` to the shell, and its going quiet one `power.busy(false)`,
//    never one call per output; turning the setting off while busy lets go at once (`now: true`) and sends no more;
// 3. the first time the close hides the window, one notification says omher still runs; the next hide says nothing.
// Shots (dark and light) when OMHER_SHOTS=<dir>: kwin-settings-system-dark.png, kwin-settings-system-light.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
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

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((th) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders", "omher.term", "omher.window.close", "omher.awake", "omher.window.hiddenNoted"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    localStorage.setItem("omher.theme", th);
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = "/home/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh"];
    w.__omherPowerTiming = { poll: 150, work: 800, quiet: 800 };
    const notes: { title: string; body?: string }[] = [];
    w.__notes = notes;
    class FakeNotification {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: (() => void) | null = null;
      constructor(title: string, opts?: { body?: string }) {
        notes.push({ title, body: opts?.body });
      }
      close() {}
    }
    w.Notification = FakeNotification;
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function openGeneral(page: Page) {
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-nav-general")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("set-system")).toBeVisible();
}

/** The mock seeds kami mid-turn: set every bot's turn by hand. */
const botTurn = (running: boolean) =>
  mock("mock.emit", { events: ["kami", "friren", "default", "omh-tui"].map((bot) => ({ event: "bot.status", bot, status: "online", running })) });

const powerCalls = (page: Page) =>
  page.evaluate(() => (((window as any).__omherSessionCalls ?? []) as { op: string; busy?: boolean; now?: boolean }[]).filter((c) => c.op === "power.busy").map((c) => ({ busy: c.busy, now: c.now })));

test("System rows: defaults, persisted choices, the shell hears the window choice", async ({ page }) => {
  await open(page);
  await openGeneral(page);
  const close = page.getByTestId("window-close-seg");
  await expect(close.getByRole("radio", { name: "Keep running" })).toHaveAttribute("aria-checked", "true");
  // the hint names where omher goes on this platform (the browser's own platform here)
  await expect(page.getByTestId("set-system")).toContainText(/omher stays in the (menu bar|notification area)/);
  await expect(page.getByTestId("set-awake")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("set-system")).toContainText("Closing the lid still sleeps it.");
  await expect.poll(() => page.evaluate(() => (window as any).__omherWindowPrefs?.[0])).toEqual({ hide: true, open: "Open omher", quit: "Quit omher" });

  await close.getByRole("radio", { name: "Quit", exact: true }).click();
  await page.getByTestId("set-awake").click();
  await expect(page.getByTestId("set-awake")).toHaveAttribute("aria-checked", "false");
  await expect.poll(() => page.evaluate(() => (window as any).__omherWindowPrefs.at(-1).hide)).toBe(false);

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await openGeneral(page);
  await expect(page.getByTestId("window-close-seg").getByRole("radio", { name: "Quit", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("set-awake")).toHaveAttribute("aria-checked", "false");
  // after the reload the shell hears the saved choice first thing
  await expect.poll(() => page.evaluate(() => (window as any).__omherWindowPrefs?.[0]?.hide)).toBe(false);

  // the tray labels follow the language
  await page.getByTestId("language").getByRole("radio", { name: "한국어" }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__omherWindowPrefs.at(-1))).toEqual({ hide: false, open: "omher 열기", quit: "omher 종료" });
});

test("a bot turn holds the computer awake until it ends", async ({ page }) => {
  await open(page);
  await expect.poll(() => powerCalls(page)).toEqual([{ busy: true, now: false }]);
  await botTurn(false);
  await expect.poll(() => powerCalls(page), { timeout: 8_000 }).toEqual([
    { busy: true, now: false },
    { busy: false, now: false },
  ]);
  await mock("mock.emit", { events: [{ event: "bot.status", bot: "friren", status: "online", running: true }] });
  await expect.poll(() => powerCalls(page).then((c) => c.at(-1))).toEqual({ busy: true, now: false });
  expect((await powerCalls(page)).length).toBe(3);
});

test("a mock agent printing then going quiet sends one busy and one idle edge", async ({ page }) => {
  await open(page);
  // the seeded bot turn first ends (its own edges), then only the terminal counts
  await expect.poll(() => powerCalls(page)).toEqual([{ busy: true, now: false }]);
  await botTurn(false);
  await expect.poll(() => powerCalls(page), { timeout: 8_000 }).toEqual([
    { busy: true, now: false },
    { busy: false, now: false },
  ]);
  const after = async () => (await powerCalls(page)).slice(2);
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-claude").click();
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).toContainText("(mock)");
  const id = await page.evaluate(() => (window as any).__omherSessions.getState().list.at(-1).id as string);
  const pty = await page.evaluate((i) => (window as any).__omherSessions.ptyOf(i) as number, id);

  // it keeps printing: one busy edge, no more calls while it does
  for (let i = 0; i < 8; i++) {
    await page.evaluate(([p, n]) => (window as any).__omherMockOut(p, `working ${n}\r\n`), [pty, i] as const);
    await page.waitForTimeout(150);
  }
  expect(await after()).toEqual([{ busy: true, now: false }]);
  // it stops: one idle edge, and nothing after it
  await expect.poll(after, { timeout: 8_000 }).toEqual([
    { busy: true, now: false },
    { busy: false, now: false },
  ]);
  await page.waitForTimeout(1_000);
  expect((await after()).length).toBe(2);

  // busy again, then the setting goes off: the shell lets go at once and hears nothing more
  await page.evaluate((p) => (window as any).__omherMockOut(p, "again\r\n"), pty);
  await expect.poll(() => after().then((c) => c.length)).toBe(3);
  await openGeneral(page);
  await page.getByTestId("set-awake").click();
  await expect.poll(after).toEqual([
    { busy: true, now: false },
    { busy: false, now: false },
    { busy: true, now: false },
    { busy: false, now: true },
  ]);
  await page.evaluate((p) => (window as any).__omherMockOut(p, "more\r\n"), pty);
  await page.waitForTimeout(800);
  expect((await after()).length).toBe(4);
});

test("the first hide of the window shows one 'still running' notification", async ({ page }) => {
  await open(page);
  await expect.poll(() => page.evaluate(() => typeof (window as any).__omherWindowHidden)).toBe("function");
  await page.evaluate(() => (window as any).__omherWindowHidden());
  await page.evaluate(() => (window as any).__omherWindowHidden());
  const notes = await page.evaluate(() => (window as any).__notes as { title: string; body?: string }[]);
  expect(notes.length).toBe(1);
  expect(notes[0].title).toBe("omher is still running");
  expect(notes[0].body).toMatch(/^Quit from the (menu bar|notification area) icon$/);
  // once per install: a reload does not say it again
  await page.reload();
  await expect.poll(() => page.evaluate(() => typeof (window as any).__omherWindowHidden)).toBe("function");
  await page.evaluate(() => (window as any).__omherWindowHidden());
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(0);
});

for (const theme of ["dark", "light"] as const) {
  test(`shot: Settings › General › System (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS not set");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ colorScheme: theme });
    await open(page, theme);
    await openGeneral(page);
    await page.getByTestId("set-system").scrollIntoViewIfNeeded();
    await page.mouse.move(10, 890);
    await page.waitForTimeout(300);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `kwin-settings-system-${theme}.png`), animations: "disabled" });
  });
}
