// The terminal engine on the mock host: the GPU renderer (lazy chunk, off/on/auto), a lost context, terminals that
// leave the page, Unicode 11 widths and `feed`'s `done` callbacks. Chromium; the WebKit numbers are in bench/render.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

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

type Gpu = "auto" | "on" | "off";

/** The app on the mock host, terminal settings set before it loads, and every xterm instance reachable as
 *  `__termTerms` (recorded where the session store makes it; the page itself is untouched). */
async function open(page: Page, gpu: Gpu) {
  await page.addInitScript((g) => {
    if (!sessionStorage.getItem("__kept")) {
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.sessions.open");
      localStorage.removeItem("omher.resume");
    }
    localStorage.setItem("omher.term", JSON.stringify({ gpu: g }));
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh"];
  }, gpu);
  await page.route("**/src/sessions/sessions.ts*", async (route) => {
    const r = await route.fetch();
    const body = (await r.text()).replace("const fit = new FitAddon();", "const fit = new FitAddon(); (globalThis.__termTerms ??= []).push(term);");
    await route.fulfill({ response: r, body });
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** A new Claude Code session opened as a terminal; returns its session id. */
async function newTerminal(page: Page): Promise<string> {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  const term = page.getByTestId("terminal");
  await expect(term).toBeVisible();
  const id = (await term.getAttribute("data-session")) as string;
  await expect.poll(() => lineText(page, id)).toContain("(mock)");
  return id;
}

/** The text of the terminal's first lines, from xterm's buffer (a GPU-drawn terminal has no text in the page). */
const lineText = (page: Page, index: number | string) =>
  page.evaluate((i) => {
    const terms = (globalThis as unknown as { __termTerms: { buffer: { active: { getLine(n: number): { translateToString(t: boolean): string } | undefined } } }[] }).__termTerms;
    const t = typeof i === "number" ? terms?.[i] : terms?.[terms.length - 1];
    if (!t) return "";
    let s = "";
    for (let n = 0; n < 6; n++) s += t.buffer.active.getLine(n)?.translateToString(true) ?? "";
    return s;
  }, index);

const renderer = (page: Page) =>
  page.evaluate(async () => (await import("/src/sessions/term/engine.ts" as string)).rendererInUse() as "gpu" | "standard" | null);

const canvasCount = (page: Page) => page.locator('[data-testid="terminal"] .xterm canvas').count();

/** The shown terminal's WebGL canvas (xterm also keeps a 2D canvas for links): null when it has none, else whether
 *  its context is alive. */
const glState = (page: Page) =>
  page.evaluate(() => {
    for (const c of document.querySelectorAll<HTMLCanvasElement>('[data-testid="terminal"] .xterm canvas')) {
      const gl = c.getContext("webgl2");
      if (gl) return gl.isContextLost() ? "lost" : "live";
    }
    return null;
  });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("gpu on: a canvas under the terminal, the renderer is the GPU, and the text is still there", async ({ page }) => {
  await open(page, "on");
  await newTerminal(page);
  await expect.poll(() => renderer(page)).toBe("gpu");
  expect(await canvasCount(page)).toBeGreaterThan(0);
  expect(await lineText(page, "last")).toContain("(mock)");
});

test("gpu off: no canvas, the add-on's chunk is never requested", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (r) => {
    if (/addon-webgl/.test(r.url())) requested.push(r.url());
  });
  await open(page, "off");
  await newTerminal(page);
  await expect.poll(() => renderer(page)).toBe("standard");
  expect(await canvasCount(page)).toBe(0);
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect(requested).toEqual([]);
});

test("gpu auto: where the rule says no (a software renderer, or macOS) the standard renderer draws and the chunk is never requested", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (r) => {
    if (/addon-webgl/.test(r.url())) requested.push(r.url());
  });
  await open(page, "auto");
  await newTerminal(page);
  await expect.poll(() => renderer(page)).toBe("standard");
  expect(await canvasCount(page)).toBe(0);
  expect(requested).toEqual([]);
});

test("the add-on's chunk is not loaded with the app", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (r) => {
    if (/addon-webgl/.test(r.url())) requested.push(r.url());
  });
  await open(page, "on");
  await page.waitForLoadState("networkidle");
  expect(requested).toEqual([]);
  await newTerminal(page);
  await expect.poll(() => renderer(page)).toBe("gpu");
  expect(requested.length).toBeGreaterThan(0);
});

test("a lost context: the terminal draws with the standard renderer at once and its text is readable", async ({ page }) => {
  await open(page, "on");
  await newTerminal(page);
  await expect.poll(() => renderer(page)).toBe("gpu");
  expect(await glState(page)).toBe("live");
  await page.evaluate(() => {
    for (const c of document.querySelectorAll<HTMLCanvasElement>('[data-testid="terminal"] .xterm canvas')) {
      const gl = c.getContext("webgl2");
      if (gl) gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
  });
  await expect.poll(() => renderer(page)).toBe("standard");
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  expect(await lineText(page, "last")).toContain("(mock)");
  // typing still shows: the terminal is alive
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("hello");
  await expect(page.locator(".xterm-rows")).toContainText("hello");
});

test("20 terminal sessions one after another: none blank, none without its renderer", async ({ page }) => {
  test.setTimeout(180_000);
  await open(page, "on");
  const ids: string[] = [];
  for (let i = 0; i < 20; i++) ids.push(await newTerminal(page));
  // each one, in turn: its text is there and, shown, it draws with a live GPU context
  for (const id of ids) {
    await page.getByTestId(`session-${id}`).locator(".ss-open").click();
    await expect(page.getByTestId("terminal")).toHaveAttribute("data-session", id);
    await expect.poll(() => renderer(page)).toBe("gpu");
    expect(await glState(page)).toBe("live");
    expect(await lineText(page, ids.indexOf(id))).toContain("(mock)");
  }
  // only the shown terminal holds a GPU context
  const held = await page.evaluate(() => [...document.querySelectorAll<HTMLCanvasElement>(".term-host canvas")].filter((c) => c.getContext("webgl2")).length);
  expect(held).toBe(1);
});

test("Unicode 11 widths: 한글 😀 表 puts the cursor where Unicode 11 says", async ({ page }) => {
  await open(page, "off");
  await newTerminal(page);
  const r = await page.evaluate(async () => {
    const t = (globalThis as unknown as { __termTerms: { write(d: string, cb: () => void): void; reset(): void; buffer: { active: { cursorX: number } }; unicode: { activeVersion: string } }[] }).__termTerms.at(-1)!;
    t.reset();
    await new Promise<void>((res) => t.write("한글 😀 表", res));
    return { x: t.buffer.active.cursorX, version: t.unicode.activeVersion };
  });
  // 한 2 + 글 2 + space 1 + 😀 2 + space 1 + 表 2
  expect(r).toEqual({ x: 10, version: "11" });
});

test("feed: every done runs once, in order", async ({ page }) => {
  await open(page, "off");
  await newTerminal(page);
  const r = await page.evaluate(async () => {
    const eng = await import("/src/sessions/term/engine.ts" as string);
    const t = (globalThis as unknown as { __termTerms: unknown[] }).__termTerms.at(-1);
    const calls: number[] = [];
    const big = "x".repeat(200_000) + "\r\n";
    for (let i = 0; i < 40; i++) eng.feed(t, i % 7 === 0 ? big : `line ${i}\r\n`, () => calls.push(i));
    await new Promise<void>((res) => eng.feed(t, "end\r\n", res));
    return calls;
  });
  expect(r).toEqual(Array.from({ length: 40 }, (_, i) => i));
});
