// Program Resume (OSC 7577) in the bottom terminal panel, on the mock host: each panel shell is told it may ask
// (`resume: false` under its own pane key `panel-<n>`, the id the tab comes back under), a gh sign-in tab never is,
// and Settings › Terminal "Programs may ask to restart" off tells no panel shell. After a restart the pane put back
// keeps its record (every other goes), its shell takes it out once as it starts (`resume: true`) and types only the
// line the shell made, never the program's command; a second restart has nothing left.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const FOLDER = "/home/you/code/web-app";

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

type ShellCall = { op: string; id?: number; link?: string; panel?: string; resume?: boolean; data?: string; keep?: string[] };
const shellCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: ShellCall[] }).__omherShellCalls ?? []) as ShellCall[]);
const starts = async (page: Page) => (await shellCalls(page)).filter((c) => c.op === "start");
const writes = async (page: Page, pty: number) => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === pty).map((c) => c.data);
const records = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("__omherMockResume") || "{}") as Record<string, string>);
const shown = (page: Page) => page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows');

async function open(page: Page, term: Record<string, unknown> = {}) {
  await page.addInitScript(
    ([folder, t]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.termpanel.tabs", "__omherMockHistory", "__omherMockResume"]) localStorage.removeItem(k);
        localStorage.setItem("omher.term", JSON.stringify(t));
        sessionStorage.setItem("__kept", "1");
      }
      (window as unknown as Record<string, unknown>).__omherPickFolder = folder;
    },
    [FOLDER, term] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function openPanel(page: Page) {
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(shown(page)).toContainText("login shell in");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a panel shell may ask under its pane key; the pane put back brings its program back once", async ({ page }) => {
  test.setTimeout(60_000);
  await open(page);
  await openPanel(page);
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  const first = (await starts(page))[0];
  // told it may ask, under its own pane key; no link (no OMHER_TERMINAL_LINK) and no record taken
  expect(first).toMatchObject({ resume: false });
  expect(first).not.toHaveProperty("link");
  expect(first.panel).toMatch(/^panel-[1-9][0-9]*$/);
  const key = first.panel!;
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.termpanel.tabs"))).not.toBeNull();
  // its program reported (htop); a record of a pane that is gone is kept too, until the restart
  await page.evaluate((k) => localStorage.setItem("__omherMockResume", JSON.stringify({ [k]: "htop", "panel-999": "vim" })), key);
  await page.waitForTimeout(400);

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  // the pane put back keeps its record; the gone pane's record goes
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "resume-records").flatMap((c) => c.keep ?? [])).toContain(key);
  await expect.poll(() => records(page)).toEqual({ [key]: "htop" });
  await openPanel(page);
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  const st = (await starts(page))[0];
  expect(st).toMatchObject({ panel: key, resume: true });
  // the record left before the shell started (one-shot); the only line typed is the shell's own, never the command
  expect(await records(page)).toEqual({});
  await expect.poll(() => writes(page, st.id!), { timeout: 10_000 }).toEqual([` '/mock/omher' --resume-exec '/mock/resume/launch-${st.id}.json'\r`]);
  await page.waitForTimeout(1_500);
  expect(await writes(page, st.id!)).toHaveLength(1);

  // a second restart has nothing to bring back
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await openPanel(page);
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  const again = (await starts(page))[0];
  expect(again).toMatchObject({ panel: key, resume: true });
  await page.waitForTimeout(3_800);
  expect(await writes(page, again.id!)).toEqual([]);
});

test("a gh sign-in tab is never told it may ask", async ({ page }) => {
  await open(page);
  await page.evaluate(async () => {
    const m = (await import("/src/terminal/state.ts" as string)) as { addGhLoginTab(h: string | null): void };
    m.addGhLoginTab(null);
  });
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "gh-login").length).toBe(1);
  expect(await starts(page)).toEqual([]);
  const gh = (await shellCalls(page)).find((c) => c.op === "gh-login")!;
  expect(gh).not.toHaveProperty("resume");
  expect(gh).not.toHaveProperty("panel");
});

test("Settings › Terminal off: no panel shell is told it may ask", async ({ page }) => {
  await open(page, { programResume: false });
  await openPanel(page);
  await expect.poll(async () => (await starts(page)).length).toBe(1);
  const st = (await starts(page))[0];
  expect(st).not.toHaveProperty("resume");
  expect(st).not.toHaveProperty("panel");
});
