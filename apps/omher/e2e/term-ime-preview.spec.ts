// The syllable being typed through a Korean input method shows at the terminal's cursor, and stays there while the
// program echoes the syllables before it (owner, 2026-11-20: "한글 입력하면 깜빡거리고 뭔가 사라지는 느낌"). The
// preview (xterm's .composition-view, drawn by engine-ime.ts) was placed only when an input event came: the previous
// syllable is sent as the next one starts, before the program's echo moves the cursor, so the new preview sat on the
// cell where that syllable was then drawn and hid it, and jumped two cells right on the next keystroke.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark", viewport: { width: 1280, height: 820 } });

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

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function shell(page: Page) {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders", "omher.term"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    localStorage.setItem("omher.theme", "dark");
    (window as unknown as Record<string, unknown>).__omherPickFolder = "/home/you/code/web-app";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-shell").click();
  await expect(page.locator('[data-testid="terminal"] .xterm-rows')).toContainText("(mock)");
}

/** WebKit's 2-Set Korean (no composition events): `insertText` of a first jamo, or an `insertReplacementText` edit of
 *  the syllable, each followed by a keyCode 229 keydown, as engine-ime.ts's comment and e2e/ime-helpers.ts describe. */
const edit = (page: Page, inputType: "insertText" | "insertReplacementText", data: string) =>
  page.evaluate(
    ([inputType, data]) => {
      const ta = document.querySelector<HTMLTextAreaElement>('[data-testid="terminal"] .xterm-helper-textarea')!;
      ta.focus();
      ta.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, composed: true, inputType, data }));
      ta.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, inputType, data }));
      const k = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Process", code: "KeyA" });
      Object.defineProperty(k, "keyCode", { value: 229 });
      ta.dispatchEvent(k);
    },
    [inputType, data] as const,
  );

/** The preview and where it must be: the cell at the terminal's cursor. */
const where = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm')!;
    const term = [...((window as any).__omherTerms as Set<any>)].find((t) => t.element === host);
    const v = host.querySelector<HTMLElement>(".composition-view")!;
    const screen = host.querySelector<HTMLElement>(".xterm-screen")!;
    const b = term.buffer.active;
    const cw = screen.clientWidth / term.cols;
    const ch = screen.clientHeight / term.rows;
    return {
      text: v.textContent,
      shown: v.classList.contains("active"),
      cell: [Math.round(parseFloat(v.style.left) / cw), Math.round(parseFloat(v.style.top) / ch)],
      cursor: [Math.min(b.cursorX, term.cols - 1), b.cursorY],
      line: (b.getLine(b.baseY + b.cursorY)?.translateToString(true) ?? "") as string,
    };
  });

/** The mock shell echoes in the same task as the keystroke; a real one answers a moment later, through the pty. */
const lateEcho = (page: Page) =>
  page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm')!;
    const term = [...((window as any).__omherTerms as Set<any>)].find((t) => t.element === host);
    const write = term.write.bind(term);
    term.write = (d: string | Uint8Array, cb?: () => void) => void setTimeout(() => write(d, cb), 30);
  });

test("the syllable being typed stays at the cursor while the program echoes the one before it", async ({ page }) => {
  await shell(page);
  await lateEcho(page);
  for (const [t, d] of [["insertText", "ㅇ"], ["insertReplacementText", "아"], ["insertReplacementText", "안"]] as const) await edit(page, t, d);
  const first = await where(page);
  expect(first).toMatchObject({ text: "안", shown: true });
  expect(first.cell).toEqual(first.cursor);

  // the next syllable starts: 안 goes to the shell, ㄴ is shown; the shell's echo of 안 moves the cursor two cells
  await edit(page, "insertText", "ㄴ");
  await expect.poll(async () => (await where(page)).line).toContain("안");
  await expect.poll(async () => (await where(page)).cursor).toEqual([first.cursor[0] + 2, first.cursor[1]]);
  // the preview follows the cursor: it does not sit on (and hide) the echoed 안
  await expect.poll(async () => (await where(page)).cell).toEqual([first.cursor[0] + 2, first.cursor[1]]);
  expect(await where(page)).toMatchObject({ text: "ㄴ", shown: true });

  // and the next edit of the syllable draws it in the same place (no jump)
  await edit(page, "insertReplacementText", "녀");
  expect(await where(page)).toMatchObject({ text: "녀", shown: true, cell: [first.cursor[0] + 2, first.cursor[1]] });
});

test("the same through composition events (Chromium, CDP)", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "CDP input method events are Chromium's");
  await shell(page);
  await lateEcho(page);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  const cdp = await page.context().newCDPSession(page);
  const compose = (text: string) => cdp.send("Input.imeSetComposition", { text, selectionStart: text.length, selectionEnd: text.length });
  for (const s of ["ㅇ", "아", "안"]) await compose(s);
  const first = await where(page);
  expect(first).toMatchObject({ text: "안", shown: true });
  expect(first.cell).toEqual(first.cursor);
  await cdp.send("Input.insertText", { text: "안" });
  await compose("ㄴ");
  await expect.poll(async () => (await where(page)).cursor).toEqual([first.cursor[0] + 2, first.cursor[1]]);
  await expect.poll(async () => (await where(page)).cell).toEqual([first.cursor[0] + 2, first.cursor[1]]);
  expect(await where(page)).toMatchObject({ text: "ㄴ", shown: true });
});
