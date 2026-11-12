// Settings > Terminal on the mock host: a theme picked for the dark and for the light app theme reaches the open
// terminal and outlives a restart, a font size changes how many columns fit (and the program is told), the search
// field filters the list, the preview is a real terminal, and the page fits a 900x700 window.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

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

type Call = { op: string; cols?: number; rows?: number };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

type Look = { background?: string; cols: number; rows: number; fontSize?: number; cursorStyle?: string; contrast?: number; optionIsMeta?: boolean; blink?: boolean; font?: string; pad: string; wrapBg: string };
/** The open session terminal as xterm has it (the hook the dev build exposes), and the box it sits in. */
const look = (page: Page): Promise<Look | null> =>
  page.evaluate(() => {
    type T = { element?: HTMLElement; cols: number; rows: number; options: { theme?: { background?: string }; fontSize?: number; fontFamily?: string; cursorStyle?: string; cursorBlink?: boolean; minimumContrastRatio?: number; macOptionIsMeta?: boolean } };
    const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
    const t = [...(set ?? [])].find((x) => x.element?.closest(".term-host"));
    if (!t) return null;
    const wrap = t.element?.closest<HTMLElement>(".term-wrap");
    return {
      background: t.options.theme?.background,
      cols: t.cols,
      rows: t.rows,
      fontSize: t.options.fontSize,
      cursorStyle: t.options.cursorStyle,
      contrast: t.options.minimumContrastRatio,
      optionIsMeta: t.options.macOptionIsMeta,
      blink: t.options.cursorBlink,
      font: t.options.fontFamily,
      pad: wrap ? getComputedStyle(wrap).paddingLeft : "",
      wrapBg: wrap ? getComputedStyle(wrap).backgroundColor : "",
    };
  });

async function open(page: Page) {
  await page.addInitScript(() => {
    // the first load starts clean; a reload (the restart) keeps what the first one stored
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.term", "omher.theme", "omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
    }
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh"];
    // the Option row is macOS's: the same page on every machine that runs this spec
    Object.defineProperty(navigator, "platform", { get: () => "MacIntel" });
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A Claude Code session opened as a terminal, its program's first output on screen. */
async function terminalClaude(page: Page) {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

async function settings(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-settings")).toBeVisible();
}

/** Back from Settings to the session's terminal. */
async function session(page: Page) {
  await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
  await expect(page.getByTestId("terminal")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("Terminal is a Settings page after General; omher's own two themes lead the list and are picked", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  const nav = page.locator(".st-nav button");
  const names = await nav.allTextContents();
  expect(names.indexOf("Terminal")).toBe(names.indexOf("General") + 1);
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("settings-nav-terminal")).toHaveAttribute("aria-current", "page");

  // every theme, grouped Dark and Light, omher's own first in each
  await expect(page.locator("[data-testid=term-themes] .tm-row")).toHaveCount(38);
  await expect(page.locator("[data-testid=term-themes-dark] .tm-row")).toHaveCount(26);
  await expect(page.locator("[data-testid=term-themes-light] .tm-row")).toHaveCount(12);
  await expect(page.locator("[data-testid=term-themes-dark] .tm-row").first()).toHaveText("omher Dark");
  await expect(page.locator("[data-testid=term-themes-light] .tm-row").first()).toHaveText("omher Light");
  await expect(page.locator("[data-testid=term-themes] .tm-gh")).toHaveText(["Dark", "Light"]);
  await expect(page.locator("[data-testid=term-themes] .tm-row[aria-checked=true]")).toHaveText("omher Dark");
  await page.getByTestId("term-slot").getByRole("radio", { name: "Light app theme" }).click();
  await expect(page.locator("[data-testid=term-themes] .tm-row[aria-checked=true]")).toHaveText("omher Light");
  // the kind that suits the app theme being picked for comes first
  await expect(page.locator("[data-testid=term-themes] .tm-gh")).toHaveText(["Light", "Dark"]);

  // a swatch is the theme's own colours: background, foreground and its eight normal ANSI colours
  const sw = await page.getByTestId("term-theme-dracula").locator(".tm-sw").evaluate((el) => {
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, fg: cs.color, ansi: [...el.querySelectorAll("i")].map((i) => getComputedStyle(i).backgroundColor) };
  });
  expect(sw.bg).toBe("rgb(40, 42, 54)");
  expect(sw.fg).toBe("rgb(248, 248, 242)");
  expect(sw.ansi).toHaveLength(8);
  expect(new Set(sw.ansi).size).toBe(8);
});

test("Dracula picked for dark reaches the open terminal at once and is still there after a restart", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  expect((await look(page))?.background).toBe("#0b090d");

  await settings(page);
  await page.getByTestId("term-theme-dracula").click();
  await expect(page.getByTestId("term-theme-dracula")).toHaveAttribute("aria-checked", "true");
  // the terminal is off the page while Settings is open, and has the theme already
  expect((await look(page))?.background).toBe("#282a36");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").themeDark)).toBe("dracula");

  await session(page);
  const now = await look(page);
  expect(now?.background).toBe("#282a36");
  // the space around the terminal is the theme's colour too
  expect(now?.wrapBg).toBe("rgb(40, 42, 54)");
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");

  // restart: the session comes back not running; resumed, its terminal is made with the pick
  await expect.poll(async () => (await page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null")))?.sessions?.[0]?.open).toBe("terminal");
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await page.getByTestId("session-resume").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect((await look(page))?.background).toBe("#282a36");
  await settings(page);
  await expect(page.getByTestId("term-theme-dracula")).toHaveAttribute("aria-checked", "true");
});

test("a light app theme uses the light pick, a dark one the dark pick", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  await settings(page);
  await page.getByTestId("term-theme-dracula").click();
  await page.getByTestId("term-slot").getByRole("radio", { name: "Light app theme" }).click();
  await page.getByTestId("term-theme-solarized-light").click();
  await expect(page.getByTestId("term-theme-solarized-light")).toHaveAttribute("aria-checked", "true");
  // the app is dark: the open terminal keeps the dark pick
  expect((await look(page))?.background).toBe("#282a36");

  await page.getByTestId("settings-nav-general").click();
  await page.getByTestId("theme-seg").getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await session(page);
  await expect.poll(async () => (await look(page))?.background).toBe("#fdf6e3");
  // light background: Solarized Light's own, and the preview follows the app theme's pick
  await settings(page);
  await expect(page.getByTestId("term-slot").getByRole("radio", { name: "Light app theme" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("term-preview")).toHaveAttribute("data-theme-id", "solarized-light");

  await page.getByTestId("settings-nav-general").click();
  await page.getByTestId("theme-seg").getByRole("radio", { name: "Dark" }).click();
  await session(page);
  await expect.poll(async () => (await look(page))?.background).toBe("#282a36");
});

test("font size 16 changes how many columns fit, and the program is told the new size", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  const before = await look(page);
  expect(before?.fontSize).toBe(12.5);
  expect(before!.cols).toBeGreaterThan(40);

  await settings(page);
  await page.getByTestId("term-font-size").locator("input").fill("16");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").fontSize)).toBe(16);
  await session(page);
  await expect.poll(async () => (await look(page))?.cols).toBeLessThan(before!.cols);
  const after = await look(page);
  expect(after?.fontSize).toBe(16);
  expect(after!.rows).toBeLessThan(before!.rows);
  const resizes = (await calls(page)).filter((c) => c.op === "resize");
  expect(resizes.at(-1)).toMatchObject({ cols: after!.cols, rows: after!.rows });

  // padding refits too: less space around the terminal, more columns
  await settings(page);
  const pad = page.getByTestId("term-padding");
  await pad.locator("input").fill("0");
  await session(page);
  await expect.poll(async () => (await look(page))?.pad).toBe("0px");
  await expect.poll(async () => (await look(page))?.cols).toBeGreaterThan(after!.cols);

  // out of range is not applied; the field goes back to the value in force
  await settings(page);
  const size = page.getByTestId("term-font-size").locator("input");
  await size.fill("99");
  await size.blur();
  await expect(size).toHaveValue("16");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}").fontSize)).toBe(16);
  // the steps stop at the ends of the range
  await page.getByTestId("term-font-size").getByRole("button", { name: "Increase Font size" }).click();
  await expect(size).toHaveValue("16.5");
});

test("cursor, contrast and the other options reach the open terminal and are kept", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  expect(await look(page)).toMatchObject({ cursorStyle: "block", contrast: 4.5, pad: "16px", optionIsMeta: true, blink: true });

  await settings(page);
  await page.getByTestId("term-cursor").getByRole("radio", { name: "Bar" }).click();
  await page.getByTestId("term-contrast").getByRole("radio", { name: "Auto" }).click();
  // omher Dark is a dark background: 3:1
  expect(await look(page)).toMatchObject({ cursorStyle: "bar", contrast: 3 });
  await expect(page.getByTestId("term-contrast-row")).toContainText("4.5:1 on a light background and 3:1 on a dark one");
  await page.getByTestId("term-contrast").getByRole("radio", { name: "As the theme" }).click();
  expect((await look(page))?.contrast).toBe(1);

  // scrollback: the four presets, and the row says when it applies
  const sb = page.getByTestId("term-scrollback");
  await expect(sb.getByRole("radio")).toHaveText(["5,000", "10,000", "25,000", "50,000"]);
  await expect(page.getByTestId("term-scrollback-row")).toContainText("Applies to terminals opened from now on");
  await sb.getByRole("radio", { name: "25,000" }).click();
  await page.getByTestId("term-blink").getByRole("radio", { name: "Off" }).click();
  await page.getByTestId("term-font").fill("Menlo");
  // Option as Meta: on as it always was, and the row says what it does
  await expect(page.getByTestId("term-option-meta").getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("term-option-meta-row")).toContainText("Option sends Meta to the program");
  await page.getByTestId("term-option-meta").getByRole("radio", { name: "Off" }).click();
  const now = await look(page);
  expect(now).toMatchObject({ optionIsMeta: false, blink: false });
  expect(now?.font).toMatch(/^"Menlo", /);
  // the GPU row shows the setting, and its second line says what draws the open terminal (Off: the standard one)
  await page.getByTestId("term-gpu").getByRole("radio", { name: "Off" }).click();
  await expect(page.getByTestId("term-gpu-row")).toContainText("In use now: standard");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term") || "{}"))).toMatchObject({
    cursorStyle: "bar",
    contrast: "theme",
    scrollback: 25000,
    cursorBlink: false,
    fontFamily: "Menlo",
    optionIsMeta: false,
    gpu: "off",
  });
});

test("the search field filters the list", async ({ page }) => {
  await open(page);
  await settings(page);
  const rows = page.locator("[data-testid=term-themes] .tm-row");
  await page.getByTestId("term-search").fill("solar");
  await expect(rows).toHaveText(["Solarized Dark", "Solarized Light"]);
  // spaces and case do not matter
  await page.getByTestId("term-search").fill("tokyonight");
  await expect(rows).toHaveText(["Tokyo Night", "Tokyo Night Light"]);
  await page.getByTestId("term-search").fill("GITHUB dark");
  await expect(rows).toHaveText(["GitHub Dark Default", "GitHub Dark High Contrast", "GitHub Dark Dimmed"]);
  await page.getByTestId("term-search").fill("no such theme");
  await expect(rows).toHaveCount(0);
  await expect(page.getByTestId("term-themes-none")).toHaveText("No theme matches “no such theme”");
  await page.getByTestId("term-search").fill("");
  await expect(rows).toHaveCount(38);
});

test("the preview is a real terminal that shows the pick: sample output, all 16 colours, a selection", async ({ page }) => {
  await open(page);
  await settings(page);
  const pv = page.getByTestId("term-preview");
  await expect(pv.locator(".xterm-rows")).toContainText("git status --short");
  await expect(pv.locator(".xterm-rows")).toContainText("42 passed");
  await expect(pv).toHaveAttribute("data-theme-id", "omher-dark");
  const read = () =>
    page.evaluate(() => {
      type T = { element?: HTMLElement; rows: number; cols: number; getSelection(): string; options: { theme?: { background?: string }; disableStdin?: boolean } };
      const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
      const t = [...(set ?? [])].find((x) => x.element?.closest(".term-pv"));
      const box = document.querySelector<HTMLElement>("[data-testid=term-preview]")!;
      return t ? { bg: t.options.theme?.background, sel: t.getSelection(), rows: t.rows, stdin: t.options.disableStdin, boxBg: getComputedStyle(box).backgroundColor } : null;
    });
  await expect.poll(async () => (await read())?.sel).toBe("src/theme.ts");
  expect(await read()).toMatchObject({ bg: "#0b090d", rows: 10, stdin: true });
  // the cursor shows in the shape picked, though the preview never has the keyboard
  await expect(pv.locator(".xterm-cursor.xterm-cursor-block")).toHaveCount(1);
  await page.getByTestId("term-cursor").getByRole("radio", { name: "Underline" }).click();
  await expect(pv.locator(".xterm-cursor.xterm-cursor-underline")).toHaveCount(1);
  // every colour of the sample is on screen: 16 background cells of each row of blocks
  expect(await pv.locator(".xterm-rows span[class*=xterm-bg-]").count()).toBeGreaterThanOrEqual(16);

  await page.getByTestId("term-theme-dracula").click();
  await expect(pv).toHaveAttribute("data-theme-id", "dracula");
  await expect.poll(async () => (await read())?.bg).toBe("#282a36");
  expect((await read())?.boxBg).toBe("rgb(40, 42, 54)");
  // the other app theme previews its own pick
  await page.getByTestId("term-slot").getByRole("radio", { name: "Light app theme" }).click();
  await expect.poll(async () => (await read())?.bg).toBe("#ffffff");
  await expect.poll(async () => (await read())?.sel).toBe("src/theme.ts");
});

test("the page has no horizontal scroll at 900x700", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  await open(page);
  await settings(page);
  await expect(page.getByTestId("term-preview").locator(".xterm-rows")).toContainText("42 passed");
  const r = await page.evaluate(() => {
    const body = document.querySelector<HTMLElement>(".st-body")!;
    const list = document.querySelector<HTMLElement>("[data-testid=term-themes]")!;
    return { doc: document.documentElement.scrollWidth, vw: window.innerWidth, body: [body.scrollWidth, body.clientWidth], list: [list.scrollWidth, list.clientWidth] };
  });
  expect(r.doc).toBeLessThanOrEqual(r.vw);
  expect(r.body[0]).toBeLessThanOrEqual(r.body[1]);
  expect(r.list[0]).toBeLessThanOrEqual(r.list[1]);
});
