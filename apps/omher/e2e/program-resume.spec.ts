// Program Resume (OSC 7577) on the mock host: a Shell row whose program asked to be started again (the mock computer
// keeps that record per row link, as the shell keeps `resume.json`) comes back paused after omher restarts and says
// which program Resume brings back. Resume asks the shell for that record once (`resume: true`) and types only the
// line the shell made (omher's own program and a one-use launch file), never the program's command; a second restart
// has nothing left. A row with no record says nothing; records of rows that are gone are dropped. Settings › Terminal
// "Programs may ask to restart" (on by default) turned off: no row is told it may ask and no record is read.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const FOLDER = "/home/you/code/web-app";
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

type ShellCall = { op: string; id?: number; link?: string; resume?: boolean; data?: string; keep?: string[] };
const shellCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: ShellCall[] }).__omherShellCalls ?? []) as ShellCall[]);
const starts = async (page: Page) => (await shellCalls(page)).filter((c) => c.op === "start");
const writes = async (page: Page, pty: number) => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === pty).map((c) => c.data);
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));
const records = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("__omherMockResume") || "{}") as Record<string, string>);

async function open(page: Page) {
  await page.addInitScript((folder) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.termpanel.tabs", "__omherMockHistory", "omher.term", "__omherMockResume"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    (window as unknown as Record<string, unknown>).__omherPickFolder = folder;
  }, FOLDER);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function newShell(page: Page): Promise<string> {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-shell").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows").last()).toContainText("(mock)");
  return (await page.getByTestId("terminal").getAttribute("data-session"))!;
}

const linkOf = async (page: Page, id: string) => ((await saved(page))?.sessions ?? []).find((s: { id: string }) => s.id === id)?.linkId as string;

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a Shell row whose program asked to be restarted names it after a restart, and Resume brings it back once", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  const asked = await newShell(page);
  const plain = await newShell(page);
  await expect.poll(async () => (await saved(page))?.sessions?.length).toBe(2);
  // each Shell row's shell is told it may ask (its token stays in the shell): `resume: false` takes no record
  expect((await starts(page)).map((c) => c.resume)).toEqual([false, false]);
  const link = await linkOf(page, asked);
  // the program in the first row reported (nvim); a record of a row that is gone is kept too, until the restart
  await page.evaluate((l) => localStorage.setItem("__omherMockResume", JSON.stringify({ [l]: "nvim", zzzzzzzzzz: "htop" })), link);
  await page.waitForTimeout(400);

  await page.reload();
  await expect(page.getByTestId(`session-${asked}`)).toBeVisible();
  // the rows that came back paused keep their records; the gone row's record goes
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "resume-records").map((c) => [...(c.keep ?? [])].sort())).toEqual([[link, await linkOf(page, plain)].sort()]);
  await expect.poll(() => records(page)).toEqual({ [link]: "nvim" });
  // nothing starts by itself
  expect(await starts(page)).toEqual([]);
  await page.getByTestId(`session-${plain}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await expect(page.getByTestId("session-resume-program")).toHaveCount(0);
  await page.getByTestId(`session-${asked}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-resume-program")).toHaveText("· Resume runs nvim again");
  await expect(page.getByTestId("session-resume-program")).toHaveAttribute("title", /never read as shell commands/);
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    for (const theme of ["dark", "light"] as const) {
      await page.evaluate((th) => document.documentElement.setAttribute("data-theme", th), theme);
      await page.waitForTimeout(150);
      await page.getByTestId("session-paused").screenshot({ path: join(SHOTS, `paused-row-${theme}.png`) });
    }
  }

  await page.getByTestId("session-resume").click();
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  const st = (await starts(page))[0];
  expect(st).toMatchObject({ link, resume: true });
  // the record left before the shell started (one-shot); the only line typed is the shell's own, never the command
  expect(await records(page)).toEqual({});
  await expect.poll(() => writes(page, st.id!), { timeout: 10_000 }).toEqual([` '/mock/omher' --resume-exec '/mock/resume/launch-${st.id}.json'\r`]);
  await page.waitForTimeout(1_500);
  expect(await writes(page, st.id!)).toHaveLength(1);
  // a second restart has nothing to bring back: the row is a plain paused shell
  await page.reload();
  await expect(page.getByTestId(`session-${asked}`)).toBeVisible();
  await page.getByTestId(`session-${asked}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await expect(page.getByTestId("session-resume-program")).toHaveCount(0);
});

test("Settings › Terminal turns it off: no shell is told it may ask and no record is read", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-program-resume-row")).toContainText("Programs may ask to restart");
  const sw = page.getByTestId("term-program-resume");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    for (const theme of ["dark", "light"] as const) {
      await page.evaluate((th) => document.documentElement.setAttribute("data-theme", th), theme);
      await page.waitForTimeout(150);
      await page.getByTestId("term-program-resume-row").screenshot({ path: join(SHOTS, `setting-row-${theme}.png`) });
    }
  }
  await sw.getByRole("radio", { name: "Off" }).click();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ programResume: false });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  const id = await newShell(page);
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  expect((await starts(page))[0]).not.toHaveProperty("resume");
  const link = await linkOf(page, id);
  await page.evaluate((l) => localStorage.setItem("__omherMockResume", JSON.stringify({ [l]: "nvim" })), link);
  await page.reload();
  await expect(page.getByTestId(`session-${id}`)).toBeVisible();
  await page.waitForTimeout(800);
  expect((await shellCalls(page)).filter((c) => c.op === "resume-records")).toEqual([]);
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  await expect(page.getByTestId("session-resume-program")).toHaveCount(0);
  await page.getByTestId("session-resume").click();
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  expect((await starts(page))[0]).not.toHaveProperty("resume");
});
