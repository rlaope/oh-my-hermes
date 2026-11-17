// Links in a session terminal's output (mock host, the engine's real feed()): a Cmd/Ctrl+click on an http(s) address
// opens it once through the app's opener (the page's window.open outside Tauri, stubbed here: no browser is ever
// opened); a plain click does not; an address with credentials or another scheme does nothing; the hover says which
// key to hold; the bell and OSC 9 / OSC 777 still reach xterm's parser with the add-ons loaded.
import { expect, test } from "@playwright/test";
import { feed, mock, modKey, newTerminal, openApp, opened, pointAt, settle } from "./term-find-helpers";

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

const URL_OK = "https://example.com/x";

async function ready(page: import("@playwright/test").Page) {
  await openApp(page);
  await newTerminal(page);
  await feed(page, `\r\nsee ${URL_OK} for more\r\nhttp://user:pw@example.com/secret\r\nfile:///etc/passwd\r\n`);
}

/** Hover until xterm has underlined the link (its decoration is a class on the terminal's element). */
async function hover(page: import("@playwright/test").Page, text: string) {
  const p = await pointAt(page, text, 0, Math.min(text.length, 12));
  await page.mouse.move(p.x - 3, p.y);
  await page.mouse.move(p.x, p.y);
  return p;
}

test("Cmd/Ctrl+click on https://example.com/x opens it once, through the app's opener", async ({ page }) => {
  await ready(page);
  const p = await hover(page, URL_OK);
  await expect(page.locator(".xterm .xterm-cursor-pointer")).toHaveCount(1); // xterm's pointer cursor over a link
  const key = await modKey(page);
  await page.keyboard.down(key);
  await page.mouse.click(p.x, p.y);
  await page.keyboard.up(key);
  await expect.poll(() => opened(page)).toEqual([URL_OK]);
  await settle(page);
  expect(await opened(page)).toEqual([URL_OK]); // once, not twice
});

test("a plain click does not open it (it still selects text, so a TUI's own mouse handling is not broken)", async ({ page }) => {
  await ready(page);
  const p = await hover(page, URL_OK);
  await page.mouse.click(p.x, p.y);
  await settle(page);
  expect(await opened(page)).toEqual([]);
});

test("the wrong modifier does not open it (Ctrl on macOS, Cmd on Windows and Linux; Shift or Alt with the right key)", async ({ page }) => {
  await ready(page);
  const p = await hover(page, URL_OK);
  const mac = await page.evaluate(() => /Mac/.test(navigator.platform));
  for (const keys of [[mac ? "Control" : "Meta"], [await modKey(page), "Shift"], [await modKey(page), "Alt"]]) {
    for (const k of keys) await page.keyboard.down(k);
    await page.mouse.click(p.x, p.y);
    for (const k of keys.reverse()) await page.keyboard.up(k);
  }
  await settle(page);
  expect(await opened(page)).toEqual([]);
});

test("http://user:pw@example.com and file:///etc/passwd do nothing, with the key held", async ({ page }) => {
  await ready(page);
  const key = await modKey(page);
  for (const text of ["http://user:pw@example.com/secret", "file:///etc/passwd"]) {
    const p = await pointAt(page, text, 0, 14);
    await page.mouse.move(p.x - 3, p.y);
    await page.mouse.move(p.x, p.y);
    await page.keyboard.down(key);
    await page.mouse.click(p.x, p.y);
    await page.keyboard.up(key);
  }
  await settle(page);
  expect(await opened(page)).toEqual([]);
});

test("hovering a link says which key to hold, and the hint goes when the mouse leaves", async ({ page }) => {
  await ready(page);
  await hover(page, URL_OK);
  const tip = page.locator(".term-linktip");
  await expect(tip).toBeVisible();
  const mac = await page.evaluate(() => /Mac/.test(navigator.platform));
  await expect(tip).toHaveText(mac ? "⌘+click to open" : "Ctrl+click to open");
  await page.mouse.move(5, 400);
  await expect(tip).toHaveCount(0);
});

/** The hint's box, the terminal's screen, a line's height and the top of the row the pointer is on, in page pixels. */
const hintBox = (page: import("@playwright/test").Page, pointerY: number) =>
  page.evaluate((y) => {
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; rows: number }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm')!;
    const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host)!;
    const screen = host.querySelector(".xterm-screen")!.getBoundingClientRect();
    const tip = document.querySelector(".term-linktip")!.getBoundingClientRect();
    const line = screen.height / term.rows;
    return { top: tip.top, bottom: tip.bottom, screenTop: screen.top, line, rowTop: screen.top + Math.floor((y - screen.top) / line) * line };
  }, pointerY);

test("the hint stands a line clear of the link: the line above the link stays uncovered, and a link on the first line gets it below", async ({ page }) => {
  await ready(page);
  const p = await hover(page, URL_OK);
  await expect(page.locator(".term-linktip")).toBeVisible();
  const g = await hintBox(page, p.y);
  // one whole line of air between the hint and the link's own line: that line is the one above the link
  expect(g.bottom).toBeLessThanOrEqual(g.rowTop - g.line + 0.5);
  expect(g.bottom).toBeGreaterThan(g.rowTop - 2 * g.line);
  expect(g.top).toBeGreaterThanOrEqual(g.screenTop - 0.5);

  // no room above a link on the first line: the hint goes the same distance below it
  await page.mouse.move(5, 400);
  await feed(page, "\x1b[2J\x1b[Hhttps://example.com/top is on the first line\r\n");
  const q = await hover(page, "https://example.com/top");
  await expect(page.locator(".term-linktip")).toBeVisible();
  const h = await hintBox(page, q.y);
  expect(h.rowTop).toBeCloseTo(h.screenTop, 0);
  expect(h.top).toBeGreaterThanOrEqual(h.rowTop + 2 * h.line - 0.5);
});

/** A hyperlink the program marks itself: `ESC ] 8 ;; url ST text ESC ] 8 ;; ST`. */
const osc8 = (url: string, text: string) => `\x1b]8;;${url}\x1b\\${text}\x1b]8;;\x1b\\`;

test("a hyperlink the program marked itself (OSC 8) follows the same rule: Cmd/Ctrl+click only, through the app's opener, with no dialog", async ({ page }) => {
  // xterm's own handler for these asks with a confirm() dialog and then calls window.open itself
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await openApp(page);
  await newTerminal(page);
  await feed(page, `\r\nread ${osc8("https://example.com/osc8", "the release notes")} first\r\n${osc8("http://user:pw@example.com/secret", "signed in")} or ${osc8("file:///etc/passwd", "a local file")}\r\n`);
  const key = await modKey(page);

  // the hint names the key, as for an address found in the text
  const p = await hover(page, "the release notes");
  await expect(page.locator(".term-linktip")).toBeVisible();
  // a plain click: nothing opens and nothing asks
  await page.mouse.click(p.x, p.y);
  await settle(page);
  expect(await opened(page)).toEqual([]);
  expect(dialogs).toEqual([]);

  // with the key: the marked address, once, through openExternal (the page's window.open with the address)
  await page.keyboard.down(key);
  await page.mouse.click(p.x, p.y);
  await page.keyboard.up(key);
  await expect.poll(() => opened(page)).toEqual(["https://example.com/osc8"]);
  await settle(page);
  expect(await opened(page)).toEqual(["https://example.com/osc8"]);

  // an address with a user name and password, or another scheme: nothing, with the key held
  for (const text of ["signed in", "a local file"]) {
    const q = await hover(page, text);
    await page.keyboard.down(key);
    await page.mouse.click(q.x, q.y);
    await page.keyboard.up(key);
  }
  await settle(page);
  expect(await opened(page)).toEqual(["https://example.com/osc8"]);
  expect(dialogs).toEqual([]);
});

test("the bell and OSC 9 / OSC 777 still reach xterm's parser with the link and find add-ons loaded", async ({ page }) => {
  await ready(page);
  // the handlers sessions.ts registers return false (not consumed), so a handler registered after them sees the
  // escape too: the add-ons must not have swallowed it first
  const seen = await page.evaluate(async () => {
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; parser: { registerOscHandler(id: number, fn: (d: string) => boolean): void } }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host)!;
    const got: string[] = [];
    term.parser.registerOscHandler(9, (d) => (got.push(`9:${d}`), false));
    term.parser.registerOscHandler(777, (d) => (got.push(`777:${d}`), false));
    const { feed } = (await import("/src/sessions/term/engine.ts" as string)) as { feed: (t: unknown, d: string, done?: () => void) => void };
    await new Promise<void>((res) => feed(term, "\x1b]9;build done\x07\x1b]777;notify;title;body\x07", res));
    return got;
  });
  expect(seen).toEqual(["9:build done", "777:notify;title;body"]);
});
