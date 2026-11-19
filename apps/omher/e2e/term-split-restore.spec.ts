// TERMINALS splits after a restart, and the dim setting: the split layout is saved on this computer and comes back
// when omher starts again (a reload with the same storage; the mock host starts empty, as the shell does). Sessions
// that came back paused show paused in their pane, with Resume, which starts that one in place. Settings › Terminal ›
// Dim unfocused panes changes how bright the panes without the keyboard are, in TERMINALS and the bottom panel alike.
import { expect, test, type Page } from "@playwright/test";
import { mock } from "./term-find-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const pane = (page: Page, id: string) => page.locator(`[data-testid="split-pane"][data-session="${id}"]`);
const mac = (page: Page) => page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));

async function open(page: Page) {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.splits", "omher.termpanel.tabs", "__omherMockHistory", "omher.term"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function split(page: Page, from: string, key: string, pick: string) {
  await term(page, from).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press(key);
  await page.locator(`[data-testid="split-pick"][data-session="${pick}"]`).click();
  await expect(page.getByTestId("split-picker")).toHaveCount(0);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the split comes back after a restart, its layout and sizes kept; paused sessions show paused in their pane and Resume starts one in place", async ({ page }) => {
  await open(page);
  const m = await mac(page);
  const ids: string[] = [];
  for (const f of ["/w/a", "/w/b", "/w/c"]) {
    const id = await start(page, f);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  const [a, b, c] = ids;
  await page.getByTestId(`session-${a}`).locator(".ss-open").click();
  await split(page, a, m ? "Meta+d" : "Control+Shift+D", b);
  await split(page, b, m ? "Meta+Shift+D" : "Alt+Shift+D", c);
  // a divider moved: its size is kept too
  const div = page.locator('[data-testid="split-divider"][data-path=""]');
  await div.focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(div).toHaveAttribute("aria-valuenow", "40");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.splits"))).toContain('"ratio":0.4');

  await page.reload();
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  // the shells come back paused; opening one shows the whole split again, each pane paused with Resume
  await page.getByTestId(`session-${b}`).locator(".ss-open").click();
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "3");
  for (const id of [a, b, c]) await expect(pane(page, id).getByTestId("session-paused")).toBeVisible();
  await expect(pane(page, b)).toHaveAttribute("data-focused", "true");
  await expect(page.locator('[data-testid="split-divider"][data-path=""]')).toHaveAttribute("aria-valuenow", "40");
  // the same shape: b and c right of a, c under b
  const [ra, rb, rc] = [(await pane(page, a).boundingBox())!, (await pane(page, b).boundingBox())!, (await pane(page, c).boundingBox())!];
  expect(rb.x).toBeGreaterThan(ra.x + ra.width - 2);
  expect(rc.y).toBeGreaterThan(rb.y + rb.height - 2);
  // nothing started by itself
  expect(await page.evaluate(() => ((window as unknown as { __omherShellCalls?: { op: string }[] }).__omherShellCalls ?? []).filter((x) => x.op === "start").length)).toBe(0);
  // Resume in c's pane: c starts there, the others stay paused, the split stays
  await pane(page, c).getByTestId("session-resume").click();
  await expect(term(page, c).locator(".xterm-rows")).toContainText("(mock)");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "3");
  await expect(pane(page, a).getByTestId("session-paused")).toBeVisible();
});

test("a closed session leaves its split, and a split left with one pane ends", async ({ page }) => {
  await open(page);
  const m = await mac(page);
  const a = await start(page, "/w/a");
  await expect(term(page, a).locator(".xterm-rows")).toContainText("(mock)");
  const b = await start(page, "/w/b");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("(mock)");
  await split(page, b, m ? "Meta+d" : "Control+Shift+D", a);
  await expect(page.getByTestId("session-split")).toBeVisible();
  // close b from its row (stop): a is alone, no split, nothing saved
  await page.getByTestId(`session-${b}`).hover();
  await page.getByTestId(`session-${b}`).getByTestId("session-close").click();
  await page.getByTestId("session-stop").click();
  await expect(page.getByTestId("session-split")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.splits"))).toBeNull();
});

test("Dim unfocused panes: the setting sets how bright panes without the keyboard are, in TERMINALS and the bottom panel", async ({ page }) => {
  await open(page);
  const m = await mac(page);
  const a = await start(page, "/w/a");
  await expect(term(page, a).locator(".xterm-rows")).toContainText("(mock)");
  const b = await start(page, "/w/b");
  await expect(term(page, b).locator(".xterm-rows")).toContainText("(mock)");
  await split(page, b, m ? "Meta+d" : "Control+Shift+D", a);
  // a has the keyboard now: b is dimmed to the default 0.72
  const opacity = (id: string) => pane(page, id).locator(".term-wrap").evaluate((el) => getComputedStyle(el).opacity);
  await expect.poll(() => opacity(b)).toBe("0.72");
  await expect.poll(() => opacity(a)).toBe("1");
  // the bottom panel's unfocused pane too
  await page.keyboard.press("Control+Backquote");
  const panes = page.locator('[data-testid="termpanel-layout"]:not([hidden]) [data-testid="termpanel-terminal"]');
  await expect(panes.first().locator(".xterm-rows")).toContainText("login shell in");
  await page.keyboard.press(m ? "Meta+d" : "Control+Shift+D");
  await expect(panes).toHaveCount(2);
  const boxOpacity = (i: number) => panes.nth(i).locator(".term-box").evaluate((el) => getComputedStyle(el).opacity);
  await expect.poll(() => boxOpacity(0)).toBe("0.72");
  await expect.poll(() => boxOpacity(1)).toBe("1");
  // Settings › Terminal: one step down (0.68), both follow at once
  await page.keyboard.press(m ? "Meta+," : "Control+,");
  await page.getByTestId("settings-tab-terminal").or(page.getByRole("button", { name: /^Terminal$/ })).first().click();
  await page.getByTestId("term-dim").getByRole("button").first().click();
  await expect(page.getByTestId("term-dim").locator("input")).toHaveValue("0.68");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").dimUnfocused)).toBe(0.68);
  await expect.poll(() => boxOpacity(0)).toBe("0.68");
  await page.getByTestId(`session-${b}`).locator(".ss-open").click();
  await expect.poll(() => opacity(a)).toBe("0.68");
});
