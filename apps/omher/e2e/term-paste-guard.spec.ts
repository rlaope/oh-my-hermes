// Multi-line paste protection (mock host): a paste of several lines into a program that has not turned on
// bracketed paste (DECSET 2004) shows a confirm in the terminal's pane and sends nothing until Paste (or Enter);
// Cancel (or Esc) sends nothing. With bracketed paste on, or the setting off, it goes straight through. The same
// guard covers the right-click paste and the bottom panel's terminals, and Settings > Terminal has the switch.
import { expect, test, type Page } from "@playwright/test";
import { feed, mock, newTerminal, openApp, settle, typed } from "./term-find-helpers";

test.use({ colorScheme: "dark" });
test.beforeEach(async () => {
  await mock("mock.reset");
});

const THREE = "echo one\necho two\necho three";
const confirm = (page: Page) => page.getByTestId("term-paste-confirm");

/** A paste on the shown terminal, as Cmd/Ctrl+V or the Edit menu's Paste delivers it: a `paste` event on xterm's
 *  textarea with the text on the clipboard data. */
async function pasteInto(page: Page, text: string, scope = '[data-testid="terminal"]') {
  await page.evaluate(
    ([t, sel]) => {
      const ta = document.querySelector<HTMLTextAreaElement>(`${sel} .xterm-helper-textarea`);
      if (!ta) throw new Error("no terminal textarea");
      ta.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", t);
      ta.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    },
    [text, scope] as const,
  );
}

async function sentSince(page: Page, before: string) {
  return (await typed(page)).slice(before.length);
}

test("three lines without bracketed paste: a confirm with the count and the lines, nothing sent until Paste", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  const before = await typed(page);
  await pasteInto(page, THREE);
  await expect(confirm(page)).toBeVisible();
  await expect(confirm(page)).toContainText("Paste 3 lines?");
  await expect(page.getByTestId("term-paste-preview")).toHaveText("echo one\necho two\necho three");
  // inside the terminal's own pane
  const [c, t] = await Promise.all([confirm(page).boundingBox(), page.getByTestId("terminal").boundingBox()]);
  expect(c!.y).toBeGreaterThanOrEqual(t!.y);
  expect(c!.x).toBeGreaterThanOrEqual(t!.x);
  expect(c!.x + c!.width).toBeLessThanOrEqual(t!.x + t!.width);
  await settle(page);
  expect(await sentSince(page, before)).toBe("");
  await page.getByTestId("term-paste-ok").click();
  await expect(confirm(page)).toHaveCount(0);
  await expect.poll(() => sentSince(page, before)).toBe("echo one\recho two\recho three");
});

test("Enter pastes and Esc cancels; Cancel sends nothing and gives the keyboard back to the terminal", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  const before = await typed(page);
  await pasteInto(page, THREE);
  await expect(confirm(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(confirm(page)).toHaveCount(0);
  await settle(page);
  expect(await sentSince(page, before)).toBe("");

  await pasteInto(page, "a\nb\n");
  await expect(confirm(page)).toContainText("Paste 2 lines?");
  await page.keyboard.press("Enter");
  await expect(confirm(page)).toHaveCount(0);
  await expect.poll(() => sentSince(page, before)).toBe("a\rb\r");

  const mid = await typed(page);
  await pasteInto(page, THREE);
  await page.getByTestId("term-paste-cancel").click();
  await expect(confirm(page)).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.activeElement?.classList.contains("xterm-helper-textarea") ?? false)).toBe(true);
  await page.keyboard.type("x");
  await expect.poll(() => sentSince(page, mid)).toBe("x");
});

test("with bracketed paste on (the program sent ESC[?2004h) the paste goes straight through, bracketed", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await feed(page, "\x1b[?2004h");
  const before = await typed(page);
  await pasteInto(page, THREE);
  await expect.poll(() => sentSince(page, before)).toBe("\x1b[200~echo one\recho two\recho three\x1b[201~");
  await expect(confirm(page)).toHaveCount(0);
  // and when the program turns it off again, the confirm is back
  await feed(page, "\x1b[?2004l");
  await pasteInto(page, THREE);
  await expect(confirm(page)).toBeVisible();
});

test("a single line goes straight through; with the setting off several lines do too", async ({ page }) => {
  await openApp(page, { term: { confirmPaste: false } });
  await newTerminal(page);
  const before = await typed(page);
  await pasteInto(page, "just one line");
  await expect.poll(() => sentSince(page, before)).toBe("just one line");
  await pasteInto(page, THREE);
  await expect.poll(() => sentSince(page, before)).toBe("just one lineecho one\recho two\recho three");
  await settle(page);
  await expect(confirm(page)).toHaveCount(0);
});

test("a long paste shows its first three lines and how many more there are", async ({ page }) => {
  await openApp(page);
  await newTerminal(page);
  await pasteInto(page, Array.from({ length: 12 }, (_, i) => `line ${i + 1}`).join("\n"));
  await expect(confirm(page)).toContainText("Paste 12 lines?");
  await expect(page.getByTestId("term-paste-preview")).toHaveText("line 1\nline 2\nline 3");
  await expect(confirm(page)).toContainText("and 9 more");
});

test("the right-click paste asks too", async ({ page }) => {
  await openApp(page, { term: { rightClickPaste: true }, clipboard: THREE });
  await newTerminal(page);
  const before = await typed(page);
  const box = (await page.getByTestId("terminal").boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: "right" });
  await expect(confirm(page)).toBeVisible();
  await settle(page);
  expect(await sentSince(page, before)).toBe("");
  await page.getByTestId("term-paste-ok").click();
  await expect.poll(() => sentSince(page, before)).toBe("echo one\recho two\recho three");
});

test("the bottom panel's terminal asks before a multi-line paste reaches its shell", async ({ page }) => {
  type Call = { op: string; data?: string };
  const shellTyped = () => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []).filter((c) => c.op === "write").map((c) => c.data ?? "").join(""));
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  const scope = '[data-testid="termpanel-terminal"]:not([hidden])';
  await expect(page.locator(`${scope} .xterm-rows`)).toContainText("login shell in");
  await pasteInto(page, THREE, scope);
  const panelConfirm = page.locator(`${scope} [data-testid="term-paste-confirm"]`);
  await expect(panelConfirm).toBeVisible();
  await settle(page);
  expect(await shellTyped()).toBe("");
  await page.keyboard.press("Enter");
  await expect.poll(shellTyped).toBe("echo one\recho two\recho three");
});

test("Settings > Terminal has \"Confirm multi-line paste\", on by default, and turning it off is stored", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  const sw = page.getByTestId("term-confirm-paste");
  await expect(page.getByTestId("term-confirm-paste-row")).toContainText("Confirm multi-line paste");
  await expect(sw.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Off" }).click();
  await expect(sw.getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term"))) ?? "{}")).toMatchObject({ confirmPaste: false });
});
