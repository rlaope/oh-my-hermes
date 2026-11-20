// Closing a TERMINALS row can be undone for a while (Settings › Terminal › Undo window after closing, 10 s by
// default): the row leaves at once, its program keeps running hidden and takes no input, a toast bottom right says
// "<name> closed" with Undo. Undo puts the same row, terminal and program back where they were (in their split too);
// at the deadline the old close runs once. ⌘Z (macOS) / Ctrl+Shift+Z undoes the newest; plain Ctrl+Z stays the
// program's. Off closes as before. Run once with OMHER_E2E_PLATFORM=Win32 for the Ctrl paths.
// Shots (dark and light) when OMHER_SHOTS=<dir>: kclose-toast-dark.png, kclose-toast-light.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { mock, openApp, platformIsMac, type OpenOpts } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";

type Rec = { id: string };
type Sessions = {
  startTerminal(a: string, cwd: string): string;
  ptyOf(id: string): number | null;
  getState(): { list: Rec[] };
  typeAllowed(id: string, p: string): Promise<boolean>;
  canType(id: string): boolean;
  dropOnTerminal(id: string, f: { name: string; read: () => Promise<Uint8Array> }[], w: boolean): Promise<void>;
  close(id: string): void;
};
type ShellCall = { op: string; id?: number; data?: string };
type SessionCall = { op: string; session?: string };

const S = (page: Page) => page.evaluateHandle(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions);
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const ptyOf = async (page: Page, id: string) => {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
};
const ids = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessions: Sessions }).__omherSessions.getState().list.map((r) => r.id));
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const shellCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: ShellCall[] }).__omherShellCalls ?? []));
const sessionCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: SessionCall[] }).__omherSessionCalls ?? []));
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const row = (page: Page, id: string) => page.getByTestId(`session-${id}`);
const graceMs = (page: Page, ms: number) => page.evaluate((m) => void ((window as unknown as { __omherCloseGraceMs: number }).__omherCloseGraceMs = m), ms);

async function app(page: Page, o: OpenOpts = {}) {
  await openApp(page, o);
  await graceMs(page, 10_000);
}

async function shell(page: Page, cwd: string): Promise<string> {
  const id = await start(page, cwd);
  await expect(term(page, id).locator(".xterm-rows")).toContainText("login shell in");
  return id;
}

async function closeRow(page: Page, id: string) {
  await row(page, id).hover();
  await row(page, id).getByTestId("session-close").click();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a closed row's program keeps running for the undo window; Undo puts the same terminal back where it was", async ({ page }) => {
  await app(page);
  const a = await shell(page, "/home/you/code/web-app");
  const b = await shell(page, "/home/you/code/api-server");
  const c = await shell(page, "/home/you/code/docs");
  const pb = await ptyOf(page, b);
  await page.getByTestId(`session-${b}`).locator(".ss-open").click();
  await out(page, pb, "marker-before-close-7731\r\n");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("marker-before-close-7731");
  const order = await ids(page);
  expect(order).toEqual(expect.arrayContaining([a, b, c]));

  // the x closes without asking (the toast is the way back); the row leaves the list and the view at once
  await closeRow(page, b);
  await expect(page.getByTestId(`session-confirm-${b}`)).toHaveCount(0);
  await expect(row(page, b)).toHaveCount(0);
  await expect(term(page, b)).toHaveCount(0);
  const toast = page.getByTestId(`close-toast-${b}`);
  await expect(toast).toBeVisible();
  await expect(toast).toContainText("api-server");
  await expect(toast).toContainText("closed");
  await expect(toast.getByTestId("close-toast-left")).toHaveText(/^(10|9) s$/);
  // nothing stopped, nothing removed
  expect((await shellCalls(page)).filter((x) => x.op === "close")).toEqual([]);
  expect((await sessionCalls(page)).filter((x) => x.op === "file.remove")).toEqual([]);

  // output still flows into the hidden terminal; input of every kind is refused
  await out(page, pb, "marker-during-grace-5512\r\n");
  const s = await S(page);
  expect(await s.evaluate((x, i) => x.canType(i), b)).toBe(false);
  expect(await s.evaluate((x, i) => x.typeAllowed(i, "echo from a bot"), b)).toBe(false);
  await s.evaluate((x, i) => x.dropOnTerminal(i, [{ name: "a.txt", read: async () => new Uint8Array([104, 105]) }], false), b);
  expect((await shellCalls(page)).filter((x) => x.op === "write" && x.id === pb)).toEqual([]);
  expect((await sessionCalls(page)).filter((x) => x.op === "file.save")).toEqual([]);

  // Undo: same place in the list, same pty, the scrollback and the output that came meanwhile
  await toast.getByTestId("close-toast-undo").click();
  await expect(toast).toHaveCount(0);
  await expect(row(page, b)).toBeVisible();
  expect(await ids(page)).toEqual(order);
  expect(await ptyOf(page, b)).toBe(pb);
  await expect(term(page, b).locator(".xterm-rows")).toContainText("marker-before-close-7731");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("marker-during-grace-5512");
  expect((await shellCalls(page)).filter((x) => x.op === "close")).toEqual([]);
  // and it takes input again
  await term(page, b).locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("ls");
  await expect.poll(async () => (await shellCalls(page)).filter((x) => x.op === "write" && x.id === pb).length).toBeGreaterThan(0);
});

test("at the end of the window the old close runs once: the pty is closed and the session's files removed", async ({ page }) => {
  await app(page);
  const a = await shell(page, "/home/you/code/web-app");
  const pa = await ptyOf(page, a);
  await graceMs(page, 300);
  await closeRow(page, a);
  await expect(page.getByTestId(`close-toast-${a}`)).toBeVisible();
  await expect(page.getByTestId(`close-toast-${a}`)).toHaveCount(0);
  await expect.poll(async () => (await shellCalls(page)).filter((x) => x.op === "close" && x.id === pa).length).toBe(1);
  await expect.poll(async () => (await sessionCalls(page)).filter((x) => x.op === "file.remove" && x.session === a).length).toBe(1);
  await page.waitForTimeout(400);
  expect((await shellCalls(page)).filter((x) => x.op === "close" && x.id === pa).length).toBe(1);
  expect((await sessionCalls(page)).filter((x) => x.op === "file.remove" && x.session === a).length).toBe(1);
  expect(await ids(page)).not.toContain(a);
});

test("a split pane's row closed and undone comes back into its split, in the same slot", async ({ page }) => {
  await app(page);
  const b = await shell(page, "/home/you/code/api-server");
  // ⌘D: a new Shell (a) in a new pane right of b
  await term(page, b).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press((await platformIsMac(page)) ? "Meta+d" : "Control+Shift+D");
  await expect(page.getByTestId("session-split")).toBeVisible();
  const a = (await page.locator('[data-testid="split-pane"][data-focused="true"]').getAttribute("data-session"))!;
  expect(a).not.toBe(b);
  const pa = await ptyOf(page, a);
  const slots = () => page.locator('[data-testid="split-pane"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-session")));
  const before = await slots();
  expect(before).toEqual([b, a]);

  await closeRow(page, a);
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect(page.getByTestId(`close-toast-${a}`)).toBeVisible();
  await page.getByTestId(`close-toast-${a}`).getByTestId("close-toast-undo").click();
  await expect(page.getByTestId("session-split")).toBeVisible();
  expect(await slots()).toEqual(before);
  expect(await ptyOf(page, a)).toBe(pa);
  expect((await shellCalls(page)).filter((x) => x.op === "close")).toEqual([]);
});

test("⌘Z / Ctrl+Shift+Z undoes the newest close; plain Ctrl+Z in a terminal stays the program's", async ({ page }) => {
  await app(page);
  const a = await shell(page, "/home/you/code/web-app");
  const b = await shell(page, "/home/you/code/api-server");
  const pa = await ptyOf(page, a);
  const mac = await platformIsMac(page);
  await closeRow(page, b);
  await expect(page.getByTestId(`close-toast-${b}`)).toBeVisible();
  await term(page, a).locator(".xterm-helper-textarea").focus();
  if (!mac) {
    // Ctrl+Z inside the terminal is the program's suspend key: it reaches the shell and undoes nothing
    await page.keyboard.press("Control+z");
    await expect.poll(async () => (await shellCalls(page)).some((x) => x.op === "write" && x.id === pa && x.data === "\x1a")).toBe(true);
    await expect(page.getByTestId(`close-toast-${b}`)).toBeVisible();
  }
  await page.keyboard.press(mac ? "Meta+z" : "Control+Shift+Z");
  await expect(page.getByTestId(`close-toast-${b}`)).toHaveCount(0);
  await expect(row(page, b)).toBeVisible();
  // the undo key never reached a program
  expect((await shellCalls(page)).filter((x) => x.op === "write" && x.id === pa && x.data !== "\x1a")).toEqual([]);
});

test("several closes stack, three shown with the newest on top, each with its own deadline", async ({ page }) => {
  await app(page);
  const rows: string[] = [];
  for (const d of ["one", "two", "three", "four"]) rows.push(await shell(page, `/home/you/code/${d}`));
  for (const id of rows) await closeRow(page, id);
  const shown = page.locator('[data-testid^="close-toast-s"]');
  await expect(shown).toHaveCount(3);
  // newest on top: the column ends at the bottom right, so the first element is the top one
  expect(await shown.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual([rows[3], rows[2], rows[1]].map((i) => `close-toast-${i}`));
  const tops = await shown.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
  expect(tops[0]).toBeLessThan(tops[1]);
  // undo the newest; the oldest shows again, still waiting
  await page.getByTestId(`close-toast-${rows[3]}`).getByTestId("close-toast-undo").click();
  await expect(shown).toHaveCount(3);
  await expect(page.getByTestId(`close-toast-${rows[0]}`)).toBeVisible();
});

test("Off closes as before: the old question, then the program stops at once", async ({ page }) => {
  await app(page, { term: { undoClose: 0 } });
  const a = await shell(page, "/home/you/code/web-app");
  const pa = await ptyOf(page, a);
  await closeRow(page, a);
  // the old question, then the old close
  await page.getByTestId("session-stop").click();
  await expect(row(page, a)).toHaveCount(0);
  await expect(page.getByTestId("close-toasts")).toHaveCount(0);
  await expect.poll(async () => (await shellCalls(page)).filter((x) => x.op === "close" && x.id === pa).length).toBe(1);
});

test("a shell that ends by itself closes its row with no toast", async ({ page }) => {
  await app(page);
  const b = await shell(page, "/home/you/code/api-server");
  await term(page, b).locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(row(page, b)).toHaveCount(0);
  await expect(page.getByTestId("close-toasts")).toHaveCount(0);
});

test("Settings › Terminal: Undo window after closing is Off / 5 s / 10 s, 10 s by default", async ({ page }) => {
  await app(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const seg = page.getByTestId("term-undo-close");
  await expect(seg.getByRole("radio")).toHaveText(["Off", "5 s", "10 s"]);
  await expect(seg.getByRole("radio", { name: "10 s" })).toHaveAttribute("aria-checked", "true");
  await seg.getByRole("radio", { name: "Off" }).click();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").undoClose)).toBe(0);
  await expect(page.getByTestId("term-undo-close-row")).toContainText("undo the close");
});

test("shots: the undo toast, dark and light", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS not set");
  mkdirSync(join(SHOTS), { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await app(page, { theme });
    const a = await shell(page, "/home/you/code/web-app");
    const b = await shell(page, "/home/you/code/api-server");
    await shell(page, "/home/you/code/docs");
    await closeRow(page, a);
    await closeRow(page, b);
    await expect(page.getByTestId(`close-toast-${b}`)).toBeVisible();
    await page.mouse.move(700, 400);
    await page.screenshot({ path: join(SHOTS, `kclose-toast-${theme}.png`) });
  }
});
