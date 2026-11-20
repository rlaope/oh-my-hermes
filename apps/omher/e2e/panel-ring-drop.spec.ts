// The bottom panel catches up with TERMINALS: a panel shell that rings (the bell, an OSC 9 message, an OSC 777
// notify; not an OSC 9;4 progress report) gives its tab a dot while the tab is not in front, no text kept, and picking
// the tab clears it; a file dropped on a panel pane is saved under the shell's own folder
// (`~/.omher/session-files/s0<shell id>/`) and its path typed at the prompt, shell-quoted, as a TERMINALS drop is.
import { expect, test, type Page } from "@playwright/test";
import { mock, openApp } from "./term-find-helpers";

type Call = { op: string; id?: number; data?: string; session?: string; name?: string; path?: string };
const shellCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: Call[] }).__omherShellCalls ?? []) as Call[]);
const sessionCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []) as Call[]);
const out = (page: Page, id: number, d: string) => page.evaluate(([p, s]) => (window as unknown as { __omherMockOut(p: number, d: string): boolean }).__omherMockOut(p as number, s as string), [id, d] as const);
const tab = (page: Page, i: number) => page.getByTestId("termpanel-tab").nth(i);

async function twoTabs(page: Page): Promise<[number, number]> {
  await openApp(page);
  await page.keyboard.press("Control+Backquote");
  await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("login shell in");
  await page.getByTestId("termpanel-new").click();
  await expect(page.getByTestId("termpanel-tab")).toHaveCount(2);
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "start").length).toBe(2);
  const [a, b] = (await shellCalls(page)).filter((c) => c.op === "start").map((c) => c.id!);
  return [a, b];
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a shell in a tab that is not in front rings: its tab gets a dot until it is picked; a progress report does not ring", async ({ page }) => {
  const [a, b] = await twoTabs(page);
  await expect(page.getByTestId("termpanel-ring")).toHaveCount(0);
  // the bell
  await out(page, a, "\x07");
  await expect(tab(page, 0).getByTestId("termpanel-ring")).toBeVisible();
  await expect(tab(page, 1).getByTestId("termpanel-ring")).toHaveCount(0);
  await tab(page, 0).getByRole("tab").click();
  await expect(page.getByTestId("termpanel-ring")).toHaveCount(0);
  // the tab in back is now the second one: a 9;4 progress report is not a ring, an OSC 9 message is
  await out(page, b, "\x1b]9;4;1;50\x07");
  await page.waitForTimeout(150);
  await expect(page.getByTestId("termpanel-ring")).toHaveCount(0);
  await out(page, b, "\x1b]9;build finished\x07");
  await expect(tab(page, 1).getByTestId("termpanel-ring")).toBeVisible();
  // its text is never shown on the tab
  await expect(tab(page, 1)).not.toContainText("build finished");
  await tab(page, 1).getByRole("tab").click();
  await expect(page.getByTestId("termpanel-ring")).toHaveCount(0);
  // OSC 777 notify
  await out(page, a, "\x1b]777;notify;Claude Code;needs you\x07");
  await expect(tab(page, 0).getByTestId("termpanel-ring")).toBeVisible();
  await expect(tab(page, 0)).not.toContainText("needs you");
});

test("a hidden panel's shell rings: its tab carries the dot when the panel comes back... and opening clears it", async ({ page }) => {
  const [, b] = await twoTabs(page);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeHidden();
  await out(page, b, "\x07");
  await expect(tab(page, 1).getByTestId("termpanel-ring")).toHaveCount(1);
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(page.getByTestId("termpanel-ring")).toHaveCount(0);
});

test("a file dropped on a panel pane is saved under its shell's folder and its quoted path typed at the prompt", async ({ page }) => {
  const [, b] = await twoTabs(page);
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File(["hello"], "my notes.txt", { type: "text/plain" }));
    const el = document.querySelector('[data-testid="termpanel-terminal"]:not([hidden])')!;
    for (const type of ["dragenter", "dragover", "drop"]) el.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  await expect.poll(async () => (await sessionCalls(page)).filter((c) => c.op === "file.save").map((c) => [c.session, c.name])).toEqual([[`s0${b}`, "my notes.txt"]]);
  // the shell's own quoting: single quotes on macOS and Linux, double quotes on Windows (the page's platform); the
  // picture's path below needs none on either
  const q = process.platform === "win32" ? '"' : "'";
  const want = `${q}/home/you/.omher/session-files/s0${b}/1-my notes.txt${q} `;
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === b).map((c) => c.data).join("")).toBe(want);
  // the other tab's shell got nothing
  expect((await shellCalls(page)).filter((c) => c.op === "write" && c.id !== b)).toEqual([]);
  // a picture pasted there takes the same path
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" }));
    document.querySelector('[data-testid="termpanel-terminal"]:not([hidden])')!.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === b).map((c) => c.data).join("")).toBe(`${want}/home/you/.omher/session-files/s0${b}/1-image.png `);
  // closing the tab removes the saved copies
  await page.getByTestId("termpanel-tab-close").nth(1).click();
  await expect.poll(async () => (await sessionCalls(page)).filter((c) => c.op === "file.remove").map((c) => c.session)).toEqual([`s0${b}`]);
});

test("a picture pasted on a panel pane whose program has bracketed paste on goes to it as a paste of the saved path", async ({ page }) => {
  const [, b] = await twoTabs(page);
  // Claude Code takes a picture's path as an image only inside a paste (DECSET 2004 on, as it turns it on)
  await out(page, b, "\x1b[?2004h");
  await expect
    .poll(() => page.evaluate(() => [...((window as unknown as { __omherTerms?: Set<{ modes: { bracketedPasteMode: boolean } }> }).__omherTerms ?? [])].some((t) => t.modes.bracketedPasteMode)))
    .toBe(true);
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" }));
    document.querySelector('[data-testid="termpanel-terminal"]:not([hidden])')!.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await expect
    .poll(async () => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === b).map((c) => c.data).join(""))
    .toBe(`\x1b[200~/home/you/.omher/session-files/s0${b}/1-image.png \x1b[201~`);
});
