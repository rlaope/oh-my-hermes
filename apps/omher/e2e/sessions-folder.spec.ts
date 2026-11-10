// SESSIONS: the + menu asks for the folder. Picking an agent turns the same menu to its folder step:
// "Choose folder…" (the native dialog; `__omherPickFolder` stands in for it in the browser) and up to five
// recent folders. The session row then carries the folder's name, with the full path in its tooltip.
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

/** Seven folders, newest first, as the app saves them (the menu offers five). */
const RECENT = [
  { agent: "claude", cwd: "/Users/you/code/oh-my-hermes", at: 7 },
  { agent: "codex", cwd: "/Users/you/work/api-server", at: 6 },
  { agent: "claude", cwd: "/Users/you/code/omher", at: 5 },
  { agent: "omh", cwd: "/Users/you/notes", at: 4 },
  { agent: "codex", cwd: "/Volumes/data/datasets", at: 3 },
  { agent: "claude", cwd: "/Users/you/code/old-one", at: 2 },
  { agent: "claude", cwd: "/Users/you/code/older", at: 1 },
];

async function open(page: Page, theme: "dark" | "light" = "dark", recent: unknown[] = RECENT) {
  await page.addInitScript(
    ([t, r]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.setItem("omher.sessions.recent", r as string);
      (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/new-app";
    },
    [theme, JSON.stringify(recent)] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const calls = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string; agent?: string; cwd?: string }[] }).__omherSessionCalls ?? []));

const pick = (page: Page, folder: string | null) =>
  page.evaluate((f) => ((window as unknown as { __omherPickFolder: string | null }).__omherPickFolder = f), folder);

/** Row backgrounds fade (0.12s) and the pointer must not hover a row before a screenshot. */
async function settle(page: Page) {
  await page.mouse.move(900, 780);
  await page.waitForTimeout(350);
}

/** WCAG contrast of each selector's text colour on `bg` (an rgb() string). */
async function contrast(page: Page, sels: string[], bg: string) {
  return page.evaluate(
    ([s, b]) => {
      const rgb = (c: string) => c.match(/[\d.]+/g)!.slice(0, 3).map(Number);
      const lum = (c: number[]) => {
        const [r, g, bl] = c.map((v) => {
          v /= 255;
          return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
      };
      const back = lum(rgb(b as string));
      return (s as string[]).map((sel) => {
        const el = document.querySelector(sel);
        if (!el) return [sel, 0] as const;
        const a = lum(rgb(getComputedStyle(el).color));
        return [sel, (Math.max(a, back) + 0.05) / (Math.min(a, back) + 0.05)] as const;
      });
    },
    [sels, bg] as const,
  );
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of ["dark", "light"] as const) {
  test(`after the agent the menu offers Choose folder… and five recent folders; a recent one starts there (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, theme);
    await page.getByTestId("session-start").click();
    const menu = page.getByTestId("session-menu");
    // step 1: the agents only (the folders come after the agent)
    await expect(menu.locator("[data-testid^=session-agent-]")).toHaveCount(6);
    await expect(menu.getByTestId("session-recent")).toHaveCount(0);
    await expect(menu.getByTestId("session-choose")).toHaveCount(0);
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await settle(page);
      await page.screenshot({ path: join(SHOTS, `sessions-menu-${theme}-after.png`) });
    }

    // step 2: the agent's mark and name, Choose folder… first (and focused), then five folders, newest first
    await menu.getByTestId("session-agent-claude").click();
    await expect(menu).toHaveAttribute("data-step", "folder");
    const head = menu.getByTestId("session-folder-agent");
    await expect(head).toHaveText("Claude Code");
    await expect(head.locator('svg[data-mark="claude"]')).toHaveCount(1);
    await expect(menu.getByTestId("session-choose")).toHaveText("Choose folder…");
    await expect(menu.getByTestId("session-choose")).toBeFocused();
    const rows = menu.getByTestId("session-recent");
    await expect(rows).toHaveCount(5);
    expect(await rows.locator(".ss-n").allTextContents()).toEqual(["oh-my-hermes", "api-server", "omher", "notes", "datasets"]);
    // the folder's parent, dim and ~-shortened; the whole path in the tooltip
    expect(await rows.locator(".ss-path").allTextContents()).toEqual(["~/code", "~/work", "~/code", "~", "/Volumes/data"]);
    await expect(rows.nth(1)).toHaveAttribute("title", "/Users/you/work/api-server");
    // the same section width as step 1: 8px inside both sidebar edges, and the dim labels meet 4.5:1
    const side = (await page.getByTestId("sidebar").boundingBox())!;
    const pop = (await menu.locator("..").boundingBox())!;
    expect(Math.round(pop.x - side.x)).toBe(8);
    expect(Math.round(side.x + side.width - (pop.x + pop.width))).toBe(8);
    const popBg = await menu.locator("..").evaluate((e) => getComputedStyle(e).backgroundColor);
    for (const [sel, r] of await contrast(page, [".ss-pop .ss-h", ".ss-pop .ss-path", ".ss-pop .ss-back", ".ss-pop .ss-agent"], popBg))
      expect(r, sel).toBeGreaterThanOrEqual(4.5);
    for (const name of ["oh-my-hermes", "api-server", "datasets"])
      expect(await rows.filter({ hasText: name }).locator(".ss-n").evaluate((el) => el.scrollWidth <= el.clientWidth), `${name} whole`).toBe(true);
    if (SHOTS) {
      await settle(page);
      await page.screenshot({ path: join(SHOTS, `sessions-folder-${theme}-after.png`) });
    }

    // a recent folder starts the agent there, without the dialog
    await rows.filter({ hasText: "api-server" }).click();
    await expect(menu).toHaveCount(0);
    await expect(page.getByTestId("session-chat")).toBeVisible();
    await expect.poll(async () => (await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "claude", cwd: "/Users/you/work/api-server" });
    const row = page.locator("[data-testid=session-list] .ss-row").first();
    await expect(row.locator(".bot-n")).toHaveText("api-server");
    await expect(row.locator(".ss-open")).toHaveAttribute("title", "/Users/you/work/api-server");

    // that folder moves to the top, once, though another agent used it before
    await page.getByTestId("session-new").click();
    await menu.getByTestId("session-agent-codex").click();
    expect(await rows.locator(".ss-n").allTextContents()).toEqual(["api-server", "oh-my-hermes", "omher", "notes", "datasets"]);
    await rows.filter({ hasText: "notes" }).click();
    await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(2);
    await expect(page.locator("[data-testid=session-list] .ss-row").first().locator(".bot-n")).toHaveText("notes");
    if (SHOTS) {
      await settle(page);
      await page.screenshot({ path: join(SHOTS, `sessions-row-${theme}-after.png`) });
    }
  });
}

test("Choose folder… opens the folder dialog; cancelling it keeps the menu and starts nothing", async ({ page }) => {
  await open(page, "dark", []);
  await pick(page, null); // the dialog cancelled
  await page.getByTestId("session-start").click();
  const menu = page.getByTestId("session-menu");
  await menu.getByTestId("session-agent-codex").click();
  // no recent folders yet: Choose folder… alone
  await expect(menu.getByTestId("session-recent")).toHaveCount(0);
  await menu.getByTestId("session-choose").click();
  await expect(menu).toHaveAttribute("data-step", "folder");
  await expect(menu.getByTestId("session-folder-agent")).toHaveText("Codex");
  expect((await calls(page)).filter((c) => c.op === "chat.start")).toEqual([]);
  await expect(page.getByTestId("session-none")).toBeVisible();

  // the dialog returns a folder: the session starts there and the menu closes
  await pick(page, "/Users/you/code/new-app");
  await menu.getByTestId("session-choose").click();
  await expect(menu).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).find((c) => c.op === "chat.start")).toMatchObject({ agent: "codex", cwd: "/Users/you/code/new-app" });
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row.locator(".bot-n")).toHaveText("new-app");
  await expect(row.locator(".bot-p")).toHaveText("Codex");
  await expect(row.locator(".ss-open")).toHaveAttribute("title", "/Users/you/code/new-app");
  // and it is a recent folder now
  await page.getByTestId("session-new").click();
  await menu.getByTestId("session-agent-claude").click();
  await expect(menu.getByTestId("session-recent")).toHaveText(["new-app~/code"]);
});

test("keyboard: Enter picks the agent, ← goes back to it, Esc closes", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-start").focus();
  await page.keyboard.press("Enter");
  const menu = page.getByTestId("session-menu");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(menu.getByTestId("session-agent-claude")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(menu.getByTestId("session-agent-codex")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(menu.getByTestId("session-choose")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(menu.getByTestId("session-recent").first()).toBeFocused();
  // back: Shift+Tab to ←, Enter; the agent list returns with Codex focused
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(menu.getByTestId("session-back")).toBeFocused();
  await expect(menu.getByTestId("session-back")).toHaveAttribute("aria-label", "Back");
  await page.keyboard.press("Enter");
  await expect(menu.getByTestId("session-agent-codex")).toBeFocused();
  await expect(menu.getByTestId("session-choose")).toHaveCount(0);
  // Esc closes the menu from either step, starting nothing
  await page.keyboard.press("Enter");
  await expect(menu.getByTestId("session-choose")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  expect((await calls(page)).filter((c) => c.op === "chat.start")).toEqual([]);
});
