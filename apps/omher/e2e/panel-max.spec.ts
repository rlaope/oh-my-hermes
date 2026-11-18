// The side panel maximises IN PLACE: the same panel grows to every pixel right of the sidebar, the chat column folds
// to 0 (still mounted: its draft stays), the sidebar never moves. Restore brings back the exact width the tab had.
// Controls: the tab row's button, a double click on the tab row, ⌘⇧G, Esc; closing the panel restores too. No
// dialog, no second header. Set OMHER_SHOTS=<dir> to also write the panelmax-*.png shots.
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
    ws.send(JSON.stringify({ id: "m1", op, ...params }));
  });
  ws.close();
}

async function mod(page: Page) {
  return (await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform))) ? "Meta" : "Control";
}

/** Rects read in one frame: sidebar, chat column, panel. */
const rects = (page: Page) =>
  page.evaluate(() => {
    const r = (id: string) => {
      const b = document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect();
      return { x: b.x, right: b.right, width: b.width };
    };
    const main = document.querySelector(".main")!.getBoundingClientRect();
    return { side: r("sidebar"), panel: r("details"), main: { x: main.x, width: main.width }, vw: window.innerWidth };
  });
const panelW = async (page: Page) => Math.round((await rects(page)).panel.width);
/** Every CSS transition running now has ended. */
const settled = (page: Page) =>
  page.evaluate(() =>
    Promise.all(document.getAnimations().filter((a) => a instanceof CSSTransition).map((a) => a.finished.catch(() => null))).then(() => undefined),
  );

async function openPanel(page: Page, tab: "details" | "runs" | "terminal" = "runs") {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  if (!/\bpanel-open\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "")) await page.getByTestId("places").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await page.getByTestId(`panel-tab-${tab}`).click();
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", tab);
  await settled(page);
}

async function expectMaxed(page: Page) {
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
  await expect
    .poll(async () => {
      const r = await rects(page);
      return [Math.abs(r.panel.x - r.side.right) <= 1, Math.abs(r.panel.right - r.vw) <= 1, Math.round(r.main.width)];
    })
    .toEqual([true, true, 0]);
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Plans: the tab row's button maximises the panel in place; the sidebar stays; restore returns the exact width and the draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "details");
  await page.getByTestId("composer").fill("half-written thought");
  await page.getByTestId("panel-tab-runs").click();
  await settled(page);
  const before = await panelW(page);
  const btn = page.getByTestId("panel-max");
  await expect(btn).toHaveAttribute("title", "Expand");
  await btn.click();
  await expectMaxed(page);
  // one header: the panel's own tab row; no dialog over the chat, no resizer
  await expect(page.locator("[role=dialog]")).toHaveCount(0);
  await expect(page.getByTestId("runs-full")).toHaveCount(0);
  await expect(page.getByTestId("panel-resizer")).toHaveCount(0);
  await expect(btn).toHaveAttribute("title", "Restore");
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  // the chat is still mounted, hidden and inert
  await expect(page.locator(".main")).toHaveAttribute("inert", "");
  await expect(page.getByTestId("composer")).toHaveCount(1);
  // the Plans graph renders at the bigger width: the full drawing with its zoom tools
  await expect(page.getByTestId("run-graph-box")).toHaveClass(/\bmax\b/);
  await expect(page.getByTestId("run-zoom")).toBeVisible();
  // the sidebar is visible and clickable
  await expect(page.getByTestId("sidebar")).toBeVisible();
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // restore: back to the width it had before, and the draft is still in the composer
  await page.getByTestId("panel-max").click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await settled(page);
  await expect.poll(() => panelW(page)).toBe(before);
  await expect(page.locator(".main")).not.toHaveAttribute("inert", "");
  await expect(page.getByTestId("composer")).toHaveValue("half-written thought");
  await expect(page.getByTestId("panel-resizer")).toHaveCount(1);
});

test("Ctrl+` while Plans is maximised restores the panel to its width and shows the terminal with the keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "runs");
  const before = await panelW(page);
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(page.locator(".main")).not.toHaveAttribute("inert", "");
  await settled(page);
  await expect.poll(() => panelW(page)).toBe(before);
  const box = (await page.getByTestId("termpanel").boundingBox())!;
  expect(box.width).toBeGreaterThan(200);
  await expect
    .poll(() => page.evaluate(() => !!document.activeElement?.closest('[data-testid="termpanel-terminal"]')))
    .toBe(true);
  // hiding it again leaves the panel at its width (not maximised again)
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeHidden();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
});

test("a dragged width comes back exactly after maximise and restore, for Details", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "details");
  const h = (await page.getByTestId("panel-resizer").boundingBox())!;
  await page.mouse.move(h.x + 3, h.y + 200);
  await page.mouse.down();
  await page.mouse.move(h.x + 3 - 77, h.y + 200, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => panelW(page)).toBe(377);
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  // maximising saves nothing
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.panelWidth") || "null"))).toEqual({ details: 377 });
  await page.getByTestId("panel-max").click();
  await settled(page);
  await expect.poll(() => panelW(page)).toBe(377);
});

test("⌘⇧G toggles (opening Plans when the panel is closed), Esc restores, double-click on the tab row toggles, closing restores", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  const m = await mod(page);
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "runs");
  await expectMaxed(page);
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  // the panel open on another tab: ⌘⇧G maximises that tab
  await page.getByTestId("panel-tab-terminal").click();
  await page.keyboard.press(`${m}+Shift+G`);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "terminal");
  await expectMaxed(page);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  // double-click on the free part of the tab row. The class flips at once but the restore slides the row for ~0.2s:
  // the free space is measured once the row has stopped moving, never under a row still in motion (F7)
  await settled(page);
  const row = page.getByTestId("panel-tabs");
  const b = (await row.boundingBox())!;
  const tabsRight = await row.evaluate((e) => Math.max(...[...e.querySelectorAll(".pn-tab")].map((t) => t.getBoundingClientRect().right)));
  await page.mouse.dblclick(tabsRight + 12, b.y + b.height / 2);
  await expectMaxed(page);
  await settled(page);
  await page.mouse.dblclick(tabsRight + 12, b.y + b.height / 2);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  // a double click on a tab only picks the tab
  await page.getByTestId("panel-tab-details").dblclick();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  // closing the panel restores: it opens again at its own width
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await page.getByRole("button", { name: "Close details" }).click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
});

/** The free point of the tab row right of its last tab, read now (also mid-slide). */
const freeRowPoint = (page: Page) =>
  page.getByTestId("panel-tabs").evaluate((e) => {
    const b = e.getBoundingClientRect();
    const right = Math.max(...[...e.querySelectorAll(".pn-tab")].map((t) => t.getBoundingClientRect().right));
    const x = right + 12;
    const y = b.y + b.height / 2;
    const hit = document.elementFromPoint(x, y);
    return { x, y, inRow: !!hit?.closest('[data-testid="panel-tabs"]'), moving: document.getAnimations().some((a) => a instanceof CSSTransition) };
  });
const isMaxed = async (page: Page) => /\bpanel-max\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "");

/** Each slide round starts the same way, whatever the last one's press hit (a control is the person's: the model
 *  picker may be open, the places chip may have closed the panel): picker closed, panel open on Plans, maximised. */
async function maxForRound(page: Page) {
  if (await page.getByTestId("model-pop").isVisible()) await page.keyboard.press("Escape");
  await expect(page.getByTestId("model-pop")).toBeHidden();
  if (!/\bpanel-open\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "")) await page.getByTestId("places").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-open\b/);
  await page.getByTestId("panel-tab-runs").click();
  if (!(await isMaxed(page))) await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await settled(page);
}

/** Every pointerdown from now on: where it landed, and whether on an interactive control outside the tab row. */
const recordPresses = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __presses: unknown[] };
    w.__presses = [];
    const ctl = 'button, a[href], input, textarea, select, [role="button"], [role="menuitem"], [role="tab"], [role="combobox"], [role="link"], [contenteditable], [tabindex]:not([tabindex="-1"])';
    window.addEventListener(
      "pointerdown",
      (e) => {
        const t = e.target as Element;
        w.__presses.push({
          id: t.closest("[data-testid]")?.getAttribute("data-testid") ?? null,
          row: !!t.closest('[data-testid="panel-tabs"]'),
          control: !t.closest('[data-testid="panel-tabs"]') && !!t.closest(ctl),
          model: !!t.closest('[data-testid="model-pill"]'),
          places: !!t.closest('[data-testid="places"]'),
          at: performance.now(),
        });
      },
      true,
    );
  });
type Press = { id: string | null; row: boolean; control: boolean; model: boolean; places: boolean; at: number };
const presses = (page: Page) => page.evaluate(() => (window as unknown as { __presses: Press[] }).__presses.splice(0));

// A control in the chat header the person actually hits during the restore slide is theirs (the model pill opens
// its picker, the places chip closes the panel), at every delay; only the header's bare background can be claimed by
// a double-click aimed at the tab row. The delay counts from the Esc keydown; the point is hit-tested right before a
// real mouse click, and only a round whose real pointerdown landed inside the control counts. Still under the panel at
// the delay (a loaded runner starts the slide late), the round clicks at the first moment after the delay the control
// shows: the earliest press the slide could steal. A press that landed elsewhere is sampled again: 20 actual hits,
// 0 lost.
for (const control of ["model-pill", "places"] as const)
  for (const delay of [120, 180, 220, 280, 350, 450])
    test(`a real click on the header's ${control} ${delay}ms after Esc is never stolen by the slide, 20 actual hits`, async ({ page }) => {
      // 20 actual hits; a round only misses when the press lands elsewhere, so 60 rounds is plenty
      test.setTimeout(300_000);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openPanel(page, "runs");
      await recordPresses(page);
      const own = (h: Press) => (control === "model-pill" ? h.model : h.places);
      const hits: { round: number; after: number; worked: boolean }[] = [];
      const left: { round: number; why: string }[] = [];
      for (let round = 0; hits.length < 20 && round < 60; round++) {
        await maxForRound(page);
        await page.evaluate(() => {
          const w = window as unknown as { __esc: number };
          w.__esc = 0;
          window.addEventListener("keydown", (e) => e.key === "Escape" && (w.__esc = performance.now()), { capture: true, once: true });
        });
        await presses(page);
        await page.keyboard.press("Escape");
        const p = await page.getByTestId(control).evaluate(async (e, delay) => {
          const esc = (window as unknown as { __esc: number }).__esc;
          while (performance.now() - esc < delay) await new Promise((r) => setTimeout(r, 1));
          // from the delay on, the first moment the control shows (the slide is over well within 2 s)
          while (performance.now() - esc < delay + 2000) {
            const b = e.getBoundingClientRect();
            for (const y of [b.y + b.height / 2, b.y + 2, b.bottom - 2])
              for (let x = b.x + 2; x < b.right - 1; x += 2) if (e.contains(document.elementFromPoint(x, y))) return { x, y };
            await new Promise((r) => setTimeout(r, 1));
          }
          return null;
        }, delay);
        if (!p) {
          left.push({ round, why: "occluded" });
          continue;
        }
        await page.mouse.click(p.x, p.y);
        const [hit] = await presses(page);
        if (!hit || !own(hit)) {
          left.push({ round, why: `pressed ${hit?.id ?? "nothing"}` });
          continue;
        }
        const after = Math.round(hit.at - (await page.evaluate(() => (window as unknown as { __esc: number }).__esc)));
        await page.waitForTimeout(450);
        const worked =
          control === "model-pill"
            ? await page.getByTestId("model-pop").isVisible()
            : !/\bpanel-open\b/.test((await page.getByTestId("window").getAttribute("class")) ?? "");
        hits.push({ round, after, worked });
      }
      const summary = JSON.stringify({ control, delay, hits, left });
      expect(hits.filter((h) => !h.worked), summary).toEqual([]);
      expect(hits.length, summary).toBe(20);
    });

/** What (x, y) shows now: the tab row, a control in the chat header, or its bare background. */
const CONTROL = 'button, a[href], input, textarea, select, [role="button"], [role="menuitem"], [role="tab"], [role="combobox"], [role="link"], [contenteditable], [tabindex]:not([tabindex="-1"])';
/** Esc restores; returns once (x, y), free tab-row space while maximised, shows `want` (checked every frame). */
async function escUntil(page: Page, x: number, y: number, want: "bare" | "control") {
  await page.keyboard.press("Escape");
  await page.waitForFunction(
    ([x, y, want, ctl]) => {
      const hit = document.elementFromPoint(x as number, y as number);
      const kind = !hit || hit.closest('[data-testid="panel-tabs"]') ? "row" : hit.closest(ctl as string) ? "control" : "bare";
      return kind === want;
    },
    [x, y, want, CONTROL] as const,
    { polling: "raf", timeout: 2000 },
  );
}

// The restore-slide double-click attack (first press on the row's free space 25ms after Esc, the row slides away
// before the second) aimed below the header's controls, so the second press lands on the chat header's bare
// background, never a control: still maximises, 10 of 10. The chosen trade-off, next test: a press that lands on a
// header control (the model pill) after the row left is the control's, and that double-click does not toggle.
test("restore-slide double-click whose second press lands on bare header background maximises 10 of 10", async ({ page }) => {
  test.setTimeout(90_000); // 10 slide rounds on a slow runner
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "runs");
  await recordPresses(page);
  const y = (await page.getByTestId("panel-tabs").evaluate((e) => e.getBoundingClientRect().bottom)) - 5;
  for (let i = 0; i < 10; i++) {
    await maxForRound(page);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(25);
    const p = await freeRowPoint(page);
    expect(p.inRow, `round ${i}: first press on the tab row`).toBe(true);
    await presses(page);
    await page.mouse.dblclick(p.x, y, { delay: 45 });
    const hits = await presses(page);
    // the first press may already find the row gone, the second the row still there: never a control
    expect(hits.map((h) => h.control), `round ${i}: ${JSON.stringify(hits)}`).toEqual([false, false]);
    await page.waitForTimeout(400);
    expect(await isMaxed(page), `round ${i}: double-click during the slide maximised`).toBe(true);
  }
});

test("trade-off: where the model pill slid over the row's old free space, the pill wins and the double-click does not toggle", async ({ page }) => {
  test.setTimeout(90_000); // 10 slide rounds on a slow runner
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "runs");
  await recordPresses(page);
  // the pill's place once restored: free tab-row space while maximised
  const p = await page.getByTestId("model-pill").evaluate((e) => {
    const b = e.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  });
  for (let i = 0; i < 5; i++) {
    await maxForRound(page);
    expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('[data-testid="panel-tabs"]'), [p.x, p.y] as const)).toBe(true);
    await escUntil(page, p.x, p.y, "control");
    await presses(page);
    await page.mouse.dblclick(p.x, p.y, { delay: 45 });
    const [first] = await presses(page);
    await page.waitForTimeout(400);
    expect(first.model, `round ${i}: ${JSON.stringify(first)}`).toBe(true);
    expect(await isMaxed(page), `round ${i}: the pill won, no toggle`).toBe(false);
    await settled(page);
  }
});

// Where the second press lands on a header control the slide brought under the pointer (the model pill), the control
// wins and the pair does not toggle (the chosen trade-off, above); every other round maximises, 10 of 10. About two
// rounds in three land on the pill at this point, so the 10 qualifying rounds take up to 60.
test("a person's double-click on the tab row during the restore slide still maximises, 10 of 10 (real mouse)", async ({ page }) => {
  test.setTimeout(300_000); // up to 60 slide rounds on a slow runner
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPanel(page, "runs");
  await recordPresses(page);
  let maxed = 0;
  for (let i = 0; maxed < 10 && i < 60; i++) {
    await maxForRound(page);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(25);
    // the free row space under the pointer at the first press; the row slides away before the second
    const p = await freeRowPoint(page);
    expect(p.inRow, `round ${i}: first press on the tab row`).toBe(true);
    await presses(page);
    await page.mouse.dblclick(p.x, p.y, { delay: 45 });
    const hits = await presses(page);
    await page.waitForTimeout(400);
    if (hits.some((h) => h.control)) {
      expect(await isMaxed(page), `round ${i}: a press on a control ${JSON.stringify(hits)} is the control's`).toBe(false);
      continue;
    }
    expect(await isMaxed(page), `round ${i}: double-click during the slide maximised`).toBe(true);
    maxed++;
  }
  expect(maxed).toBe(10);
});

test("tab row: a settled double-click toggles once; one click, or two clicks 800ms apart, never toggles", async ({ page }) => {
  await openPanel(page, "runs");
  const p = await freeRowPoint(page);
  expect(p.moving).toBe(false);
  await page.mouse.dblclick(p.x, p.y);
  await expectMaxed(page);
  await settled(page);
  const q = await freeRowPoint(page);
  await page.mouse.dblclick(q.x, q.y);
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
  await settled(page);
  const r = await freeRowPoint(page);
  await page.mouse.click(r.x, r.y);
  await page.waitForTimeout(600);
  expect(await isMaxed(page)).toBe(false);
  await page.mouse.click(r.x, r.y);
  await page.waitForTimeout(800);
  await page.mouse.click(r.x, r.y);
  await page.waitForTimeout(600);
  expect(await isMaxed(page)).toBe(false);
  // a double-click on a tab only picks the tab
  await page.getByTestId("panel-tab-details").dblclick();
  await page.waitForTimeout(300);
  expect(await isMaxed(page)).toBe(false);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "details");
});

test("Esc in a field inside the panel does not restore it", async ({ page }) => {
  await openPanel(page, "details");
  await page.getByTestId("panel-max").click();
  await expectMaxed(page);
  await page.evaluate(() => {
    const i = document.createElement("input");
    i.id = "probe";
    document.querySelector("[data-testid=details-panel]")!.appendChild(i);
  });
  await page.locator("#probe").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
});

test("the graph's expand button maximises the panel on Plans, and restores it", async ({ page }) => {
  await openPanel(page, "runs");
  const expand = page.getByTestId("graph-expand");
  await expect(expand).toHaveAttribute("title", /^Full view (⌘⇧G|Ctrl\+Shift\+G)$/);
  await expand.click();
  await expectMaxed(page);
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "runs");
  await expect(expand).toHaveAttribute("title", /^Restore (⌘⇧G|Ctrl\+Shift\+G)$/);
  await expand.click();
  await expect(page.getByTestId("window")).not.toHaveClass(/\bpanel-max\b/);
});

test("eases in about 180ms; reduced motion: no transition", async ({ browser }) => {
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    const ctx = await browser.newContext({ reducedMotion, viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await openPanel(page, "details");
    await page.getByTestId("panel-max").click();
    const t = await page.getByTestId("window").evaluate((e) => [getComputedStyle(e).transitionDuration, getComputedStyle(e).transitionProperty]);
    // reduced motion: base.css forces every transition to 0.001ms, i.e. none a person can see
    if (reducedMotion === "reduce") expect(parseFloat(t[0]) * (t[0].endsWith("ms") ? 1 : 1000)).toBeLessThan(1);
    else expect(t).toEqual(["0.18s", "grid-template-columns"]);
    await expectMaxed(page);
    await ctx.close();
  }
});

test("under 1100px the overlay panel maximises to the window less the sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 760 });
  await openPanel(page, "details");
  await page.getByTestId("panel-max").click();
  await expect(page.getByTestId("window")).toHaveClass(/\bpanel-max\b/);
  await expect
    .poll(async () => {
      const r = await rects(page);
      return [Math.abs(r.panel.x - r.side.right) <= 1, Math.abs(r.panel.right - r.vw) <= 1];
    })
    .toEqual([true, true]);
  await expect(page.getByTestId("sidebar")).toBeVisible();
});

test("shots: normal, maximised Plans, maximised Details (dark) and maximised Plans (light)", async ({ browser }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  mkdirSync(SHOTS, { recursive: true });
  const shot = async (scheme: "dark" | "light", name: string, tab: "details" | "runs", max: boolean) => {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await openPanel(page, tab);
    if (max) {
      await page.getByTestId("panel-max").click();
      await expectMaxed(page);
    }
    await page.waitForTimeout(1600);
    await page.screenshot({ path: join(SHOTS, `panelmax-${name}.png`), animations: "disabled" });
    await ctx.close();
  };
  await shot("dark", "normal-dark", "runs", false);
  await shot("dark", "max-plans-dark", "runs", true);
  await shot("dark", "max-details-dark", "details", true);
  await shot("light", "max-plans-light", "runs", true);
});
