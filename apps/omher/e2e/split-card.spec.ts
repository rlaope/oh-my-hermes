// The TERMINALS split card: every split is one card on top of the TERMINALS list (no search typed), its cells at the
// panes' real places with each pane's CLI mark, title and last line; the members are not rows in their folders again.
// A cell click focuses that pane, a right-click opens the row menu, output makes the cell's edge orbit (still under
// reduced motion), a bell on a cell not in view makes it wait, the grip sets the card's height (kept after a restart,
// double-click goes back), a search draws rows instead, and a 1+3 split's tall cell stacks its text.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp } from "./term-find-helpers";
import { closeFromSidebar, dragRowOnto, type Side } from "./split-drag-helpers";

type Sessions = { startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null };
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
  // the card is on top of the list, above the folder groups
  const first = await page.getByTestId("session-list").evaluate((l) => l.firstElementChild?.getAttribute("data-testid"));
  expect(first).toBe("split-card");
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
  // the TERMINALS row menu, item for item
  await expect(menu.getByRole("menuitem")).toHaveCount(6);
  for (const id of ["session-rename", "session-reveal", "session-system-terminal", "session-copy-link", "session-new-here", "session-menu-close"]) await expect(menu.getByTestId(id)).toHaveCount(1);
  await page.getByTestId("session-rename").click();
  const input = cell(page, a).getByTestId("session-rename-input");
  await expect(input).toBeFocused();
  await input.fill("left side");
  await page.keyboard.press("Enter");
  await expect(cell(page, a).getByTestId("split-cell-name")).toHaveText("left side");
});

test("output makes a cell work with an orbiting edge, still under reduced motion; a bell on a cell not in view makes it wait", async ({ page }) => {
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
  await expect(cell(page, a)).toHaveAttribute("data-state", "wait", { timeout: 8000 });
  await expect(cell(page, b)).not.toHaveAttribute("data-state", "wait");
  await expect(cell(page, a).locator(".sc-wait")).toHaveCount(1);
});

test("the grip sets the card's height, kept after a restart; a double-click goes back to the default", async ({ page }) => {
  await openApp(page);
  const [a, b] = await sessions(page, ["/w/a", "/w/b"]);
  await splitWith(page, a, b);
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
  await page.keyboard.press("ArrowUp");
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
  await expect.poll(() => mapH(page)).toBe(126);
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
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "110");
  expect(await gripAx(page)).toEqual({ now: 110, min: 46, max: 240 });
  for (let i = 0; i < 9; i++) await page.keyboard.press("ArrowDown");
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
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(grip).toHaveAttribute("aria-valuenow", "94");
  // b moved below a: still one split of a and b, still 94
  await dragRowOnto(page, b, a, "down");
  await expect(pane(page, b)).toHaveAttribute("data-focused", "true");
  await expect(card(page)).toHaveAttribute("data-panes", "2");
  await expect(grip).toHaveAttribute("aria-valuenow", "94");
  // close b (the split ends while the close can be undone), then Undo: the card is back at its height
  await grip.focus();
  await page.keyboard.press("ArrowDown");
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

test("a 1+3 split gives its tall cell stacked text and its short cells text beside the mark", async ({ page }) => {
  await openApp(page);
  const [a, b, c, d] = await sessions(page, ["/w/a", "/w/b", "/w/c", "/w/d"]);
  await oneThree(page, [a, b, c, d]);
  await expect(cell(page, a)).toHaveAttribute("data-text", "stack");
  for (const id of [b, c, d]) await expect(cell(page, id)).toHaveAttribute("data-text", "beside");
});
