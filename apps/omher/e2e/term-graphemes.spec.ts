// Character widths by grapheme (xterm's unicode-graphemes add-on, Unicode 15), on the mock host: an emoji made of
// several code points (a ZWJ family, a flag, a skin tone) is one wide character, two cells, as the agents' TUIs
// count it. Before, Unicode 11 counted each part of the family (six cells).
import { expect, test, type Page } from "@playwright/test";
import { mock, newTerminal, openApp } from "./term-find-helpers";

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** Write `text` at the start of a clean line through the engine's own `feed()`; the cursor's column after it. */
const columnAfter = (page: Page, text: string) =>
  page.evaluate(async (data) => {
    type T = { element?: HTMLElement; buffer: { active: { cursorX: number } }; unicode: { activeVersion: string } };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const t = [...(window as unknown as { __omherTerms: Set<T> }).__omherTerms].find((x) => x.element === host)!;
    const { feed } = (await import("/src/sessions/term/engine.ts" as string)) as { feed: (t: unknown, d: string, done?: () => void) => void };
    await new Promise<void>((res) => feed(t, `\r\n\x1b[2K${data}`, res));
    return { x: t.buffer.active.cursorX, version: t.unicode.activeVersion };
  }, text);

test("👨‍👩‍👧x puts x at column 2: the family is one wide character", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  // x is written at column 2, so the cursor ends at column 3
  expect(await columnAfter(page, "👨‍👩‍👧x")).toEqual({ x: 3, version: "15-graphemes" });
  expect((await columnAfter(page, "👨‍👩‍👧")).x).toBe(2);
});

test("flags, skin tones and keycaps are two cells; CJK and Hangul stay two, ASCII one", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  expect((await columnAfter(page, "🇰🇷x")).x).toBe(3);
  expect((await columnAfter(page, "👍🏽x")).x).toBe(3);
  // 한 2 + 글 2 + space 1 + 😀 2 + space 1 + 表 2 (as before)
  expect((await columnAfter(page, "한글 😀 表")).x).toBe(10);
  expect((await columnAfter(page, "abc")).x).toBe(3);
});
