// The two clipboard settings on the Terminal page, both off by default (mock host): copy on select puts a mouse
// selection on the clipboard only when it is on; right-click pastes only when it is on; Ctrl+C with no selection
// still reaches the program; and a picture or file pasted on a terminal still goes through the drop/paste path
// (e2e/sessions-attach.spec.ts has its own check of that path and must stay green).
import { expect, test, type Page } from "@playwright/test";
import { clipWrites, feed, mock, newTerminal, openApp, pointAt, settle, typed } from "./term-find-helpers";

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

async function selectWord(page: Page, word: string) {
  const a = await pointAt(page, word, 0, 1);
  const b = await pointAt(page, word, word.length - 1, 1);
  await page.mouse.move(a.x - 2, a.y);
  await page.mouse.down();
  await page.mouse.move((a.x + b.x) / 2, b.y, { steps: 4 });
  await page.mouse.move(b.x + 2, b.y, { steps: 4 });
  await page.mouse.up();
}

const selected = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; getSelection(): string }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    return [...w.__omherTerms].find((t) => t.element === host)?.getSelection() ?? "";
  });

test("both settings are off by default: a selection copies nothing and a right click pastes nothing", async ({ page }) => {
  await openApp(page, { clipboard: "FROM-CLIPBOARD" });
  await newTerminal(page);
  await feed(page, "\r\nselect-me-please\r\n");
  await selectWord(page, "select-me-please");
  await expect.poll(() => selected(page)).toContain("select-me");
  await settle(page);
  expect(await clipWrites(page)).toEqual([]);
  const p = await pointAt(page, "(mock)");
  const before = await typed(page);
  await page.mouse.click(p.x, p.y, { button: "right" });
  await settle(page);
  expect((await typed(page)).slice(before.length)).toBe("");
});

test("copy on select: the selection is on the clipboard once the mouse is let go, and only when the setting is on", async ({ page }) => {
  await openApp(page, { term: { copyOnSelect: true } });
  await newTerminal(page);
  await feed(page, "\r\nselect-me-please\r\n");
  await selectWord(page, "select-me-please");
  await expect.poll(() => clipWrites(page)).toEqual(["select-me-please"]);
});

test("turning copy on select on in Settings applies to a terminal that is already open", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\r\nselect-me-please\r\n");
  await selectWord(page, "select-me-please");
  await settle(page);
  expect(await clipWrites(page)).toEqual([]);
  // the page's own setter (what the Terminal page calls); the open terminal reads it when the mouse is let go
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ copyOnSelect: true });
  });
  await page.mouse.click(5, 5);
  await selectWord(page, "select-me-please");
  await expect.poll(() => clipWrites(page)).toEqual(["select-me-please"]);
});

test("a click that selects nothing copies nothing even with copy on select on", async ({ page }) => {
  await openApp(page, { term: { copyOnSelect: true } });
  await newTerminal(page);
  await feed(page, "\r\nsome text\r\n");
  const p = await pointAt(page, "some text");
  await page.mouse.click(p.x, p.y);
  await settle(page);
  expect(await clipWrites(page)).toEqual([]);
});

test("right-click pastes the clipboard into the program when the setting is on, and Ctrl+right-click does not", async ({ page }) => {
  await openApp(page, { term: { rightClickPaste: true }, clipboard: "pasted-text" });
  await newTerminal(page);
  const p = await pointAt(page, "(mock)");
  const before = await typed(page);
  await page.mouse.click(p.x, p.y, { button: "right" });
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("pasted-text");
  const mid = await typed(page);
  await page.keyboard.down("Control");
  await page.mouse.click(p.x, p.y, { button: "right" });
  await page.keyboard.up("Control");
  await settle(page);
  expect(await typed(page)).toBe(mid);
});

test("right-click paste leaves a program that has mouse reporting on without a second paste", async ({ page }) => {
  await openApp(page, { term: { rightClickPaste: true }, clipboard: "once" });
  await newTerminal(page);
  await feed(page, "\x1b[?1000h\x1b[?1006h"); // mouse reporting on, as a TUI asks for it
  const p = await pointAt(page, "(mock)");
  const before = await typed(page);
  await page.mouse.click(p.x, p.y, { button: "right" });
  await expect.poll(async () => (await typed(page)).slice(before.length)).toContain("once");
  await settle(page);
  const sent = (await typed(page)).slice(before.length);
  expect(sent.split("once").length - 1).toBe(1);
  expect(sent).not.toMatch(/\x1b\[<2;/); // the right button's mouse report was not sent as well
});

test("Ctrl+C with no selection still reaches the program, with both settings on", async ({ page }) => {
  await openApp(page, { term: { copyOnSelect: true, rightClickPaste: true } });
  await newTerminal(page);
  const before = await typed(page);
  await page.keyboard.press("Control+c");
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("\x03");
  expect(await clipWrites(page)).toEqual([]);
});

test("the Terminal page has both rows, off, under Clipboard, and switching one leaves the other", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const copy = page.getByTestId("term-copy-select");
  const paste = page.getByTestId("term-right-paste");
  await expect(copy.getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await expect(paste.getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await copy.getByRole("radio", { name: "On" }).click();
  await expect(copy.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await expect(paste.getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ copyOnSelect: true, rightClickPaste: false });
  await expect(page.getByTestId("term-copy-select-row")).toContainText("Copy on select");
  await expect(page.getByTestId("term-right-paste-row")).toContainText("Right-click pastes");
});

test("a picture pasted on a terminal still goes through the drop/paste path, not into the program as text", async ({ page }) => {
  await openApp(page, { term: { copyOnSelect: true, rightClickPaste: true } });
  await newTerminal(page);
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" }));
    document.querySelector("[data-testid=terminal]")!.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await expect
    .poll(async () => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).some((c) => c.op === "file.save")))
    .toBe(true);
  expect(await typed(page)).toMatch(/session-files\/s\d+\/1-image\.png/);
});
