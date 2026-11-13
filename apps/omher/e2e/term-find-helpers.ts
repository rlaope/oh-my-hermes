// Shared by e2e/term-engine-links.spec.ts, term-engine-input.spec.ts and term-find*.spec.ts: the app on the mock host
// with a terminal session open, text fed through the engine's real `feed()`, and a way to point the mouse at a
// piece of text in the terminal. Never opens a real browser: `window.open` (what openExternal uses outside Tauri) and
// the clipboard are stubbed and record what they were asked.
import { expect, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

export async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
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

export interface OpenOpts {
  theme?: "dark" | "light";
  /** terminal settings stored before the app loads (the omher.term record) */
  term?: Record<string, unknown>;
  /** text the clipboard holds (navigator.clipboard.readText) */
  clipboard?: string;
}

type Spy = { __opened: unknown[][]; __clipWrites: string[]; __clipText: string };

/** Opt-in: the platform the page reports (`navigator.platform`), for example `OMHER_E2E_PLATFORM=Win32`, so the
 *  paths the app takes off macOS (Ctrl is the key, Ctrl+<key> in a terminal is the program's) run on any machine.
 *  Unset, the page reports the machine's own. */
const PLATFORM = process.env.OMHER_E2E_PLATFORM || "";

/** The app on the mock host. `window.open` and the clipboard are stubs that record into window.__opened / __clipWrites. */
export async function openApp(page: Page, o: OpenOpts = {}) {
  if (PLATFORM) {
    await page.addInitScript((p) => {
      Object.defineProperty(navigator, "platform", { configurable: true, get: () => p });
    }, PLATFORM);
  }
  await page.addInitScript(
    ([theme, term, clip]) => {
      if (!sessionStorage.getItem("__kept")) {
        localStorage.removeItem("omher.sessions.recent");
        localStorage.removeItem("omher.sessions.open");
        localStorage.removeItem("omher.resume");
      }
      if (theme) localStorage.setItem("omher.theme", theme as string);
      localStorage.setItem("omher.term", JSON.stringify(term ?? {}));
      const w = window as unknown as Spy & { __omherPickFolder: string; __omherMockAgents: string[] };
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "omh"];
      w.__opened = [];
      w.__clipWrites = [];
      w.__clipText = (clip as string) ?? "";
      window.open = ((...args: unknown[]) => {
        w.__opened.push(args);
        return null;
      }) as typeof window.open;
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async (t: string) => void w.__clipWrites.push(t),
          readText: async () => w.__clipText,
        },
      });
    },
    [o.theme ?? null, o.term ?? {}, o.clipboard ?? ""] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A new Claude Code session opened as a terminal; returns its session id once the mock program has printed. */
export async function newTerminal(page: Page): Promise<string> {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  const term = page.getByTestId("terminal");
  await expect(term).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  return (await term.getAttribute("data-session")) as string;
}

/** Text into the shown terminal through the engine's own `feed()`, as program output. Resolves once xterm took it. */
export async function feed(page: Page, text: string): Promise<void> {
  await page.evaluate(async (data) => {
    const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement }> };
    const host = document.querySelector('[data-testid="terminal"] .xterm');
    const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host);
    if (!term) throw new Error("no terminal");
    const { feed } = (await import("/src/sessions/term/engine.ts" as string)) as { feed: (t: unknown, d: string, done?: () => void) => void };
    await new Promise<void>((res) => feed(term, data, res));
  }, text);
}

/** Where a piece of text sits on the screen right now: the middle of its first `len` characters, in page pixels. */
export async function pointAt(page: Page, text: string, from = 0, len = text.length): Promise<{ x: number; y: number }> {
  const p = await page.evaluate(
    ([needle, a, n]) => {
      const w = window as unknown as { __omherTerms?: Set<{ element?: HTMLElement; cols: number; rows: number; buffer: { active: { viewportY: number; getLine(i: number): { translateToString(t: boolean): string } | undefined } } }> };
      const host = document.querySelector('[data-testid="terminal"] .xterm');
      const term = [...(w.__omherTerms ?? [])].find((t) => t.element === host);
      if (!term) return null;
      const screen = host!.querySelector(".xterm-screen")!.getBoundingClientRect();
      const buf = term.buffer.active;
      for (let r = 0; r < term.rows; r++) {
        const line = buf.getLine(buf.viewportY + r)?.translateToString(true) ?? "";
        const c = line.indexOf(needle as string);
        if (c < 0) continue;
        const cw = screen.width / term.cols;
        const ch = screen.height / term.rows;
        return { x: screen.left + (c + (a as number) + (n as number) / 2) * cw, y: screen.top + (r + 0.5) * ch };
      }
      return null;
    },
    [text, from, len] as const,
  );
  if (!p) throw new Error(`"${text}" is not on the terminal's screen`);
  return p;
}

export const platformIsMac = (page: Page) => page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));
/** The key that opens links and find: Meta on macOS, Control elsewhere. */
export const modKey = async (page: Page) => ((await platformIsMac(page)) ? "Meta" : "Control");

export const opened = (page: Page) => page.evaluate(() => (window as unknown as Spy).__opened.map((a) => a[0] as string));
export const clipWrites = (page: Page) => page.evaluate(() => (window as unknown as Spy).__clipWrites);

type Call = { op: string; data?: string };
/** Everything the terminal's program was sent (typing, a paste), in order. */
export const typed = (page: Page) =>
  page.evaluate(() =>
    ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? [])
      .filter((c) => c.op === "write")
      .map((c) => c.data ?? "")
      .join(""),
  );

/** Nothing more happens for a moment (a negative check that does not rely on a timeout of one frame). */
export const settle = (page: Page, ms = 400) => page.waitForTimeout(ms);
