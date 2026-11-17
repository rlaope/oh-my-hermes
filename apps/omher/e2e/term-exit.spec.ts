// TERMINALS behave like a real terminal (owner, 2026-11-17, on 0.2.12: "exit하면 자동으로 꺼지거나 해야지", "클로드 꺼지면
// 다시 터미널로 돌아가야지", "한글 같은거 입력좀씹힘", "터미널 폰트 otty랑같은걸로"):
// 1. a Shell row whose login shell ends (exit, exit 3, Ctrl+D) closes and leaves TERMINALS, as its x does, and the
//    neighbour row (else the bot chat) opens; a shell that could not start stays, with its error;
// 2. a CLI row whose CLI ends (/exit, a crash) goes on as the login shell in the same row and terminal: one dim line,
//    shell_start in the same folder (no other program), the shell mark; the next CLI started there is followed
//    (session-fg codex -> the Codex mark and name); then exit closes the row;
// 3. Korean typed through an input method reaches the program exactly once: Chromium's composition events (CDP
//    Input.imeSetComposition / insertText), and the sequence WebKit (the macOS window) sends for the 2-Set Korean input
//    source, which has no composition events (insertText, then insertReplacementText edits in place; xterm.js#6284);
// 4. the terminal draws in the bundled JetBrains Mono (Otty's font) at 13px, with Symbols Nerd Font Mono for glyphs,
//    and Korean takes two cells.
// Shots (dark, 1440x900) when OMHER_SHOTS=<dir>: termexit-back-to-shell.png, termexit-codex-after.png,
// termexit-korean-font.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const WEB = "/home/you/code/web-app";
const API = "/home/you/code/api-server";

test.use({ colorScheme: "dark", viewport: { width: 1440, height: 900 } });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page) {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders", "omher.term"]) localStorage.removeItem(k);
      sessionStorage.setItem("__kept", "1");
    }
    localStorage.setItem("omher.theme", "dark");
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = "/home/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "grok", "opencode", "omh", "pi"];
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

const list = (page: Page) => page.evaluate(() => (window as any).__omherSessions.getState().list as { id: string; agent: string; status: string; error?: string }[]);
const pty = (page: Page, id: string) => page.evaluate((i) => (window as any).__omherSessions.ptyOf(i) as number | null, id);
const shellCalls = (page: Page) => page.evaluate(() => ((window as any).__omherShellCalls ?? []) as { op: string; id: number; cwd?: string | null; data?: string }[]);
const agentCalls = (page: Page) => page.evaluate(() => ((window as any).__omherSessionCalls ?? []) as { op: string; id?: number; agent?: string; data?: string }[]);
const screen = (page: Page) => page.locator('[data-testid="terminal"] .xterm-rows');

/** Start `agent` (or `shell`) from the TERMINALS + menu in `folder`; its session id once its program printed. */
async function newTerm(page: Page, agent: string, folder: string): Promise<string> {
  const before = (await list(page)).map((r) => r.id);
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.getByTestId("session-folder").click();
  const recent = page.locator(`[data-testid=session-folder-pick][title="${folder}"]`);
  if (await recent.count()) await recent.click();
  else {
    await page.evaluate((f) => ((window as unknown as Record<string, unknown>).__omherPickFolder = f), folder);
    await page.getByTestId("session-choose").click();
  }
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect.poll(async () => (await list(page)).find((r) => !before.includes(r.id))?.id ?? null).not.toBeNull();
  const id = (await list(page)).find((r) => !before.includes(r.id))!.id;
  await expect(screen(page)).toContainText("(mock)");
  return id;
}

async function typeLine(page: Page, text: string) {
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.mouse.move(1000, 700);
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

// ---- 1. a shell that ends closes its row ----------------------------------------------------------------------------

test("a Shell row closes when its shell exits: the row, its tab and view go, and the neighbour row opens", async ({ page }) => {
  await open(page);
  const keep = await newTerm(page, "shell", API);
  const gone = await newTerm(page, "shell", WEB);
  await expect(page.getByTestId(`session-${gone}`)).toBeVisible();
  await typeLine(page, "exit");
  await expect(page.getByTestId(`session-${gone}`)).toHaveCount(0);
  expect((await list(page)).map((r) => r.id)).toEqual([keep]);
  // no Ended leftover anywhere; the other terminal is the one shown now
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", keep);
  await expect(page.getByTestId(`session-${keep}`)).toHaveClass(/active/);
  await expect(page.getByTestId("session-ended")).toHaveCount(0);
  // its shell is not closed twice (it is gone already)
  const id = (await shellCalls(page)).filter((c) => c.op === "start")[1].id;
  expect((await shellCalls(page)).filter((c) => c.op === "close" && c.id === id)).toEqual([]);

  // a non-zero exit after typing closes it too; then nothing is left and the bot chat shows
  await typeLine(page, "exit 3");
  await expect(page.getByTestId(`session-${keep}`)).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("session-none")).toBeVisible();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
});

test("Ctrl+D at the prompt closes the Shell row; one ending while another session is open closes without moving you", async ({ page }) => {
  await open(page);
  const a = await newTerm(page, "shell", WEB);
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  await page.keyboard.press("Control+D");
  await expect(page.getByTestId(`session-${a}`)).toHaveCount(0);

  const b = await newTerm(page, "shell", WEB);
  const c = await newTerm(page, "shell", API);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", c);
  // b's shell is told `exit` while c is on screen (as a script in it would end it)
  const bp = await pty(page, b);
  await page.evaluate(async (p) => {
    const m = (await import("/src/terminal/host.ts" as string)) as { getShellHost(): { write(id: number, d: string): Promise<void> } };
    await m.getShellHost().write(p as number, "exit\r");
  }, bp);
  await expect(page.getByTestId(`session-${b}`)).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", c);
});

test("a shell that cannot start stays listed with its error; one that dies at once before any typing stays too", async ({ page }) => {
  await open(page);
  await page.evaluate(() => ((window as any).__omherShellDie = { error: "no login shell: /bin/nosuch is not in /etc/shells" }));
  const a = await newTerm(page, "shell", WEB).catch(() => null);
  const rows = await list(page);
  const failed = a ?? rows[0].id;
  await expect(page.getByTestId(`session-${failed}`)).toBeVisible();
  await expect(page.getByTestId(`session-${failed}`)).toHaveAttribute("data-term-status", "err");
  await expect(screen(page)).toContainText("no login shell");
  expect((await list(page)).find((r) => r.id === failed)).toMatchObject({ status: "failed", error: "no login shell: /bin/nosuch is not in /etc/shells" });

  await page.evaluate(() => ((window as any).__omherShellDie = { code: 1 }));
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-shell`).click();
  await expect(screen(page)).toContainText("could not read its profile");
  const died = (await list(page))[0];
  await expect(page.getByTestId(`session-${died.id}`)).toHaveAttribute("data-term-status", "err");
  expect(died.status).toBe("exited");
});

// ---- 2. a CLI that ends goes back to the shell in the same row --------------------------------------------------------

test("Claude Code /exit: the same row and terminal go on as the login shell, then codex there shows the Codex mark, then exit closes it", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "claude", WEB);
  const row = page.getByTestId(`session-${id}`);
  await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "claude");
  const firstPty = await pty(page, id);
  await typeLine(page, "remember PLUM-42");
  await typeLine(page, "/exit");
  // one dim line, then the shell's prompt in the same terminal; what Claude Code printed is still there
  await expect(screen(page)).toContainText("Claude Code ended — back to your shell");
  await expect(screen(page)).toContainText("login shell in /home/you/code/web-app");
  await expect(screen(page)).toContainText("remember PLUM-42");
  // the shell came from shell_start in the row's folder; no other program was asked for
  const starts = (await shellCalls(page)).filter((c) => c.op === "start");
  expect(starts).toEqual([expect.objectContaining({ cwd: WEB })]);
  expect((await agentCalls(page)).filter((c) => c.op === "start").map((c) => c.agent)).toEqual(["claude"]);
  // the same row, now a shell: shell icon, name Shell, running, the same terminal element
  await expect(page.getByTestId(`session-${id}`)).toHaveCount(1);
  await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  await expect(row.getByTestId("session-name")).toHaveText("Shell");
  await expect(row).toHaveAttribute("data-term-status", /idle|busy/);
  expect((await list(page)).find((r) => r.id === id)).toMatchObject({ agent: "shell", status: "running" });
  const shellPty = await pty(page, id);
  expect(shellPty).not.toBe(firstPty);
  expect(shellPty).toBe(starts[0].id);
  await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
  await shot(page, "termexit-back-to-shell");

  // the person starts codex in that shell: the shell reports it in front and the row follows it
  await typeLine(page, "codex");
  await page.evaluate((p) => (window as any).__omherEmitSessionFg({ id: p, agent: "codex" }), shellPty);
  await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "codex");
  await expect(row.getByTestId("session-name")).toHaveText("Codex");
  await expect(page.getByTestId("header").getByTestId("term-row-mark")).toHaveAttribute("data-agent", "codex");
  // Codex's own screen, as it draws it (the alternate screen, over the shell's)
  await page.evaluate(
    (p) =>
      (window as any).__omherMockOut(
        p,
        "\x1b[?1049h\x1b[H\x1b[2J╭──────────────────────────────────────────────╮\r\n│ \x1b[1m>_ OpenAI Codex\x1b[0m (v0.98.0)                    │\r\n│                                              │\r\n│ \x1b[2mmodel:\x1b[0m     gpt-5.3-codex high                │\r\n│ \x1b[2mdirectory:\x1b[0m ~/code/web-app                    │\r\n╰──────────────────────────────────────────────╯\r\n\r\n\x1b[1m›\x1b[0m Make the checkout total update when a coupon is removed\r\n\r\n• Read src/checkout/cart.ts\r\n• Ran pnpm test -- cart\r\n",
      ),
    shellPty,
  );
  await shot(page, "termexit-codex-after");
  // codex quits: back to the shell icon; then exit closes the row
  await page.evaluate((p) => (window as any).__omherMockOut(p, "\x1b[?1049l"), shellPty);
  await page.evaluate((p) => (window as any).__omherEmitSessionFg({ id: p, agent: null }), shellPty);
  await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  await typeLine(page, "exit");
  await expect(page.getByTestId(`session-${id}`)).toHaveCount(0);
  expect(await list(page)).toEqual([]);
});

test("a CLI that crashes (exit 3) also goes back to the shell, saying how it ended; its input reaches the shell after", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "codex", WEB);
  await typeLine(page, "after 10 exit 3");
  await expect(screen(page)).toContainText("Codex ended with exit 3 — back to your shell");
  await expect(page.getByTestId(`session-${id}`).getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  const shellPty = await pty(page, id);
  await expect.poll(async () => (await shellCalls(page)).some((c) => c.op === "start" && c.id === shellPty)).toBe(true);
  await typeLine(page, "pwd");
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "write" && c.id === shellPty).map((c) => c.data).join("")).toContain("pwd");
  // the agent host got nothing after its program ended
  const after = (await agentCalls(page)).filter((c) => c.op === "write" && c.data === "p");
  expect(after).toEqual([]);
});

// ---- 3. Korean input -----------------------------------------------------------------------------------------------

/** What the shell of session `id` was sent, from index `from` of its writes. */
const sent = async (page: Page, p: number, from = 0) =>
  (await shellCalls(page))
    .filter((c) => c.op === "write" && c.id === p)
    .slice(from)
    .map((c) => c.data)
    .join("");

/** Replay what WebKit sends for the macOS 2-Set Korean input source (xterm.js#6284's Safari 26.2 trace): no
 *  composition events; each syllable starts as `insertText` and is edited in place with `insertReplacementText`; each
 *  keyCode 229 keydown arrives after its input. `plain` keys pass through the IME; `enter` comes right after the last
 *  syllable. */
async function webkit2Set(page: Page, steps: (string[] | string)[]) {
  await page.evaluate(async (all) => {
    const ta = document.querySelector<HTMLTextAreaElement>('[data-testid="terminal"] .xterm-helper-textarea')!;
    ta.focus();
    let start = ta.value.length;
    const input = (inputType: string, data: string) => {
      ta.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, composed: true, inputType, data }));
      if (inputType === "insertReplacementText") ta.value = ta.value.slice(0, start) + data;
      else {
        start = ta.value.length;
        ta.value += data;
      }
      ta.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, inputType, data }));
    };
    const key = (type: string, k: string, code: number) => {
      const e = new KeyboardEvent(type, { bubbles: true, cancelable: true, key: k, code: k === "Enter" ? "Enter" : "KeyA" });
      Object.defineProperty(e, "keyCode", { value: code });
      Object.defineProperty(e, "which", { value: code });
      ta.dispatchEvent(e);
      return !e.defaultPrevented;
    };
    const k229 = () => {
      key("keydown", "Process", 229);
      key("keyup", "Process", 229);
    };
    for (const step of all) {
      if (Array.isArray(step)) {
        // one syllable: [first jamo, edits...] (an edit equal to the syllable's end state repeats as WebKit does)
        input("insertText", step[0]);
        k229();
        for (const e of step.slice(1)) {
          input("insertReplacementText", e);
          k229();
        }
      } else if (step === "\r") {
        key("keydown", "Enter", 13);
        key("keyup", "Enter", 13);
      } else {
        const ok = key("keydown", step, step.toUpperCase().charCodeAt(0));
        if (ok) {
          const kp = new KeyboardEvent("keypress", { bubbles: true, cancelable: true, key: step });
          Object.defineProperty(kp, "charCode", { value: step.charCodeAt(0) });
          Object.defineProperty(kp, "keyCode", { value: step.charCodeAt(0) });
          ta.dispatchEvent(kp);
        }
        key("keyup", step, step.toUpperCase().charCodeAt(0));
      }
      await new Promise((r) => setTimeout(r, 4));
    }
  }, steps);
}

const S = {
  안: ["ㅇ", "아", "안", "안"],
  녕: ["ㄴ", "녀", "녕", "녕"],
  하: ["ㅎ", "하", "핫", "하"],
  세: ["세", "셍", "세"],
  요: ["요", "요"],
  한: ["ㅎ", "하", "한", "한"],
  글: ["ㄱ", "그", "글"],
  입: ["ㅇ", "이", "입", "입"],
  력: ["ㄹ", "려", "력"],
};

test("Korean from the macOS 2-Set input source (WebKit, no composition events) reaches the shell exactly, with English and a fast Enter", async ({ page }) => {
  await open(page);
  const id = await newTerm(page, "shell", WEB);
  const p = (await pty(page, id))!;
  let from = (await shellCalls(page)).filter((c) => c.op === "write" && c.id === p).length;
  await webkit2Set(page, [S.안, S.녕, S.하, S.세, S.요, " ", S.한, S.글, " ", S.입, S.력, "\r"]);
  await expect.poll(() => sent(page, p, from)).toBe("안녕하세요 한글 입력\r");
  await expect(screen(page)).toContainText("안녕하세요 한글 입력");

  from = (await shellCalls(page)).filter((c) => c.op === "write" && c.id === p).length;
  await webkit2Set(page, ["g", "i", "t", " ", S.한, S.글, " ", "o", "k", " ", S.입, S.력, "\r"]);
  await expect.poll(() => sent(page, p, from)).toBe("git 한글 ok 입력\r");
});

test("Korean through composition events (Chromium, CDP) reaches the shell exactly once, with English and a fast Enter", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "CDP input method events are Chromium's");
  await open(page);
  const id = await newTerm(page, "shell", WEB);
  const p = (await pty(page, id))!;
  await page.locator('[data-testid="terminal"] .xterm-helper-textarea').focus();
  const cdp = await page.context().newCDPSession(page);
  const word = async (w: string) => {
    for (const syl of w) {
      if (syl === " " || /[a-z]/.test(syl)) {
        await cdp.send("Input.insertText", { text: syl });
        continue;
      }
      for (const s of (S as Record<string, string[]>)[syl]) await cdp.send("Input.imeSetComposition", { text: s, selectionStart: s.length, selectionEnd: s.length });
      await cdp.send("Input.insertText", { text: syl });
    }
  };
  let from = (await shellCalls(page)).filter((c) => c.op === "write" && c.id === p).length;
  await word("안녕하세요 한글 입력");
  await page.keyboard.press("Enter");
  await expect.poll(() => sent(page, p, from)).toBe("안녕하세요 한글 입력\r");
  // mixed English, and Enter while the last syllable is still being composed
  from = (await shellCalls(page)).filter((c) => c.op === "write" && c.id === p).length;
  await word("ok 한");
  for (const s of S.글) await cdp.send("Input.imeSetComposition", { text: s, selectionStart: s.length, selectionEnd: s.length });
  await page.keyboard.press("Enter");
  await expect.poll(() => sent(page, p, from)).toBe("ok 한글\r");
});

// ---- 4. the font ---------------------------------------------------------------------------------------------------

test("the terminal draws in the bundled JetBrains Mono at 13px with Symbols Nerd Font Mono; Korean takes two cells", async ({ page }) => {
  await open(page);
  await newTerm(page, "shell", WEB);
  const look = await page.evaluate(async () => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const term = [...((window as any).__omherTerms as Set<any>)].find((t) => t.element === host);
    await document.fonts.ready;
    return {
      family: term.options.fontFamily as string,
      size: term.options.fontSize as number,
      jb: document.fonts.check('13px "JetBrains Mono"'),
      jbBold: document.fonts.check('bold 13px "JetBrains Mono"'),
      jbItalic: document.fonts.check('italic 13px "JetBrains Mono"'),
      // the symbols file is fetched on its first glyph (unicode-range): ask for one
      sym: (await document.fonts.load('13px "Symbols Nerd Font Mono"', "\ue0b0")).length > 0,
      loaded: [...document.fonts].filter((f) => f.status === "loaded").map((f) => `${f.family.replace(/"/g, "")} ${f.weight} ${f.style}`).sort(),
      // the measured cell is JetBrains Mono's advance (0.6em), not Menlo's or SF Mono's
      cell: term._core._renderService.dimensions.css.cell.width as number,
    };
  });
  expect(look.family.split(",")[0].trim()).toBe('"JetBrains Mono"');
  expect(look.family).toContain('"Symbols Nerd Font Mono"');
  expect(look.size).toBe(13);
  expect({ jb: look.jb, jbBold: look.jbBold, jbItalic: look.jbItalic, sym: look.sym }).toEqual({ jb: true, jbBold: true, jbItalic: true, sym: true });
  expect(look.loaded).toEqual(expect.arrayContaining(["JetBrains Mono 400 normal", "Symbols Nerd Font Mono 400 normal"]));
  expect(look.cell).toBeGreaterThan(7.6);
  expect(look.cell).toBeLessThan(8.0);
  // Korean is two cells wide each (unicode 11 widths) and nothing overlaps: the cursor lands after 4 cells
  await typeLine(page, "");
  await page.evaluate((p) => (window as any).__omherMockOut(p, "\r\n한글 OK\r\n\x1b[32m  main\x1b[0m  \ue0a0 \ue0b0 ready\r\n"), (await page.evaluate(() => (window as any).__omherSessions.ptyOf((window as any).__omherSessions.getState().list[0].id))) as number);
  const cells = () => page.evaluate(() => {
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const term = [...((window as any).__omherTerms as Set<any>)].find((t) => t.element === host);
    const b = term.buffer.active;
    for (let y = 0; y < b.length; y++) {
      const line = b.getLine(y);
      if (line?.translateToString(true).startsWith("한글")) return [0, 1, 2, 3, 4].map((x) => [line.getCell(x)?.getChars(), line.getCell(x)?.getWidth()]);
    }
    return null;
  });
  // (the terminal parses what it is given a moment later)
  await expect.poll(cells).toEqual([["한", 2], ["", 0], ["글", 2], ["", 0], [" ", 1]]);
  await webkit2Set(page, [S.안, S.녕, S.하, S.세, S.요, " ", S.한, S.글, " ", S.입, S.력]);
  await shot(page, "termexit-korean-font");
});

test("Settings › Terminal still sets another font and size; the bundled font comes back when the field is cleared", async ({ page }) => {
  await open(page);
  await newTerm(page, "shell", WEB);
  const opts = () =>
    page.evaluate(() => {
      const host = document.querySelector('[data-testid="terminal"] .xterm');
      const term = [...((window as any).__omherTerms as Set<any>)].find((t) => t.element === host);
      return { family: term.options.fontFamily as string, size: term.options.fontSize as number };
    });
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ fontFamily: "Menlo", fontSize: 15 });
  });
  await expect.poll(opts).toEqual({ family: expect.stringMatching(/^"Menlo", "JetBrains Mono"/), size: 15 });
  await page.evaluate(async () => {
    const m = (await import("/src/sessions/term/settings.ts" as string)) as { writeTermSettings(p: object): void };
    m.writeTermSettings({ fontFamily: "", fontSize: 13 });
  });
  await expect.poll(opts).toEqual({ family: expect.stringMatching(/^"JetBrains Mono"/), size: 13 });
});
