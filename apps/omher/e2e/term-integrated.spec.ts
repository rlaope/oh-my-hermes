// The joins between the terminal's parts (mock host), not the parts themselves:
//   1. the output credit (flow) runs from the `done` of the engine's `feed`: every message the program prints is
//      acknowledged once, with its size, in order, also when the terminal takes a flood over several frames;
//   2. a session that is not on the page keeps acknowledging what its program prints, so a background agent is never
//      held at the shell's 2 MiB mark because another session, or Settings, is on screen;
//   3. Settings > Terminal shows the renderer in use, and Auto / On / Off reaches a terminal that is already open;
//   4. a theme or font change made while a terminal is hidden is on it when it is shown again, and its program is
//      told the new size;
//   5. find's matches and a link's underline stay readable on three themes, one of them light, and the active match
//      is the most visible one.
// Chromium (Playwright's headless shell); nothing here ran in the Tauri window.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, modKey, newTerminal, openApp, pointAt } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Flow = { op: "feed" | "ack"; id: number; bytes: number };
type Call = { op: string; id?: number; cols?: number; rows?: number; bytes?: number };
const flow = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionFlow?: Flow[] }).__omherSessionFlow ?? []);
const calls = (page: Page) => page.evaluate(() => (window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []);
/** The shell's ids of the terminals started so far, in the order they were opened. */
const hostIds = async (page: Page) => (await calls(page)).filter((c) => c.op === "start").map((c) => c.id as number);
const sum = (steps: Flow[], op: Flow["op"], id: number) => steps.filter((f) => f.op === op && f.id === id).reduce((n, f) => n + f.bytes, 0);
const MIB = 1024 * 1024;
/** One message of the mock's flood (FLOOD_MESSAGE in src/sessions/host.ts): what the shell hands on at most. */
const MESSAGE = 64 * 1024;
/** FLOW_HIGH in src-tauri/src/sessions.rs: the shell stops reading a program this far ahead of the page. */
const FLOW_HIGH = 2 * MIB;

const show = async (page: Page, id: string) => {
  await page.getByTestId(`session-${id}`).locator(".ss-open").click();
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
};
const settings = async (page: Page) => {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-settings")).toBeVisible();
};
/** Type a line at the shown terminal's prompt. */
const run = async (page: Page, line: string) => {
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await page.keyboard.type(line);
  await page.keyboard.press("Enter");
};

test.describe("credit through the engine's feed", () => {
  test.use({ colorScheme: "dark" });

  test("a flood the terminal takes over several frames: every message acknowledged once, with its size, in order", async ({ page }) => {
    await openApp(page);
    await newTerminal(page);
    const [id] = await hostIds(page);
    // each acknowledgement is stamped with the frame it came in
    await page.evaluate(() => {
      const w = window as unknown as { __omherSessionFlow?: Flow[]; __ackFrames: number[] };
      type Flow = { op: string };
      let frame = 0;
      const tick = () => {
        frame += 1;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      w.__ackFrames = [];
      const log = (w.__omherSessionFlow ??= []);
      const push = log.push.bind(log);
      log.push = (...steps: Flow[]) => {
        for (const s of steps) if (s.op === "ack") w.__ackFrames.push(frame);
        return push(...steps);
      };
    });
    const before = (await flow(page)).length;
    await run(page, "after 50 flood 6");
    await expect.poll(async () => sum(await flow(page), "feed", id), { timeout: 20_000 }).toBeGreaterThanOrEqual(6 * MIB);
    await expect.poll(async () => sum(await flow(page), "ack", id), { timeout: 20_000 }).toBe(sum(await flow(page), "feed", id));

    const all = (await flow(page)).slice(before);
    const feeds = all.filter((f) => f.op === "feed");
    const acks = all.filter((f) => f.op === "ack");
    expect(feeds.filter((f) => f.bytes === MESSAGE)).toHaveLength(96);
    // the acknowledgements are the messages: as many, of the same sizes, in the same order
    expect(acks.map((a) => a.bytes)).toEqual(feeds.map((f) => f.bytes));
    // and none comes before its message was handed over
    let fed = 0;
    let acked = 0;
    for (const step of all) {
      if (step.op === "feed") fed += 1;
      else expect(++acked).toBeLessThanOrEqual(fed);
    }
    // the terminal did not take the flood in one go: its acknowledgements came over more than one frame, which is
    // what gives the shell its credit back while the program is still printing
    const frames = await page.evaluate(() => (window as unknown as { __ackFrames: number[] }).__ackFrames);
    expect(new Set(frames).size).toBeGreaterThan(1);
    expect([...frames].sort((a, b) => a - b)).toEqual(frames);
  });

  test("a session that is not on the page keeps acknowledging: another session shown, then Settings, then a bot's chat", async ({ page }) => {
    await openApp(page);
    const a = await newTerminal(page);
    const b = await newTerminal(page);
    const [idA, idB] = await hostIds(page);
    expect(idA).not.toBe(idB);

    // A's program prints 3 MiB (more than the shell lets a session run ahead) a little later; meanwhile B is shown
    await show(page, a);
    await run(page, "after 1500 flood 3");
    await show(page, b);
    // the flood has not started: A was hidden before its first message
    expect((await flow(page)).filter((f) => f.id === idA && f.bytes === MESSAGE)).toHaveLength(0);
    await expect.poll(async () => sum(await flow(page), "feed", idA), { timeout: 20_000 }).toBeGreaterThanOrEqual(3 * MIB);
    await expect.poll(async () => sum(await flow(page), "ack", idA), { timeout: 20_000 }).toBe(sum(await flow(page), "feed", idA));
    expect(sum(await flow(page), "ack", idA)).toBeGreaterThan(FLOW_HIGH);
    // B stayed on the page the whole time
    await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", b);

    // no terminal on the page at all: Settings
    await run(page, "after 1500 flood 3");
    await settings(page);
    await expect(page.getByTestId("terminal")).toHaveCount(0);
    expect((await flow(page)).filter((f) => f.id === idB && f.bytes === MESSAGE)).toHaveLength(0);
    await expect.poll(async () => sum(await flow(page), "feed", idB), { timeout: 20_000 }).toBeGreaterThanOrEqual(3 * MIB);
    await expect.poll(async () => sum(await flow(page), "ack", idB), { timeout: 20_000 }).toBe(sum(await flow(page), "feed", idB));
    await expect(page.getByTestId("terminal")).toHaveCount(0);

    // and a bot's chat on screen
    await show(page, a);
    const fedA = sum(await flow(page), "feed", idA);
    await run(page, "after 1500 flood 3");
    await page.getByTestId("bot-kami").click();
    await expect(page.getByTestId("terminal")).toHaveCount(0);
    await expect.poll(async () => sum(await flow(page), "feed", idA), { timeout: 20_000 }).toBeGreaterThanOrEqual(fedA + 3 * MIB);
    await expect.poll(async () => sum(await flow(page), "ack", idA), { timeout: 20_000 }).toBe(sum(await flow(page), "feed", idA));

    // every acknowledgement of either session is one of its messages, in the order they came
    const all = await flow(page);
    for (const id of [idA, idB]) {
      const mine = all.filter((f) => f.id === id);
      expect(mine.filter((f) => f.op === "ack").map((f) => f.bytes)).toEqual(mine.filter((f) => f.op === "feed").map((f) => f.bytes));
    }
    // back on A, what it printed while it was away is there
    await show(page, a);
    await expect(page.locator(".xterm-rows")).toContainText("build output");
  });
});

test.describe("the renderer, from Settings", () => {
  test.use({ colorScheme: "dark" });

  const inUse = (page: Page) => page.evaluate(async () => (await import("/src/sessions/term/engine.ts" as string)).rendererInUse() as "gpu" | "standard" | null);
  const canvases = (page: Page) => page.locator('[data-testid="terminal"] .xterm canvas').count();
  const back = async (page: Page) => {
    await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
    await expect(page.getByTestId("terminal")).toBeVisible();
  };

  test("the row says what draws the terminals; Auto, On and Off reach a terminal that is already open", async ({ page }) => {
    const requested: string[] = [];
    page.on("request", (r) => {
      if (/addon-webgl/.test(r.url())) requested.push(r.url());
    });
    await openApp(page);
    const row = page.getByTestId("term-gpu-row");

    // nothing open: the row shows the choice and no renderer
    await settings(page);
    await expect(row.getByRole("radio")).toHaveText(["Auto", "On", "Off"]);
    await expect(row.getByRole("radio", { name: "Auto" })).toHaveAttribute("aria-checked", "true");
    await expect(row).toContainText("Auto uses the standard renderer for now");
    await expect(row).not.toContainText("In use now");

    // Auto, the default: the standard renderer, and the GPU add-on is never fetched
    await page.getByTestId("bot-kami").click();
    await newTerminal(page);
    expect(await inUse(page)).toBe("standard");
    expect(await canvases(page)).toBe(0);
    await settings(page);
    await expect(row).toContainText("In use now: standard");
    expect(requested).toEqual([]);

    // On: the open terminal draws with the GPU when it is back on the page, and the row says so
    await row.getByRole("radio", { name: "On" }).click();
    await back(page);
    await expect.poll(() => inUse(page)).toBe("gpu");
    expect(await canvases(page)).toBeGreaterThan(0);
    expect(requested.length).toBeGreaterThan(0);
    await settings(page);
    await expect(row).toContainText("In use now: GPU");

    // Off: at once, on the same terminal; its text is back in the page
    await row.getByRole("radio", { name: "Off" }).click();
    await expect(row).toContainText("In use now: standard");
    await back(page);
    expect(await inUse(page)).toBe("standard");
    expect(await canvases(page)).toBe(0);
    await expect(page.locator(".xterm-rows")).toContainText("(mock)");

    // back to Auto: still the standard renderer
    await settings(page);
    await row.getByRole("radio", { name: "Auto" }).click();
    await expect(row).toContainText("In use now: standard");
    await back(page);
    expect(await canvases(page)).toBe(0);
  });

  for (const platform of ["Win32", "Linux x86_64"]) {
    test(`Auto stays on the standard renderer on ${platform} too, and never asks for a WebGL context to decide`, async ({ page }) => {
      const requested: string[] = [];
      page.on("request", (r) => {
        if (/addon-webgl/.test(r.url())) requested.push(r.url());
      });
      await page.addInitScript((p) => {
        Object.defineProperty(navigator, "platform", { get: () => p });
        const w = window as unknown as { __glAsked: number };
        w.__glAsked = 0;
        const get = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
          if (/webgl/.test(kind)) w.__glAsked += 1;
          return (get as (...a: unknown[]) => unknown).call(this, kind, ...rest);
        } as typeof get;
      }, platform);
      await openApp(page);
      await newTerminal(page);
      expect(await inUse(page)).toBe("standard");
      expect(await canvases(page)).toBe(0);
      expect(requested).toEqual([]);
      expect(await page.evaluate(() => (window as unknown as { __glAsked: number }).__glAsked)).toBe(0);
    });
  }
});

test.describe("the look reaches a hidden terminal", () => {
  test.use({ colorScheme: "dark" });

  type Seen = { background?: string; fontSize?: number; cols: number; rows: number; connected: boolean };
  /** The session terminals as xterm has them, in the order they were opened (shown or not). */
  const terms = (page: Page): Promise<Seen[]> =>
    page.evaluate(() => {
      type T = { element?: HTMLElement; cols: number; rows: number; options: { theme?: { background?: string }; fontSize?: number } };
      const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
      return [...(set ?? [])].filter((t) => t.element?.closest(".term-host")).map((t) => ({ background: t.options.theme?.background, fontSize: t.options.fontSize, cols: t.cols, rows: t.rows, connected: !!t.element?.isConnected }));
    });

  test("a theme and a font size picked while a terminal is hidden are on it when it is shown again, and its program is told the new size", async ({ page }) => {
    await openApp(page);
    const a = await newTerminal(page);
    const b = await newTerminal(page);
    const [idA] = await hostIds(page);
    const before = await terms(page);
    expect(before.map((t) => t.connected)).toEqual([false, true]); // A is hidden, B is shown
    expect(before[0]).toMatchObject({ background: "#0b090d", fontSize: 12.5 });
    expect(before[0].cols).toBeGreaterThan(40);

    await settings(page);
    await page.getByTestId("term-theme-dracula").click();
    await page.getByTestId("term-font-size").locator("input").fill("16");
    // no terminal is on the page now; neither has been refitted, and neither program has been told a size
    expect((await terms(page)).map((t) => t.connected)).toEqual([false, false]);
    expect((await terms(page)).map((t) => t.cols)).toEqual(before.map((t) => t.cols));
    expect((await calls(page)).filter((c) => c.op === "resize")).toEqual([]);

    // A again: Dracula, 16px, fewer cells, and the page around it is the theme's colour
    await show(page, a);
    await expect.poll(async () => (await terms(page))[0].cols).toBeLessThan(before[0].cols);
    const after = (await terms(page))[0];
    expect(after).toMatchObject({ background: "#282a36", fontSize: 16, connected: true });
    expect(after.rows).toBeLessThan(before[0].rows);
    expect(await page.getByTestId("terminal").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(40, 42, 54)");
    expect(await page.locator('[data-testid="terminal"] .xterm-rows').evaluate((el) => getComputedStyle(el).fontSize)).toBe("16px");
    await expect(page.locator(".xterm-rows")).toContainText("(mock)");
    // its program hears the size it ended on, once the size has stood still
    await expect.poll(async () => (await calls(page)).filter((c) => c.op === "resize" && c.id === idA).at(-1)).toMatchObject({ cols: after.cols, rows: after.rows });

    // B, hidden through all of it, has the look too when it comes back
    await show(page, b);
    await expect.poll(async () => (await terms(page))[1].cols).toBe(after.cols);
    expect((await terms(page))[1]).toMatchObject({ background: "#282a36", fontSize: 16, connected: true });
  });
});

// ---- find and links on three themes --------------------------------------------------------------------------

const THEMES = [
  { id: "dracula", app: "dark" },
  { id: "github-dark-default", app: "dark" },
  { id: "solarized-light", app: "light" },
] as const;

const OUTPUT = "\r\nalpha needle one\r\nbeta\r\nneedle two\r\nsee https://example.com/docs for more\r\nthe needle three\r\n";

/** What the terminal's cells look like where a decoration filled them, and what find-colors.ts picked. */
const painted = (page: Page) =>
  page.evaluate(async () => {
    type T = { element?: HTMLElement; options: { theme?: Record<string, string> } };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const term = [...((window as unknown as { __omherTerms?: Set<T> }).__omherTerms ?? [])].find((t) => t.element === host)!;
    const theme = term.options.theme ?? {};
    const { findColors, contrastRatio } = (await import("/src/sessions/term/find-colors.ts" as string)) as {
      findColors: (t: unknown) => { matchBackground: string; activeMatchBackground: string; activeMatchBorder: string };
      contrastRatio: (a: string, b: string) => number;
    };
    const hex = (rgb: string) => {
      const m = /rgba?\((\d+), (\d+), (\d+)/.exec(rgb);
      return m ? `#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("")}` : rgb;
    };
    const cells = [...host!.querySelectorAll<HTMLElement>(".xterm-rows span")]
      .filter((s) => /background-color/.test(s.getAttribute("style") ?? ""))
      .map((s) => ({ text: s.textContent ?? "", bg: hex(getComputedStyle(s).backgroundColor), fg: hex(getComputedStyle(s).color) }));
    const picked = findColors(theme);
    const ratio = (a: string, b: string) => Math.round(contrastRatio(a, b) * 100) / 100;
    return {
      picked,
      background: theme.background,
      foreground: theme.foreground,
      selection: (theme.selectionBackground ?? "").slice(0, 7).toLowerCase(),
      own: ratio(theme.foreground, theme.background),
      cells: cells.map((c) => ({ ...c, text: ratio(c.fg, c.bg), page: ratio(c.bg, theme.background) })),
    };
  });

for (const th of THEMES) {
  test.describe(`${th.id} (${th.app})`, () => {
    test.use({ colorScheme: th.app });

    test(`find's matches and a link's underline are readable on ${th.id}, and the active match is the most visible`, async ({ page }) => {
      // `contrast: "theme"`: xterm lifts no colour, so what is read here is what the theme and find-colors.ts give
      await openApp(page, { theme: th.app, term: { [th.app === "light" ? "themeLight" : "themeDark"]: th.id, contrast: "theme" } });
      await newTerminal(page);
      await feed(page, OUTPUT);
      await page.keyboard.press(`${await modKey(page)}+f`);
      await page.getByTestId("term-find-input").fill("needle");
      await expect(page.getByTestId("term-find-count")).toHaveText(/^[123] of 3$/);
      await expect.poll(async () => (await painted(page)).cells.length).toBe(18); // 3 matches of 6 cells

      const p = await painted(page);
      const active = p.cells.filter((c) => c.bg === p.picked.activeMatchBackground);
      const plain = p.cells.filter((c) => c.bg === p.picked.matchBackground);
      // one match is the active one and carries the stronger fill (not the selection's colour); the other two the plain one
      expect(active.map((c) => c.text).length, JSON.stringify(p.cells.map((c) => c.bg))).toBe(6);
      expect(plain).toHaveLength(12);
      expect(p.picked.activeMatchBackground).not.toBe(p.selection);
      // readable: the text on a match keeps 4.5:1, or a little under the theme's own ratio when that is lower; on
      // the active match 3:1, and that one is outlined in the theme's text colour
      const target = Math.min(4.5, p.own - 0.6);
      for (const c of plain) expect(c.text, `text on a match (${th.id})`).toBeGreaterThanOrEqual(target - 0.05);
      for (const c of active) expect(c.text, `text on the active match (${th.id})`).toBeGreaterThanOrEqual(3);
      // the most visible: the active fill stands further from the page than a plain match does, and apart from it
      expect(active[0].page).toBeGreaterThan(plain[0].page);
      expect(plain[0].page).toBeGreaterThan(1.1);
      // and it alone carries the heavier outline, in the theme's text colour
      const outlines = await page.locator(".xterm-decoration-container .tfind-active").evaluateAll((els) => els.map((e) => ({ width: getComputedStyle(e).outlineWidth, style: getComputedStyle(e).outlineStyle })));
      expect(outlines).toEqual([{ width: "2px", style: "solid" }]);

      // Enter moves the strong fill to another match: still exactly one
      await page.keyboard.press("Enter");
      await expect.poll(async () => (await painted(page)).cells.filter((c) => c.bg === p.picked.activeMatchBackground).length).toBe(6);
      // closing find takes every fill away
      await page.keyboard.press("Escape");
      await expect.poll(async () => (await painted(page)).cells.length).toBe(0);

      // a link: underlined on hover in the text's own colour, which reads on the theme's background
      const at = await pointAt(page, "https://example.com/docs", 0, 12);
      await page.mouse.move(at.x - 3, at.y);
      await page.mouse.move(at.x, at.y);
      const link = page.locator('[data-testid="terminal"] .xterm-rows span[style*="underline"]');
      await expect(link.first()).toBeVisible();
      const seen = await link.first().evaluate((el) => {
        const c = getComputedStyle(el);
        return { line: c.textDecorationLine, color: c.color };
      });
      expect(seen.line).toContain("underline");
      const ratio = await page.evaluate(
        async ([fg, bg]) => {
          const { contrastRatio } = (await import("/src/sessions/term/find-colors.ts" as string)) as { contrastRatio: (a: string, b: string) => number };
          const m = /rgba?\((\d+), (\d+), (\d+)/.exec(fg)!;
          return contrastRatio(`#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("")}`, bg);
        },
        [seen.color, p.background] as const,
      );
      expect(ratio, `the link's text on ${th.id}`).toBeGreaterThanOrEqual(3);
      // the hint beside it is the app's own popover, readable whatever the terminal's theme
      const tip = page.locator(".term-linktip");
      await expect(tip).toBeVisible();
      const tipRatio = await tip.evaluate(async (el) => {
        const { contrastRatio } = (await import("/src/sessions/term/find-colors.ts" as string)) as { contrastRatio: (a: string, b: string) => number };
        const c = getComputedStyle(el);
        const hex = (rgb: string) => {
          const m = /rgba?\((\d+), (\d+), (\d+)/.exec(rgb)!;
          return `#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("")}`;
        };
        return contrastRatio(hex(c.color), hex(c.backgroundColor));
      });
      expect(tipRatio, `the hint on ${th.id}`).toBeGreaterThanOrEqual(4.5);
    });
  });
}
