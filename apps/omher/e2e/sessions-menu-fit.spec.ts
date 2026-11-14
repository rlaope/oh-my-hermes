// The SESSIONS + menu with every agent listed: at each window height from 600px it stays inside the window, ends
// above the sidebar's bottom rows (Automations, Plugins, Settings, You) instead of half-covering them, and scrolls
// inside so every row is reachable; arrow keys bring the focused row into view.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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

test.beforeEach(async () => {
  await mock("mock.reset");
});

const ALL = ["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "qwen", "kimi", "copilot", "cline"];

async function open(page: Page, height: number) {
  await page.setViewportSize({ width: 1280, height });
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherMockAgents: string[] };
    w.__omherMockAgents = ["claude", "codex", "omh", "opencode"];
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-more")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("session-more").click();
  await expect(page.getByTestId("session-agent-grok")).toBeAttached();
  await page.keyboard.press("Home");
  // the pop-in animation scales the box: measure once it has settled
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

const box = (page: Page, sel: string) =>
  page.evaluate((s) => {
    const el = document.querySelector(s)!;
    const r = el.getBoundingClientRect();
    // a menu opened upward keeps a band of the sidebar's colour above its edge (its air): it covers what lies there
    const band = parseFloat(getComputedStyle(el, "::before").height) || 0;
    return { top: r.top - band, bottom: r.bottom, left: r.left, right: r.right };
  }, sel);

for (const height of [600, 720, 820]) {
  test(`the + menu fits a ${height}px window, ends above the sidebar's bottom rows and scrolls to every agent`, async ({ page }) => {
    await open(page, height);
    const pop = await box(page, ".ss-pop");
    const win = await page.evaluate(() => ({ w: innerWidth, h: innerHeight }));
    expect(pop.top).toBeGreaterThanOrEqual(0);
    expect(pop.left).toBeGreaterThanOrEqual(0);
    expect(pop.bottom).toBeLessThanOrEqual(win.h);
    expect(pop.right).toBeLessThanOrEqual(win.w);
    // no sidebar row below it is partly covered: the menu ends above the first of them
    const foot = await box(page, ".side-foot");
    expect(pop.bottom).toBeLessThanOrEqual(foot.top);
    // no sidebar row shows half under either edge: each is wholly under the menu or wholly clear of it
    const cut = await page.evaluate((p) => {
      const rows = [...document.querySelectorAll(".side-top, .bot-list > *, .side-sh, .ss-list > *, .side-foot > *")];
      return rows
        .map((r) => r.getBoundingClientRect())
        .filter((r) => r.height > 0 && r.top < p.bottom - 0.5 && r.bottom > p.top + 0.5 && !(r.top >= p.top - 0.5 && r.bottom <= p.bottom + 0.5))
        .map((r) => [r.top, r.bottom]);
    }, pop);
    expect(cut).toEqual([]);
    // every agent is listed, the installed ones first (then the "Continue a conversation" rows)
    const all = await page.getByTestId("session-menu").locator("[role=menuitem]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!));
    const ids = all.filter((t) => t.startsWith("session-agent-")).map((t) => t.replace("session-agent-", ""));
    expect([...ids].sort()).toEqual([...ALL].sort());
    expect(ids.slice(0, 4)).toEqual(["claude", "codex", "omh", "opencode"]);
    expect(all.filter((id) => !id.startsWith("session-agent-") && id !== "session-more")).toEqual(["session-past-claude", "session-past-codex"]);
    // each row can be reached: scrolled into the menu's own box it is wholly inside the window
    const list = await box(page, "[data-testid=session-menu]");
    for (const id of all) {
      const row = page.getByTestId(id);
      await row.evaluate((e) => e.scrollIntoView({ block: "nearest" }));
      const r = await row.boundingBox();
      expect(r!.y).toBeGreaterThanOrEqual(list.top - 0.5);
      expect(r!.y + r!.height).toBeLessThanOrEqual(list.bottom + 0.5);
    }
  });
}

test("arrow keys scroll the focused row into view, End reaches the last agent, Home the first", async ({ page }) => {
  await open(page, 600);
  const list = await box(page, "[data-testid=session-menu]");
  const inView = async (id: string) => {
    const r = await page.getByTestId(id).boundingBox();
    return r!.y >= list.top - 0.5 && r!.y + r!.height <= list.bottom + 0.5;
  };
  await expect(page.getByTestId("session-agent-claude")).toBeFocused();
  // every row of the menu: the agents, then "Continue a conversation"
  const ids = await page.getByTestId("session-menu").locator("[role=menuitem]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!));
  for (const id of ids.slice(1)) {
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId(id)).toBeFocused();
    expect(await inView(id)).toBe(true);
  }
  await page.keyboard.press("Home");
  await expect(page.getByTestId("session-agent-claude")).toBeFocused();
  expect(await inView("session-agent-claude")).toBe(true);
  await page.keyboard.press("End");
  await expect(page.getByTestId(ids.at(-1)!)).toBeFocused();
  expect(await inView(ids.at(-1)!)).toBe(true);
});
