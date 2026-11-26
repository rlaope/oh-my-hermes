// The TERMINALS split card: every split is one card at the top of its first pane's folder (no search typed), its cells at the
// panes' real places with each pane's CLI mark, title and last line; the members are not rows in their folders again.
// A cell click focuses that pane, a right-click opens the row menu (Hand to <bot> included), output makes the cell's edge orbit (still under
// reduced motion), a bell on a cell not in view is quiet news while a bot's request to type makes it wait, the grip sets the card's height (kept after a restart,
// double-click goes back), a search draws rows instead, and every cell of a card takes one text layout on the rows' icon column.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp } from "./term-find-helpers";
import { closeFromSidebar, dragRowOnto, type Side } from "./split-drag-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null; linkOf(id: string): string | null };
const start = (page: Page, cwd: string, agent = "shell") => page.evaluate(([c, a]) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal(a, c), [cwd, agent] as const);
const ptyOf = async (page: Page, id: string) => {
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id)).not.toBeNull();
  return (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.ptyOf(i), id))!;
};
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const term = (page: Page, id: string) => page.locator(`[data-testid="terminal"][data-session="${id}"]`);
const pane = (page: Page, id: string) => page.locator(`[data-testid="split-pane"][data-session="${id}"]`);
const cell = (page: Page, id: string) => page.locator(`[data-testid="split-cell"][data-session="${id}"]`);
const card = (page: Page) => page.getByTestId("split-card");
const grip = (page: Page) => page.getByTestId("split-card-grip");
const mapH = (page: Page) => page.locator(".sc-map").first().evaluate((e) => Math.round(e.getBoundingClientRect().height));

async function sessions(page: Page, folders: string[], agent = "shell"): Promise<string[]> {
  const ids: string[] = [];
  for (const f of folders) {
    const id = await start(page, f, agent);
    await expect(term(page, id).locator(".xterm-rows")).toContainText("(mock)");
    ids.push(id);
  }
  return ids;
}

/** `pick`'s row (or cell) dragged onto `from`'s pane; `from` opens first when it is a row. */
async function splitWith(page: Page, from: string, pick: string, side: Side = "right") {
  if (await page.getByTestId(`session-${from}`).count()) await page.getByTestId(`session-${from}`).locator(".ss-open").click();
  await dragRowOnto(page, pick, from, side);
  await expect(pane(page, pick)).toHaveAttribute("data-focused", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("two sessions in a split are one card of two cells side by side, gone from their folder rows; a third stays a row; a cell click focuses that pane", async ({ page }) => {
  await openApp(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await splitWith(page, a, b);
  await expect(card(page)).toHaveCount(1);
  await expect(card(page)).toHaveAttribute("data-panes", "2");
  await expect(page.getByTestId("split-cell")).toHaveCount(2);
  // the card sits in its first pane's folder, under that folder's header and above its rows
  const group = page.locator('[data-testid="term-group"][data-cwd="/w/a"]');
  await expect(group.getByTestId("split-card")).toHaveCount(1);
  const order = await group.evaluate((g) => [...g.children].map((c) => c.getAttribute("data-testid")));
  expect(order.slice(0, 2)).toEqual(["term-group-head", "split-card"]);
  await expect(page.getByTestId(`session-${a}`)).toHaveCount(0);
  await expect(page.getByTestId(`session-${b}`)).toHaveCount(0);
  await expect(page.getByTestId(`session-${c}`)).toBeVisible();
  // side by side, the same top; each cell has the real mark (a shell) and its title
  const [ra, rb] = [(await cell(page, a).boundingBox())!, (await cell(page, b).boundingBox())!];
  expect(rb.x).toBeGreaterThan(ra.x + ra.width - 1);
  expect(Math.abs(rb.y - ra.y)).toBeLessThan(1);
  await expect(cell(page, a).getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  await expect(cell(page, b)).toHaveAttribute("data-focused", "true");
  await expect(cell(page, a)).toHaveAttribute("data-focused", "false");
  await expect(card(page)).not.toHaveAttribute("data-away", "true");
  // a click on a's cell focuses a's pane
  await cell(page, a).locator(".sc-open").click();
  await expect(cell(page, a)).toHaveAttribute("data-focused", "true");
  await expect(cell(page, b)).toHaveAttribute("data-focused", "false");
  await expect(pane(page, a)).toHaveAttribute("data-focused", "true");
  // opening c leaves the split out of view: the card is drawn dimmer
  await page.getByTestId(`session-${c}`).locator(".ss-open").click();
  await expect(card(page)).toHaveAttribute("data-away", "true");
  await expect(page.locator('[data-testid="split-cell"][data-focused="true"]')).toHaveCount(0);
});

test("a right-click on a cell opens the row menu and Rename renames that session", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
  await cell(page, a).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu).toBeVisible();
  // the TERMINALS row menu, item for item (Hand to <bot> too: a bot of this computer is online; e2e/hand-to-bot.spec.ts)
  await expect(menu.getByRole("menuitem")).toHaveCount(7);
  for (const id of ["session-rename", "session-reveal", "session-system-terminal", "session-copy-link", "session-hand", "session-new-here", "session-menu-close"]) await expect(menu.getByTestId(id)).toHaveCount(1);
  await page.getByTestId("session-rename").click();
  const input = cell(page, a).getByTestId("session-rename-input");
  await expect(input).toBeFocused();
  await input.fill("left side");
  await page.keyboard.press("Enter");
  await expect(cell(page, a).getByTestId("split-cell-name")).toHaveText("left side");
});

test("output makes a cell work with an orbiting edge, still under reduced motion; a bell on a cell not in view is quiet news", async ({ page }) => {
  await openApp(page);
  // a runs Claude Code (the mock's agent terminal takes `after <ms> bell`), b and c are shells
  const [a] = await sessions(page, ["/w/a"], "claude");
  const [b, c] = await sessions(page, ["/w/b", "/w/c"]);
  await splitWith(page, a, b);
  const pa = await ptyOf(page, a);
  // keep a printing so it stays busy while we read it
  const feed = setInterval(() => void out(page, pa, "working...\r\n").catch(() => {}), 300);
  try {
    await expect(cell(page, a)).toHaveAttribute("data-state", "work");
    await expect(cell(page, a).getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
    const orbit = cell(page, a).locator(".sc-orbit").first();
    await expect.poll(() => orbit.evaluate((e) => getComputedStyle(e).animationName)).not.toBe("none");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect.poll(() => orbit.evaluate((e) => getComputedStyle(e).animationName)).toBe("none");
    await page.emulateMedia({ reducedMotion: "no-preference" });
  } finally {
    clearInterval(feed);
  }
  // a rings later while another session is open (the split is not in view; a pane on screen sees its own bell)
  await cell(page, a).locator(".sc-open").click();
  await expect(pane(page, a)).toHaveAttribute("data-focused", "true");
  await page.waitForTimeout(2200);
  await term(page, a).locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("after 1200 bell");
  await page.keyboard.press("Enter");
  await page.getByTestId(`session-${c}`).locator(".ss-open").click();
  await expect(card(page)).toHaveAttribute("data-away", "true");
  // a ring is news (it may have finished): a soft accent edge breathing slowly, never the amber wait (demo 2026-11-23)
  await expect(cell(page, a)).toHaveAttribute("data-state", "news", { timeout: 8000 });
  await expect(cell(page, b)).not.toHaveAttribute("data-state", "news");
  await expect(cell(page, a).locator(".sc-wait")).toHaveCount(0);
  const news = cell(page, a).locator(".sc-news");
  await expect(news).toHaveCount(1);
  await expect.poll(() => news.evaluate((e) => getComputedStyle(e).animationName)).toBe("sc-breath");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => news.evaluate((e) => getComputedStyle(e).animationName)).toBe("none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
});

test("a bot's request to type into a cell's session is the amber wait, not news", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
  await expect.poll(() => page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.linkOf(i), a)).not.toBeNull();
  const link = (await page.evaluate((i) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.linkOf(i), a))!.slice(-10);
  // what the OMH tool writes into the session's inbox
  await page.evaluate((l) => ((window as unknown as { __omherMockInbox?: unknown[] }).__omherMockInbox ??= []).push({ id: `${Date.now()}`, link: l, prompt: "make test", from: "Kami", session: "s-1" }), link);
  await expect(cell(page, a)).toHaveAttribute("data-state", "wait", { timeout: 8000 });
  await expect(cell(page, a).locator(".sc-wait")).toHaveCount(1);
  await expect(cell(page, a).locator(".sc-news")).toHaveCount(0);
  await expect(cell(page, b)).not.toHaveAttribute("data-state", "wait");
});

test("the grip sets the card's height, kept after a restart; a double-click goes back to the default", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
  // keys go through the locator (it focuses the grip before each press): on a slow runner the pane a split just made
  // takes focus a moment later, and a bare keyboard press after grip.focus() would land in that pane
  const grip = page.getByTestId("split-card-grip");
  const h0 = await mapH(page);
  expect(h0).toBe(62);
  await expect(grip).toHaveAttribute("aria-valuenow", "62");
  const g = (await grip.boundingBox())!;
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2 + 40, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => mapH(page)).toBe(102);
  await expect(grip).toHaveAttribute("aria-valuenow", "102");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.splits"))).toContain('"mapH":102');
  // ArrowUp moves it 16 px
  await grip.focus();
  await grip.press("ArrowUp");
  await expect(grip).toHaveAttribute("aria-valuenow", "86");
  // a restart keeps it
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await expect(card(page)).toBeVisible();
  await expect.poll(() => mapH(page)).toBe(86);
  await page.getByTestId("split-card-grip").dblclick();
  await expect.poll(() => mapH(page)).toBe(62);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("omher.splits"))).not.toContain("mapH");
});

test("with a search typed no card is drawn and the split's sessions are rows again", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/alpha", "/w/beta"]);
  await splitWith(page, a, b);
  await expect(card(page)).toHaveCount(1);
  const search = page.getByTestId("bot-search");
  await search.fill("alpha");
  await expect(card(page)).toHaveCount(0);
  await expect(page.getByTestId(`session-${a}`)).toBeVisible();
  await expect(page.getByTestId(`session-${a}`).getByTestId("term-split-glyph")).toBeVisible();
  await search.fill("");
  await expect(card(page)).toHaveCount(1);
  await expect(page.getByTestId(`session-${a}`)).toHaveCount(0);
});

/** A 1+3 split: a tall on the left, b, c, d in even thirds on the right. */
async function oneThree(page: Page, ids: string[]) {
  const [a, b, c, d] = ids as [string, string, string, string];
  await splitWith(page, a, b, "right");
  await splitWith(page, b, c, "down");
  await splitWith(page, c, d, "down");
  await expect(card(page)).toHaveAttribute("data-panes", "4");
  // even them out: three thirds on the right
  await term(page, d).locator(".xterm-helper-textarea").focus();
  await page.keyboard.press((await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform))) ? "Meta+Control+Equal" : "Control+Alt+Equal");
  // its own height (a tall list may draw it shorter to fit, as a folder header now sits above it)
  await expect(card(page)).toHaveAttribute("data-map-h", "126");
}

/** The grip's value as the accessibility tree reports it (what a screen reader hears), with its range. */
async function gripAx(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  const { nodes } = (await cdp.send("Accessibility.getFullAXTree")) as { nodes: { role?: { value: string }; name?: { value: string }; value?: { value: unknown }; properties?: { name: string; value: { value: unknown } }[] }[] };
  const n = nodes.find((x) => x.role?.value === "separator" && String(x.name?.value ?? "").startsWith("Card height"));
  const prop = (k: string) => n?.properties?.find((p) => p.name === k)?.value.value;
  await cdp.detach();
  return { now: Number(n?.value?.value), min: Number(prop("valuemin")), max: Number(prop("valuemax")) };
}

test("the grip tells assistive technology its real range, and its value follows the keys past 100 up to 240", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
  const grip = page.getByTestId("split-card-grip");
  await expect(grip).toHaveAttribute("aria-valuemin", "46");
  await expect(grip).toHaveAttribute("aria-valuemax", "240");
  await grip.focus();
  // 62 + 3 × 16 = 110, above the 0–100 a range-less separator falls back to
  for (let i = 0; i < 3; i++) await grip.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
  expect(await gripAx(page)).toEqual({ now: 110, min: 46, max: 240 });
  for (let i = 0; i < 9; i++) await grip.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "240");
  expect((await gripAx(page)).now).toBe(240);
});

test("a split that ends while its grip is held saves nothing, and a later window blur leaves the next split's height alone", async ({ page }) => {
  await openApp(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await splitWith(page, a, b);
  const grip = page.getByTestId("split-card-grip");
  await expect(grip).toHaveAttribute("aria-valuenow", "62");
  // hold the grip 31 px down, then the split ends under the held pointer (the pane's Leave)
  const g = (await grip.boundingBox())!;
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2 + 31, { steps: 5 });
  await expect(grip).toHaveAttribute("aria-valuenow", "93");
  await page.evaluate(async (id) => (await import("/src/sessions/SplitView.tsx" as string)).leaveSplit(id), b);
  await expect(grip).toHaveCount(0);
  await page.mouse.up();
  // a and c make a new split at its default height; the window losing focus must not hand it the old drag's height
  await splitWith(page, a, c);
  await expect(grip).toHaveAttribute("aria-valuenow", "62");
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await page.waitForTimeout(100);
  await expect(grip).toHaveAttribute("aria-valuenow", "62");
  expect(await page.evaluate(() => localStorage.getItem("omher.splits"))).not.toContain("mapH");
});

test("a card keeps its height when a pane moves within its split and when a closed cell comes back with Undo", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => ((window as unknown as { __omherCloseGraceMs: number }).__omherCloseGraceMs = 10_000));
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await splitWith(page, a, b);
  const grip = page.getByTestId("split-card-grip");
  await grip.focus();
  await grip.press("ArrowDown");
  await grip.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "94");
  // b moved below a: still one split of a and b, still 94
  await dragRowOnto(page, b, a, "down");
  await expect(pane(page, b)).toHaveAttribute("data-focused", "true");
  await expect(card(page)).toHaveAttribute("data-panes", "2");
  await expect(grip).toHaveAttribute("aria-valuenow", "94");
  // close b (the split ends while the close can be undone), then Undo: the card is back at its height
  await grip.focus();
  await grip.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
  await closeFromSidebar(page, b);
  await expect(card(page)).toHaveCount(0);
  await page.getByTestId(`close-toast-${b}`).getByTestId("close-toast-undo").click();
  await expect(page.getByTestId("split-cell")).toHaveCount(2);
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
  // a three-pane split: a cell closes and comes back, the height stays its own throughout
  await splitWith(page, a, c);
  await expect(card(page)).toHaveAttribute("data-panes", "3");
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
  await closeFromSidebar(page, b);
  await expect(page.getByTestId("split-cell")).toHaveCount(2);
  await page.getByTestId(`close-toast-${b}`).getByTestId("close-toast-undo").click();
  await expect(page.getByTestId("split-cell")).toHaveCount(3);
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
});

test("a long name in a tall cell keeps its start and ends in an ellipsis inside the cell", async ({ page }) => {
  await openApp(page);
  const [a, b, c, d] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d"]);
  await oneThree(page, [a, b, c, d]);
  await expect(cell(page, a)).toHaveAttribute("data-text", "stack");
  const name = "VISIBLE-PREFIX — implement a long descriptive title for the review split";
  await cell(page, a).click({ button: "right" });
  await page.getByTestId("session-rename").click();
  await cell(page, a).getByTestId("session-rename-input").fill(name);
  await page.keyboard.press("Enter");
  await expect(cell(page, a).getByTestId("split-cell-name")).toHaveText(name);
  const fit = await cell(page, a).evaluate((e) => {
    const n = e.querySelector(".sc-n") as HTMLElement;
    const c = e.getBoundingClientRect();
    const r = n.getBoundingClientRect();
    return { scroll: n.scrollWidth, client: n.clientWidth, cellW: c.width, left: r.left - c.left, right: c.right - r.right, overflow: getComputedStyle(n).textOverflow };
  });
  // the title is cut (an ellipsis at its end), no wider than the cell, and starts inside it (its prefix shows)
  expect(fit.scroll).toBeGreaterThan(fit.client);
  expect(fit.client).toBeLessThanOrEqual(fit.cellW);
  expect(fit.left).toBeGreaterThanOrEqual(0);
  expect(fit.right).toBeGreaterThanOrEqual(0);
  expect(fit.overflow).toBe("ellipsis");
});

test("in a right-to-left document the card mirrors as the main split does: the tall cell is on its pane's side", async ({ page }) => {
  await openApp(page);
  const [a, b, c, d] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d"]);
  await oneThree(page, [a, b, c, d]);
  // the side of its box each one is on: the tall cell against the short ones, the tall pane against the short ones
  const sides = async () => {
    const [ca, cb, pa, pb] = await Promise.all([cell(page, a).boundingBox(), cell(page, b).boundingBox(), pane(page, a).boundingBox(), pane(page, b).boundingBox()]);
    return { card: ca!.x < cb!.x ? "start-left" : "start-right", main: pa!.x < pb!.x ? "start-left" : "start-right" };
  };
  expect(await sides()).toEqual({ card: "start-left", main: "start-left" });
  await page.evaluate(() => (document.documentElement.dir = "rtl"));
  await expect.poll(sides).toEqual({ card: "start-right", main: "start-right" });
  // the cells stay inside the card
  const [box, cellA] = [(await page.locator(".sc-map").boundingBox())!, (await cell(page, a).boundingBox())!];
  expect(cellA.x).toBeGreaterThanOrEqual(box.x - 0.5);
  expect(cellA.x + cellA.width).toBeLessThanOrEqual(box.x + box.width + 0.5);
});

test("a tall card in a short TERMINALS gives way so it is never hidden whole: 1280×600, and 1280×700 with the divider low", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 700 });
  for (const bot of ["kami", "friren", "default", "omh-tui"]) await mock("mock.threads", { bot, threads: Array.from({ length: 5 }, (_, i) => ({ title: `Review thread ${i + 1}`, ago: 600 + i })) });
  await openApp(page);
  await expect(page.locator(".th-row")).toHaveCount(20);
  const [a, b, c, d] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d", "/w/e", "/w/f", "/w/g", "/w/h", "/w/i", "/w/j"]);
  await oneThree(page, [a!, b!, c!, d!]);
  const grip = page.getByTestId("split-card-grip");
  await grip.focus();
  for (let i = 0; i < 8; i++) await grip.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "240");
  /** Every cell's centre, hit-tested: the cell it lands on (null when the clip or another element hides it), and how
   *  much of the card the list's clip leaves showing. */
  const seen = () =>
    page.evaluate(() => {
      const list = document.querySelector<HTMLElement>('[data-testid="session-list"]')!;
      // the card sits in its folder (/w/a, the oldest, listed last): scroll that folder to the list's top
      list.scrollTop = 0;
      const group = document.querySelector(".split-card")!.closest<HTMLElement>('[data-testid="term-group"]')!;
      list.scrollTop = group.getBoundingClientRect().top - list.getBoundingClientRect().top;
      const lb = list.getBoundingClientRect();
      const cut = Number(/inset\(0px 0px ([\d.]+)px/.exec(list.style.clipPath)?.[1] ?? 0);
      const hits = [...document.querySelectorAll<HTMLElement>('[data-testid="split-cell"]')].map((e) => {
        const r = e.getBoundingClientRect();
        const [x, y] = [r.left + r.width / 2, r.top + r.height / 2];
        const at = y < lb.bottom - cut ? document.elementFromPoint(x, y) : null;
        return at?.closest<HTMLElement>('[data-testid="split-cell"]')?.dataset.session === e.dataset.session ? e.dataset.session : (at?.className ?? null);
      });
      // the cells (the map): the grip under them may sit in the chevron's band, which is clipped so the chevron is
      // never drawn over the card
      const map = document.querySelector(".split-card .sc-map")!.getBoundingClientRect();
      return { hits, shown: Math.max(0, Math.min(map.bottom, lb.bottom - cut) - map.top), card: map.height };
    });
  const check = async () => {
    await page.waitForTimeout(250);
    const v = await seen();
    expect(v.hits.filter((h) => [a, b, c, d].includes(h as string)).length, JSON.stringify(v)).toBeGreaterThan(0);
    expect(v.shown, JSON.stringify(v)).toBeGreaterThan(0);
    return v;
  };
  await check();
  await page.setViewportSize({ width: 1280, height: 600 });
  const short = await check();
  // the card gave way to the room: every cell is reachable and shown whole, and the saved height is still 240
  expect(short.hits, JSON.stringify(short)).toEqual([a, b, c, d]);
  expect(short.shown, JSON.stringify(short)).toBe(short.card);
  await expect(grip).toHaveAttribute("aria-valuenow", "240");
  expect(await page.evaluate(() => localStorage.getItem("omher.splits"))).toContain('"mapH":240');
  // 1280×700 with BOTS | TERMINALS dragged low
  await page.setViewportSize({ width: 1280, height: 700 });
  const side = page.getByTestId("side-split");
  for (let i = 0; i < 16; i++) await side.press("ArrowDown");
  await check();
});

/** Each cell's text layout (data-text), and whether it shows a last line. */
const looks = (page: Page) => page.locator('[data-testid="split-cell"]').evaluateAll((els) => els.map((e) => ({ id: (e as HTMLElement).dataset.session, text: (e as HTMLElement).dataset.text, line: !!e.querySelector(".sc-l") })));

test("a 1+3 split lays every cell out the same way: one text layout per card, never a stacked cell beside cells with text beside the mark", async ({ page }) => {
  await openApp(page);
  const [a, b, c, d] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d"]);
  await oneThree(page, [a, b, c, d]);
  for (const id of [a, b, c, d]) await expect(cell(page, id)).toHaveAttribute("data-text", "stack");
});

test("one tall cell and two stacked ones (1280x820, and capped short at 900x600) share one layout; the right cells' mark and title start where the left cell's do", async ({ page }) => {
  await openApp(page);
  const [a, b, c] = await sessions(page, ["/w/a", "/w/b", "/w/c"]);
  await splitWith(page, a, b, "right");
  await splitWith(page, b, c, "down");
  await expect(card(page)).toHaveAttribute("data-panes", "3");
  const one = async () => {
    const l = await looks(page);
    expect(new Set(l.map((x) => x.text)).size, JSON.stringify(l)).toBe(1);
    expect(new Set(l.map((x) => x.line)).size, JSON.stringify(l)).toBe(1);
    // every cell's content starts the same distance in from its own left edge
    const inset = await page.locator('[data-testid="split-cell"]').evaluateAll((els) => els.map((e) => Math.round(e.querySelector(".trm")!.getBoundingClientRect().left - e.getBoundingClientRect().left)));
    expect(new Set(inset).size, JSON.stringify(inset)).toBe(1);
    return l[0]!.text;
  };
  await expect.poll(async () => (await looks(page)).length).toBe(3);
  expect(await one()).toBe("stack");
  // a short window caps the card (46 px): every cell is one line, none keeps two
  await page.setViewportSize({ width: 900, height: 600 });
  const grip = page.getByTestId("split-card-grip");
  await grip.focus();
  for (let i = 0; i < 3; i++) await grip.press("ArrowUp");
  await expect(grip).toHaveAttribute("aria-valuenow", "46");
  await expect.poll(async () => [...new Set((await looks(page)).map((x) => x.text))]).toEqual(["line"]);
  expect(await one()).toBe("line");
  // a one-line cell's face is still the whole cell: a right-click anywhere on it is the row menu
  const faces = await page.locator('[data-testid="split-cell"]').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height - e.querySelector(".sc-open")!.getBoundingClientRect().height)));
  expect(faces).toEqual([0, 0, 0]);
  const box = (await cell(page, a).boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height - 4, { button: "right" });
  await expect(page.getByTestId("session-row-menu")).toBeVisible();
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
});

test("at the default grip no CLI's name is cut, and the cells' marks sit on the TERMINALS rows' icon column at the rows' size", async ({ page }) => {
  await openApp(page);
  const [a] = await sessions(page, ["/w/a"], "claude");
  const [b, c] = await sessions(page, ["/w/a", "/w/a"]);
  await splitWith(page, a, b);
  await expect(grip(page)).toHaveAttribute("aria-valuenow", "62");
  await expect(cell(page, a).getByTestId("split-cell-name")).toHaveText("Claude Code");
  const fit = await page.locator('[data-testid="split-cell"]').evaluateAll((els) =>
    els.map((e) => {
      const n = e.querySelector<HTMLElement>(".sc-n")!;
      const m = e.querySelector(".trm")!.getBoundingClientRect();
      return { name: n.textContent, scroll: n.scrollWidth, client: n.clientWidth, markX: Math.round(m.left), markW: Math.round(m.width) };
    }),
  );
  for (const f of fit) expect(f.scroll, JSON.stringify(fit)).toBeLessThanOrEqual(f.client);
  const row = (await page.getByTestId(`session-${c}`).getByTestId("term-row-mark").boundingBox())!;
  // the first cell's mark on the row's mark, at the row's 16 px
  expect(Math.abs(fit[0]!.markX - Math.round(row.x)), JSON.stringify({ fit, row })).toBeLessThanOrEqual(1);
  expect(fit.map((f) => f.markW)).toEqual([16, 16]);
  expect(Math.round(row.width)).toBe(16);
});

test("a shell cell's last line is never its own prompt", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/api-server", "/w/api-server"]);
  await splitWith(page, a, b);
  // the mock shell printed its first line, then sits at `you@mock api-server % `
  await expect(cell(page, a).locator(".sc-l")).toHaveText("(mock) login shell in /w/api-server");
  for (const id of [a, b]) await expect(cell(page, id)).not.toContainText("you@mock");
  // what is typed after the prompt is what it shows
  await out(page, await ptyOf(page, a), "\x1b[2J\x1b[Hyou@mock api-server % make test\r\nyou@mock api-server % ");
  await expect(cell(page, a).locator(".sc-l")).toHaveText("make test");
});

test("a still frame of a working cell shows a whole ring with a short head, never a segment that reads as a fill level; under reduced motion only the ring, still", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
  const pa = await ptyOf(page, a);
  const feed = setInterval(() => void out(page, pa, "working...\r\n").catch(() => {}), 300);
  try {
    await expect(cell(page, a)).toHaveAttribute("data-state", "work");
    const ring = cell(page, a).locator(".sc-ring");
    const head = cell(page, a).locator(".sc-orbit");
    await expect(ring).toHaveCount(1);
    await expect(head).toHaveCount(1);
    const g = await cell(page, a).evaluate((e) => {
      const ring = getComputedStyle(e.querySelector(".sc-ring")!);
      const head = e.querySelector(".sc-orbit")!;
      return { ringDash: ring.strokeDasharray, ringOpacity: Number(ring.opacity), headDash: head.getAttribute("stroke-dasharray"), heads: e.querySelectorAll(".sc-orbit").length };
    });
    // the ring is the whole edge (no dash), the head at most 6 % of it, one head only
    expect(g.ringDash).toBe("none");
    expect(g.ringOpacity).toBeGreaterThan(0);
    expect(Number(g.headDash!.split(" ")[0])).toBeLessThanOrEqual(6);
    expect(g.heads).toBe(1);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(head).toBeHidden();
    await expect.poll(() => ring.evaluate((e) => getComputedStyle(e).animationName)).toBe("none");
    await expect(ring).toBeVisible();
  } finally {
    clearInterval(feed);
    await page.emulateMedia({ reducedMotion: "no-preference" });
  }
});
