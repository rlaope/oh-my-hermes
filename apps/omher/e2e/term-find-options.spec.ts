// Find options in a session terminal (mock host, the engine's real feed()): Match case (Aa, Alt+C) and Regular
// expression (.*, Alt+R) in the find bar. Match case tells "Foo" from "foo"; a regex finds `fo+`; an invalid
// pattern shows the field in an error state and finds nothing; the count and previous / next keep working; the
// toggles hold for the page load, in the next bar too.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, modKey, newTerminal, openApp } from "./term-find-helpers";

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

const LINES = "\r\nFoo alpha\r\nfoo beta\r\nfooo gamma\r\nFOO delta\r\nfo epsilon\r\n";

const bar = (page: Page) => page.getByTestId("term-find");
const input = (page: Page) => page.getByTestId("term-find-input");
const count = (page: Page) => page.getByTestId("term-find-count");
const caseBtn = (page: Page) => page.getByTestId("term-find-case");
const regexBtn = (page: Page) => page.getByTestId("term-find-regex");

async function openFind(page: Page) {
  await openApp(page);
  await newTerminal(page);
  await feed(page, LINES);
  await page.keyboard.press(`${await modKey(page)}+f`);
  await expect(input(page)).toBeFocused();
}

/** The text of the active match (the add-on selects it). */
const activeText = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; getSelection(): string }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    return [...w.__omherTerms].find((t) => t.element === host)?.getSelection() ?? "";
  });

test("both toggles are off at first; Match case tells Foo from foo, and previous / next stay on the exact case", async ({ page }) => {
  await openFind(page);
  await expect(caseBtn(page)).toHaveAttribute("aria-pressed", "false");
  await expect(regexBtn(page)).toHaveAttribute("aria-pressed", "false");
  await input(page).fill("Foo");
  // Foo, foo, foo(o), FOO
  await expect(count(page)).toHaveText(/^\d of 4$/);
  await caseBtn(page).click();
  await expect(caseBtn(page)).toHaveAttribute("aria-pressed", "true");
  await expect(count(page)).toHaveText("1 of 1");
  await expect.poll(() => activeText(page)).toBe("Foo");
  await input(page).fill("foo");
  await expect(count(page)).toHaveText(/^[12] of 2$/);
  const first = await count(page).textContent();
  await page.getByTestId("term-find-next").click();
  await expect(count(page)).not.toHaveText(first!);
  await expect.poll(() => activeText(page)).toBe("foo");
  await page.getByTestId("term-find-prev").click();
  await expect(count(page)).toHaveText(first!);
  // off again: every case
  await caseBtn(page).click();
  await expect(count(page)).toHaveText(/^\d of 4$/);
});

test("Regular expression: fo+ matches fo, foo and fooo; with Match case too, FOO and Foo drop out", async ({ page }) => {
  await openFind(page);
  await input(page).fill("fo+");
  await expect(count(page)).toHaveText("No matches"); // as plain text, "fo+" is nowhere
  await regexBtn(page).click();
  await expect(regexBtn(page)).toHaveAttribute("aria-pressed", "true");
  // Foo, foo, fooo, FOO, fo (no case)
  await expect(count(page)).toHaveText(/^\d of 5$/);
  await caseBtn(page).click();
  await expect(count(page)).toHaveText(/^\d of 3$/);
  await expect(input(page)).toBeFocused(); // a toggle clicked leaves the keyboard in the field
  // Enter walks the three, each the exact-case text the pattern matches
  const seen = new Set<string>();
  for (let i = 0; i < 3; i++) {
    const at = await count(page).textContent();
    await expect.poll(() => activeText(page)).toMatch(/^fo+$/);
    seen.add(await activeText(page));
    await page.keyboard.press("Enter");
    await expect(count(page)).not.toHaveText(at!);
  }
  expect([...seen].sort()).toEqual(["fo", "foo", "fooo"]);
});

test("an invalid pattern (an open bracket) shows the field in an error state and finds nothing, without an error on the page", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await openFind(page);
  await regexBtn(page).click();
  await input(page).fill("foo");
  await expect(count(page)).toHaveText(/^\d of 4$/);
  await input(page).fill("(");
  await expect(input(page)).toHaveAttribute("aria-invalid", "true");
  await expect(input(page)).toHaveClass(/tfind-bad/);
  await expect(count(page)).toHaveText("Invalid pattern");
  await expect(page.getByTestId("term-find-next")).toBeDisabled();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Shift+Enter");
  await expect.poll(() => activeText(page)).toBe("");
  // the highlights of the last valid search are gone too
  await expect(page.locator('[data-testid="terminal"] .xterm-decoration-container > *')).toHaveCount(0);
  // a valid pattern again: no error, matches again
  await input(page).fill("(fo)");
  await expect(input(page)).not.toHaveAttribute("aria-invalid", "true");
  await expect(count(page)).toHaveText(/^\d of 5$/);
  // the same text as plain text is not an error
  await regexBtn(page).click();
  await input(page).fill("(");
  await expect(input(page)).not.toHaveAttribute("aria-invalid", "true");
  await expect(count(page)).toHaveText("1 of 1"); // the mock program's "(mock)" banner
  expect(errors).toEqual([]);
});

test("a theme change while the bar holds an invalid pattern does not throw", async ({ page }) => {
  await openFind(page);
  await regexBtn(page).click();
  await input(page).fill("foo");
  await expect(count(page)).toHaveText(/^\d of 4$/);
  await input(page).fill("(");
  await expect(count(page)).toHaveText("Invalid pattern");
  const error = await page.evaluate(async () => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; options: { theme?: unknown } }> };
    const term = [...w.__omherTerms].find((t) => t.element === host)!;
    const { finderOf } = (await import("/src/sessions/term/engine-find.ts" as string)) as { finderOf(t: unknown): { restyle(): void } | undefined };
    term.options.theme = { background: "#ffffff", foreground: "#000000" };
    try {
      finderOf(term)!.restyle();
      return null;
    } catch (e) {
      return String(e);
    }
  });
  expect(error).toBeNull();
  await expect(count(page)).toHaveText("Invalid pattern");
});

test("Alt+C and Alt+R flip the toggles from the field; they hold for the next bar in the page load", async ({ page }) => {
  await openFind(page);
  await input(page).fill("fo+");
  await page.keyboard.press("Alt+r");
  await expect(regexBtn(page)).toHaveAttribute("aria-pressed", "true");
  await expect(input(page)).toHaveValue("fo+"); // the key typed nothing into the field
  await expect(count(page)).toHaveText(/^\d of 5$/);
  await page.keyboard.press("Alt+c");
  await expect(caseBtn(page)).toHaveAttribute("aria-pressed", "true");
  await expect(input(page)).toHaveValue("fo+");
  await expect(count(page)).toHaveText(/^\d of 3$/);
  await page.keyboard.press("Escape");
  await expect(bar(page)).toHaveCount(0);
  await page.keyboard.press(`${await modKey(page)}+f`);
  await expect(caseBtn(page)).toHaveAttribute("aria-pressed", "true");
  await expect(regexBtn(page)).toHaveAttribute("aria-pressed", "true");
  await input(page).fill("FO+");
  await expect(count(page)).toHaveText("1 of 1");
});
