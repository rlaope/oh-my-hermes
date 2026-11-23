// The terminal's clipboard keys on Windows, as Windows Terminal has them: Ctrl+V pastes through the page's own paste
// (the multi-line confirm and a pasted picture's path included) and only once, Ctrl+C copies while there is a
// selection (and clears it) and is the program's ^C otherwise, Ctrl+Shift+C / V and the Insert keys still work, and
// AltGr (Ctrl+Alt) takes none of them. Ctrl+Shift+A selects all and Ctrl+Shift+K clears, as off macOS everywhere. The
// page reports Win32 here whatever machine runs it.
//
// WebView2 pastes on Ctrl+V by itself: a keydown the page did not cancel becomes one `paste` event on the focused
// field. Headless Chromium does not do that on every OS (not on macOS) and never from the stubbed clipboard, so the
// page below plays WebView2's part: a Ctrl+V or Ctrl+Shift+V keydown that nothing cancelled is followed by a paste
// event carrying `__nativeClip`. A paste the app also made itself would show up twice; one it blocked, not at all.
import { expect, test, type Page } from "@playwright/test";
import { clipWrites, feed, mock, newTerminal, openApp, pointAt, settle, typed } from "./term-find-helpers";

test.beforeEach(async () => {
  test.skip(!!process.env.OMHER_E2E_PLATFORM && !/^Win/.test(process.env.OMHER_E2E_PLATFORM), `the run reports ${process.env.OMHER_E2E_PLATFORM} for every page`);
  await mock("mock.reset");
});

type Native = { text?: string; png?: boolean };

/** A Windows page whose Ctrl+V / Ctrl+Shift+V pastes `__nativeClip` the way WebView2 does. */
async function openWindows(page: Page, clip: Native = {}) {
  await page.addInitScript((c) => {
    Object.defineProperty(navigator, "platform", { configurable: true, get: () => "Win32" });
    const w = window as unknown as { __nativeClip: Native; __nativePastes: number };
    w.__nativeClip = c;
    w.__nativePastes = 0;
    window.addEventListener("keydown", (e) => {
      if (e.defaultPrevented || !e.ctrlKey || e.altKey || e.metaKey || e.code !== "KeyV") return;
      const dt = new DataTransfer();
      if (w.__nativeClip.text) dt.setData("text/plain", w.__nativeClip.text);
      if (w.__nativeClip.png) dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" }));
      w.__nativePastes++;
      e.target?.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
      // this stands in for the native paste: Chromium's own (Linux, Windows) would paste the real clipboard as well
      e.preventDefault();
    });
  }, clip);
  // what the app would read itself (navigator.clipboard.readText): never asked on Windows, so a second copy shows
  await openApp(page, { clipboard: clip.text ?? "" });
  await newTerminal(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
}

const hasSelection = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; hasSelection(): boolean }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    return [...w.__omherTerms].find((x) => x.element === host)!.hasSelection();
  });
const selectAll = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; selectAll(): void }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    [...w.__omherTerms].find((x) => x.element === host)!.selectAll();
  });
const sentSince = async (page: Page, before: string) => (await typed(page)).slice(before.length);

test("Ctrl+V pastes the clipboard's text once, and the program gets no ^V", async ({ page }) => {
  await openWindows(page, { text: "echo pasted-on-windows" });
  const before = await typed(page);
  await page.keyboard.press("Control+V");
  await expect.poll(() => sentSince(page, before)).toBe("echo pasted-on-windows");
  await settle(page);
  expect(await sentSince(page, before)).toBe("echo pasted-on-windows");
  expect(await page.evaluate(() => (window as unknown as { __nativePastes: number }).__nativePastes)).toBe(1);
});

test("Ctrl+V of several lines asks first, once; Enter pastes them once", async ({ page }) => {
  await openWindows(page, { text: "echo one\necho two" });
  const before = await typed(page);
  await page.keyboard.press("Control+V");
  await expect(page.getByTestId("term-paste-confirm")).toHaveCount(1);
  await expect(page.getByTestId("term-paste-preview")).toHaveText("echo one\necho two");
  await settle(page);
  expect(await sentSince(page, before)).toBe("");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("term-paste-confirm")).toHaveCount(0);
  await expect.poll(() => sentSince(page, before)).toBe("echo one\recho two");
  await settle(page);
  expect(await sentSince(page, before)).toBe("echo one\recho two");
});

test("Ctrl+V of a picture types its saved path, as a pasted picture does", async ({ page }) => {
  await openWindows(page, { png: true });
  const before = await typed(page);
  await page.keyboard.press("Control+V");
  await expect.poll(() => sentSince(page, before)).toMatch(/session-files\/s\d+\/1-image\.png/);
  expect(await sentSince(page, before)).not.toContain("\x16");
});

test("Ctrl+C copies a selection and clears it; the next Ctrl+C, with nothing selected, is the program's ^C", async ({ page }) => {
  await openWindows(page);
  await feed(page, "\r\ncopy-on-windows-5521\r\n");
  await selectAll(page);
  const before = await typed(page);
  await page.keyboard.press("Control+C");
  await expect.poll(() => clipWrites(page)).toEqual([expect.stringContaining("copy-on-windows-5521")]);
  expect(await hasSelection(page)).toBe(false);
  await settle(page);
  expect(await sentSince(page, before)).toBe("");
  await page.keyboard.press("Control+C");
  await expect.poll(() => sentSince(page, before)).toBe("\x03");
  expect(await clipWrites(page)).toHaveLength(1);
});

test("Ctrl+Shift+C, Ctrl+Insert copy and Ctrl+Shift+V pastes once; the selection stays, no ^C or ^V reaches the program", async ({ page }) => {
  await openWindows(page, { text: "from-ctrl-shift-v" });
  await feed(page, "\r\nkeep-selected-8830\r\n");
  await selectAll(page);
  const before = await typed(page);
  await page.keyboard.press("Control+Shift+C");
  await expect.poll(() => clipWrites(page)).toEqual([expect.stringContaining("keep-selected-8830")]);
  await page.keyboard.press("Control+Insert");
  await expect.poll(async () => (await clipWrites(page)).length).toBe(2);
  expect(await hasSelection(page)).toBe(true);
  await page.keyboard.press("Control+Shift+V");
  await expect.poll(() => sentSince(page, before)).toBe("from-ctrl-shift-v");
  await settle(page);
  expect(await sentSince(page, before)).toBe("from-ctrl-shift-v");
});

test("AltGr (Ctrl+Alt) with C or V neither copies nor pastes, and the key is left to type its character", async ({ page }) => {
  await openWindows(page, { text: "never-pasted" });
  await feed(page, "\r\naltgr-text-1207\r\n");
  await selectAll(page);
  // what the app does with the keys itself: a clipboard read, or a key it cancelled (an AltGr key must stay
  // uncancelled, or its character is never typed). WebView2 itself pastes on Ctrl+V only with no other modifier, as
  // the stand-in does, so a paste here could only be the app's own.
  await page.evaluate(() => {
    const w = window as unknown as { __reads: number; __cancelled: string[] };
    w.__reads = 0;
    w.__cancelled = [];
    const clip = navigator.clipboard as unknown as { readText: () => Promise<string> };
    const read = clip.readText.bind(clip);
    clip.readText = () => {
      w.__reads++;
      return read();
    };
    window.addEventListener("keydown", (e) => {
      if (e.altKey && e.defaultPrevented) w.__cancelled.push(e.code);
    });
  });
  const before = await typed(page);
  await page.keyboard.press("Control+Alt+KeyC");
  await page.keyboard.press("Control+Alt+KeyV");
  await settle(page);
  expect(await clipWrites(page)).toEqual([]);
  expect(await hasSelection(page)).toBe(true);
  expect(await sentSince(page, before)).not.toContain("never-pasted");
  expect(await page.evaluate(() => (window as unknown as { __reads: number }).__reads)).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __cancelled: string[] }).__cancelled)).toEqual([]);
});

test("a key pressed while a copying Ctrl+C is held lets no C through; a copy the clipboard refused keeps the selection", async ({ page }) => {
  await openWindows(page);
  await feed(page, "\r\nheld-copy-4410\r\n");
  // the program asked for the Kitty protocol with key-release events (flags 1|2): a C key-up let through would reach
  // it as CSI 99;5:3 u
  await feed(page, "\x1b[>3u");
  await selectAll(page);
  let before = await typed(page);
  // Ctrl+C copies (the selection goes); Shift pressed and let go meanwhile; then C and Ctrl let go
  await page.keyboard.down("Control");
  await page.keyboard.down("KeyC");
  await expect.poll(() => hasSelection(page)).toBe(false);
  await page.keyboard.down("Shift");
  await page.keyboard.up("Shift");
  await page.keyboard.up("KeyC");
  await page.keyboard.up("Control");
  await settle(page);
  expect(await clipWrites(page)).toEqual([expect.stringContaining("held-copy-4410")]);
  expect(await sentSince(page, before)).not.toMatch(/\x03|\x1b\[99;5/);
  // the clipboard refuses the next copy: the selection stays, so nothing is lost and the next Ctrl+C tries again
  await page.evaluate(() => {
    (navigator.clipboard as unknown as { writeText: () => Promise<void> }).writeText = () => Promise.reject(new Error("denied"));
  });
  await selectAll(page);
  before = await typed(page);
  await page.keyboard.press("Control+C");
  await settle(page);
  expect(await hasSelection(page)).toBe(true);
  expect(await sentSince(page, before)).not.toMatch(/\x03|\x1b\[99;5u/);
});

test("Ctrl+Up / Ctrl+Down jump between prompts at the shell's prompt, and stay a running program's", async ({ page }) => {
  await openWindows(page);
  const OSC = (b: string) => `\x1b]${b}\x07`;
  const round = (name: string) =>
    `${OSC("133;A")}${name}$ ${OSC("133;B")}run ${name}\r\n${OSC("133;C")}${Array.from({ length: 40 }, (_, i) => `${name} out ${i}\r\n`).join("")}${OSC("133;D;0")}`;
  await feed(page, `\r\n${round("p1")}${round("p2")}${OSC("133;A")}p3$ ${OSC("133;B")}`);
  const view = () =>
    page.evaluate(() => {
      const w = window as unknown as { __omherTerms: Set<{ element?: HTMLElement; buffer: { active: { viewportY: number; baseY: number } } }> };
      const host = document.querySelector('[data-testid="terminal"] .xterm');
      const b = [...w.__omherTerms].find((x) => x.element === host)!.buffer.active;
      return { y: b.viewportY, base: b.baseY };
    });
  const bottom = await view();
  expect(bottom.y).toBe(bottom.base);
  let before = await typed(page);
  // at the bottom, Ctrl+Down has nowhere to go: the shell gets it
  await page.keyboard.press("Control+ArrowDown");
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("\x1b[1;5B");
  // at the prompt, Ctrl+Up goes to the previous prompt and the shell gets nothing
  before = await typed(page);
  await page.keyboard.press("Control+ArrowUp");
  await expect.poll(async () => (await view()).y).toBeLessThan(bottom.base);
  // Ctrl+Down: the next prompt is the live one, on the bottom screen, so the view goes back to the bottom
  await page.keyboard.press("Control+ArrowDown");
  await expect.poll(async () => (await view()).y).toBe(bottom.base);
  await settle(page);
  expect((await typed(page)).slice(before.length)).toBe("");
  // a command runs (C without D), an inline program such as the OMH TUI: Ctrl+Up is its key
  // it printed enough that the earlier prompts are all above the screen: without the rule, Ctrl+Up would jump there
  await feed(page, `run p3\r\n${OSC("133;C")}${Array.from({ length: 40 }, (_, i) => `p3 out ${i}\r\n`).join("")}`);
  before = await typed(page);
  const running = await view();
  await page.keyboard.press("Control+ArrowUp");
  await expect.poll(async () => (await typed(page)).slice(before.length)).toBe("\x1b[1;5A");
  expect((await view()).y).toBe(running.y);
});

test("Ctrl+Shift+A selects the whole terminal and Ctrl+Shift+K clears it; the program gets neither, plain Ctrl+A stays its own", async ({ page }) => {
  await openWindows(page);
  await feed(page, "\r\nclear-me-6612\r\n");
  const before = await typed(page);
  await page.keyboard.press("Control+Shift+A");
  await expect.poll(() => hasSelection(page)).toBe(true);
  await page.keyboard.press("Control+Shift+K");
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).not.toContainText("clear-me-6612");
  await settle(page);
  expect(await sentSince(page, before)).toBe("");
  await page.keyboard.press("Control+A");
  await expect.poll(() => sentSince(page, before)).toBe("\x01");
});

test("the terminal's menu and Settings' keyboard list name the Windows keys: Ctrl, never ⌘", async ({ page }) => {
  await openWindows(page);
  await feed(page, "\r\nmenu-keys-3391\r\n");
  const p = await pointAt(page, "menu-keys-3391");
  await page.mouse.click(p.x, p.y, { button: "right" });
  await expect(page.getByTestId("term-menu")).toBeVisible();
  await expect(page.getByTestId("term-menu-copy")).toContainText("Ctrl+C");
  await expect(page.getByTestId("term-menu-paste")).toContainText("Ctrl+V");
  await expect(page.getByTestId("term-menu-selectAll")).toContainText("Ctrl+Shift+A");
  await expect(page.getByTestId("term-menu-clear")).toContainText("Ctrl+Shift+K");
  await expect(page.getByTestId("term-menu")).not.toContainText("⌘");
  await page.keyboard.press("Escape");
  await page.getByTestId("nav-settings").click();
  const list = page.getByTestId("shortcuts");
  await expect(list).toContainText("Ctrl+C · Ctrl+V · Ctrl+Shift+C · Ctrl+Shift+V");
  await expect(list).toContainText("Ctrl+Shift+A");
  await expect(list).toContainText("Ctrl+Shift+K");
  await expect(list).toContainText("Ctrl+↑ · Ctrl+↓");
  await expect(list).not.toContainText(/[⌘⌥⌃⇧]/);
});

test("the chat composer on Windows keeps its own editing keys (no app shortcut cancels one), a pasted picture is one attachment, Ctrl+Enter sends", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "platform", { configurable: true, get: () => "Win32" });
    const w = window as unknown as { __prevented: string[] };
    w.__prevented = [];
    // after every listener ran: a key someone cancelled
    window.addEventListener("keydown", (e) => setTimeout(() => e.defaultPrevented && w.__prevented.push(`${e.ctrlKey ? "Ctrl+" : ""}${e.shiftKey ? "Shift+" : ""}${e.key}`)), true);
  });
  await openApp(page);
  const box = page.getByTestId("composer");
  await box.fill("first line");
  await box.focus();
  // Ctrl+C and Ctrl+X first, with nothing selected, so the browser's real clipboard (Chromium copies natively on Linux)
  // stays as it was for the specs after this one
  const keys = ["Control+C", "Control+X", "Control+A", "Control+V", "Control+Z", "Control+Y", "Control+Shift+Z", "Control+ArrowLeft", "Control+ArrowRight", "Control+Shift+ArrowLeft", "Control+Backspace", "Control+Delete", "Control+Home", "Control+End", "Shift+Home", "Shift+End", "Shift+Enter"];
  for (const k of keys) await page.keyboard.press(k);
  await settle(page, 200);
  expect(await page.evaluate(() => (window as unknown as { __prevented: string[] }).__prevented)).toEqual([]);
  // a picture pasted as WebView2 delivers it becomes one attachment (a text paste stays the field's own: the composer
  // takes only files from a paste, and no key above was cancelled)
  await box.fill("");
  await box.evaluate((el) => {
    const d = new DataTransfer();
    d.items.add(new File(["clip"], "pasted.png", { type: "image/png" }));
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: d, bubbles: true, cancelable: true }));
  });
  await expect(page.getByTestId("attach-chip")).toHaveCount(1);
  await page.getByTestId("attach-chip").getByTestId("attach-remove").click();
  // Ctrl+Enter sends, as Enter does
  await box.fill("sent with ctrl enter");
  await box.press("Control+Enter");
  await expect(box).toHaveValue("");
});
