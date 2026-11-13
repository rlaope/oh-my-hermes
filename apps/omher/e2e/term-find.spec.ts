// Find in a session terminal (mock host, the engine's real feed()): Cmd+F (macOS) / Ctrl+F opens a small bar at the
// terminal's top right, typing shows the match count, Enter and Shift+Enter move, Esc closes it and the terminal
// has the keyboard again. It does nothing in a chat session or a bot chat, and on Windows and Linux a full-screen
// program keeps its Ctrl+F (Ctrl+Shift+F is always find).
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, modKey, newTerminal, openApp, platformIsMac, settle, typed } from "./term-find-helpers";

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

const LINES = "\r\nalpha needle one\r\nbeta\r\nneedle two\r\ngamma\r\nthe needle three\r\n";

const bar = (page: Page) => page.getByTestId("term-find");
const input = (page: Page) => page.getByTestId("term-find-input");
const count = (page: Page) => page.getByTestId("term-find-count");

/** The keyboard is in the terminal (xterm's hidden textarea has focus). */
const terminalFocused = (page: Page) => page.evaluate(() => document.activeElement?.classList.contains("xterm-helper-textarea") ?? false);

async function find(page: Page, shift = false) {
  const mod = await modKey(page);
  await page.keyboard.press(`${mod}+${shift ? "Shift+" : ""}f`);
}

async function terminalWithText(page: Page) {
  await openApp(page);
  await newTerminal(page);
  await feed(page, LINES);
}

test("Cmd/Ctrl+F opens the bar with the field focused; a closed bar is not in the page", async ({ page }) => {
  await terminalWithText(page);
  await expect(bar(page)).toHaveCount(0);
  await find(page);
  await expect(bar(page)).toBeVisible();
  await expect(input(page)).toBeFocused();
  // at the terminal's top right, inside it
  const [b, t] = await Promise.all([bar(page).boundingBox(), page.getByTestId("terminal").boundingBox()]);
  expect(b!.y - t!.y).toBeLessThan(24);
  expect(t!.x + t!.width - (b!.x + b!.width)).toBeLessThan(40);
  expect(b!.x).toBeGreaterThan(t!.x + t!.width / 2);
});

test("typing shows the match count, Enter moves to the next match, Shift+Enter back, Esc closes and the terminal has focus again", async ({ page }) => {
  await terminalWithText(page);
  await find(page);
  await input(page).fill("needle");
  await expect(count(page)).toHaveText(/^[123] of 3$/);

  const seen: string[] = [];
  const at = async () => {
    const t = (await count(page).textContent()) ?? "";
    return Number(t.split(" ")[0]);
  };
  seen.push(String(await at()));
  await page.keyboard.press("Enter");
  await expect.poll(async () => String(await at())).not.toBe(seen[0]);
  const second = await at();
  await page.keyboard.press("Enter");
  await expect.poll(at).not.toBe(second);
  await page.keyboard.press("Shift+Enter");
  await expect.poll(at).toBe(second);
  // three Enters from any spot come back round to where they started (3 matches)
  const start = await at();
  for (let i = 0; i < 3; i++) await page.keyboard.press("Enter");
  await expect.poll(at).toBe(start);

  // the buttons do the same
  await page.getByTestId("term-find-next").click();
  await expect.poll(at).not.toBe(start);
  await page.getByTestId("term-find-prev").click();
  await expect.poll(at).toBe(start);

  await page.keyboard.press("Escape");
  await expect(bar(page)).toHaveCount(0);
  await expect.poll(() => terminalFocused(page)).toBe(true);
  // the keyboard really is the terminal's: typing reaches the program
  await page.keyboard.type("hi");
  await expect.poll(() => typed(page)).toContain("hi");
});

test("matches are selected in the scrollback; a search with no match says so, and an empty field says nothing", async ({ page }) => {
  await terminalWithText(page);
  await find(page);
  await input(page).fill("needle");
  await expect(count(page)).toHaveText(/ of 3$/);
  await expect.poll(() => page.evaluate(() => (window as unknown as { __omherTerms: Set<{ getSelection(): string }> }).__omherTerms && [...(window as unknown as { __omherTerms: Set<{ getSelection(): string }> }).__omherTerms].some((t) => t.getSelection() === "needle"))).toBe(true);
  await input(page).fill("zzz-nothing");
  await expect(count(page)).toHaveText("No matches");
  await expect(page.getByTestId("term-find-next")).toBeDisabled();
  await input(page).fill("");
  await expect(count(page)).toHaveText("");
});

test("find also reaches text that scrolled out of the screen", async ({ page }) => {
  await terminalWithText(page);
  await feed(page, Array.from({ length: 120 }, (_, i) => `filler ${i}\r\n`).join(""));
  await find(page);
  await input(page).fill("needle");
  await expect(count(page)).toHaveText(/ of 3$/);
});

test("the counter is not clipped and the bar stays inside a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  await terminalWithText(page);
  await find(page);
  await input(page).fill("needle");
  await expect(count(page)).toHaveText(/ of 3$/);
  const r = await page.evaluate(() => {
    const n = document.querySelector<HTMLElement>('[data-testid="term-find-count"]')!;
    const b = document.querySelector<HTMLElement>('[data-testid="term-find"]')!;
    const t = document.querySelector<HTMLElement>('[data-testid="terminal"]')!;
    const nb = n.getBoundingClientRect();
    const bb = b.getBoundingClientRect();
    const tb = t.getBoundingClientRect();
    const st = getComputedStyle(b);
    return { clipped: n.scrollWidth > n.clientWidth, inside: bb.left >= tb.left && bb.right <= tb.right && nb.left >= bb.left && nb.right <= bb.right, fontPx: parseFloat(getComputedStyle(n).fontSize), shadow: st.boxShadow, radius: parseFloat(st.borderRadius) };
  });
  expect(r.clipped).toBe(false);
  expect(r.inside).toBe(true);
  expect(r.fontPx).toBeGreaterThanOrEqual(12);
  expect(r.fontPx).toBeLessThanOrEqual(13);
  expect(r.shadow).toBe("none");
  expect(r.radius).toBeGreaterThanOrEqual(4);
  expect(r.radius).toBeLessThanOrEqual(6);
});

test("the shortcut does nothing in a chat session", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await page.getByTestId("composer").click();
  await find(page);
  await find(page, true);
  await settle(page);
  await expect(bar(page)).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveCount(0);
});

test("the shortcut does nothing in a bot chat", async ({ page }) => {
  await openApp(page);
  await expect(page.getByTestId("composer")).toBeVisible();
  await page.getByTestId("composer").click();
  await find(page);
  await find(page, true);
  await settle(page);
  await expect(bar(page)).toHaveCount(0);
});

test("a terminal that is not focused does not take the shortcut (the bar is for the terminal the keyboard is in)", async ({ page }) => {
  await terminalWithText(page);
  // the keyboard is in the sidebar's search field, not the terminal. A click, not the search shortcut: off macOS
  // Ctrl+K typed in a terminal is the program's (src/app/shortcuts.ts), so the shortcut would leave the keyboard
  // where it was
  await page.getByTestId("bot-search").click();
  await expect(page.getByTestId("bot-search")).toBeFocused();
  await find(page);
  await settle(page);
  await expect(bar(page)).toHaveCount(0);
});

test("macOS: Cmd+F opens find even in a full-screen program; Ctrl+F stays the program's. Windows/Linux: Ctrl+F in a full-screen program stays the program's, Ctrl+Shift+F opens find", async ({ page }) => {
  await terminalWithText(page);
  await feed(page, "\x1b[?1049h\x1b[2J\x1b[Hfull screen needle"); // the alternate screen (vim, less, htop)
  const mac = await platformIsMac(page);
  const before = await typed(page);
  if (mac) {
    await find(page);
    await expect(bar(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(bar(page)).toHaveCount(0);
    await page.keyboard.press("Control+f");
    await settle(page);
    await expect(bar(page)).toHaveCount(0);
    expect((await typed(page)).slice(before.length)).toContain("\x06"); // Ctrl+F reached the program
  } else {
    await find(page);
    await settle(page);
    await expect(bar(page)).toHaveCount(0);
    expect((await typed(page)).slice(before.length)).toContain("\x06"); // Ctrl+F reached the program
    await find(page, true);
    await expect(bar(page)).toBeVisible();
  }
});

test("Windows/Linux: Ctrl+F at a prompt opens find and is not sent to the program", async ({ page }) => {
  await terminalWithText(page);
  test.skip(await platformIsMac(page), "on macOS Ctrl+F is the program's (cursor forward) and Cmd+F finds");
  const before = await typed(page);
  await find(page);
  await expect(bar(page)).toBeVisible();
  await page.keyboard.press("Escape");
  expect((await typed(page)).slice(before.length)).not.toContain("\x06");
});

/** The cells find has filled in the shown terminal (their fills), what find-colors.ts picks for its theme now, and
 *  what the terminal has selected. */
const fills = (page: Page) =>
  page.evaluate(async () => {
    type T = { element?: HTMLElement; options: { theme?: object }; getSelection(): string };
    const host = document.querySelector('[data-testid="terminal"] .xterm')!;
    const term = [...((window as unknown as { __omherTerms?: Set<T> }).__omherTerms ?? [])].find((t) => t.element === host)!;
    const { findColors } = (await import("/src/sessions/term/find-colors.ts" as string)) as { findColors: (t: unknown) => { matchBackground: string; activeMatchBackground: string } };
    const hex = (rgb: string) => {
      const m = /rgba?\((\d+), (\d+), (\d+)/.exec(rgb);
      return m ? `#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("")}` : rgb;
    };
    const bg = [...host.querySelectorAll<HTMLElement>(".xterm-rows span")].filter((x) => /background-color/.test(x.getAttribute("style") ?? "")).map((x) => hex(getComputedStyle(x).backgroundColor));
    const picked = findColors(term.options.theme ?? {});
    return {
      cells: bg.length,
      active: bg.filter((c) => c === picked.activeMatchBackground).length,
      plain: bg.filter((c) => c === picked.matchBackground).length,
      outlines: host.querySelectorAll(".tfind-active").length,
      selection: term.getSelection(),
    };
  });

test("leaving the terminal with find open takes the highlights with the bar: back on it, nothing is filled and nothing selected", async ({ page }) => {
  await terminalWithText(page);
  const id = (await page.getByTestId("terminal").getAttribute("data-session")) as string;
  const back = async () => {
    await page.getByTestId(`session-${id}`).locator(".ss-open").click();
    await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
  };
  const search = async () => {
    await find(page);
    await input(page).fill("needle");
    await expect(count(page)).toHaveText(/^[123] of 3$/);
    await expect.poll(async () => (await fills(page)).cells).toBe(18); // 3 matches of 6 cells
  };

  // to a bot's chat and back
  await search();
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await back();
  await expect(bar(page)).toHaveCount(0);
  await expect.poll(() => fills(page)).toEqual({ cells: 0, active: 0, plain: 0, outlines: 0, selection: "" });

  // to Settings and back
  await search();
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await back();
  await expect(bar(page)).toHaveCount(0);
  await expect.poll(() => fills(page)).toEqual({ cells: 0, active: 0, plain: 0, outlines: 0, selection: "" });

  // find still works on the terminal afterwards
  await search();
  expect((await fills(page)).active).toBe(6);
});

test("a theme that changes while find is open recolours the matches at once, and the active match stays where it was", async ({ page }) => {
  await openApp(page, { theme: "dark", term: { themeDark: "dracula" } });
  await newTerminal(page);
  await feed(page, LINES);
  await find(page);
  await input(page).fill("needle");
  await page.keyboard.press("Enter");
  await expect(count(page)).toHaveText(/^[123] of 3$/);
  await expect.poll(() => fills(page)).toMatchObject({ cells: 18, active: 6, plain: 12, outlines: 1 });
  const at = await count(page).textContent();

  for (const theme of ["one-light", "tango-dark"]) {
    await page.evaluate(async (themeDark) => {
      const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
      m.writeTermSettings({ themeDark });
    }, theme);
    // every fill is the new theme's (none of the old theme's is left), with no key pressed
    await expect.poll(() => fills(page), theme).toMatchObject({ cells: 18, active: 6, plain: 12, outlines: 1, selection: "needle" });
    await expect(count(page)).toHaveText(at as string);
  }
  // a setting that is no colour and no size (the cursor's blink) leaves find as it is. A size is another matter:
  // xterm drops the selection when the terminal's grid changes, and the add-on then finds again from the bottom
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ cursorBlink: false });
  });
  await settle(page);
  expect(await fills(page)).toMatchObject({ cells: 18, active: 6, plain: 12, outlines: 1, selection: "needle" });
  await expect(count(page)).toHaveText(at as string);
});

test("find does not change what a program is sent: typing in the field never reaches the terminal", async ({ page }) => {
  await terminalWithText(page);
  await find(page);
  const before = await typed(page);
  await input(page).fill("needle");
  await page.keyboard.press("Enter");
  await settle(page);
  expect((await typed(page)).slice(before.length)).toBe("");
});

test("find does not touch the clipboard (it selects, and copy on select must not copy a find's selection)", async ({ page }) => {
  await openApp(page, { term: { copyOnSelect: true } });
  await newTerminal(page);
  await feed(page, LINES);
  await find(page);
  await input(page).fill("needle");
  await expect(count(page)).toHaveText(/ of 3$/);
  await page.keyboard.press("Enter");
  await settle(page);
  expect(await page.evaluate(() => (window as unknown as { __clipWrites: string[] }).__clipWrites)).toEqual([]);
});
