// A session's header while its agent has work in the background (mock host `/lateask`, the event order of
// src-tauri/tests/fixtures/real/claude-13-late-ask.jsonl):
// 1. it never says "running" about work that only waits for the person. When every background subagent omher has a
//    row for waits on an open approval or question, and they are as many as the agent counts, the label reads
//    "1 waiting in the background" (four languages); a count that holds a command (no row), or one subagent still
//    running, keeps "N still running in the background".
// 2. nothing that matters is cut on a narrow chat: at 900, 1100, 1280 and 1440px, panel open and closed, in four
//    languages, dark and light, Stop is whole and is what a click at its centre lands on, the count is readable, the
//    session's name keeps at least 80px and the model's name is as long as without background work.
// With OMHER_SHOTS=<dir> it writes bg-header-{wording,narrow}-<tag>-{dark,light}.png (OMHER_SHOT_TAG, default
// "after"), each before the first assertion on the new parts, so the same spec on the unfixed tree writes the
// before shots.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";
const CLAUDE_SESSION = "11111111-2222-4333-8444-555555555555"; // the mock Claude Code's session id
const NAME = "Fix the login redirect";
const LANGS = ["en", "ko", "ja", "zh"] as const;
type Lang = (typeof LANGS)[number];
type Theme = "dark" | "light";

const WAITING: Record<Lang, string> = {
  en: "1 waiting in the background",
  ko: "백그라운드에서 1개 대기 중",
  ja: "バックグラウンドで 1 件待機中",
  zh: "后台有 1 项在等待",
};
/** "running" as each language's header would say it. */
const RUNNING = /running|실행|実行|运行/i;

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "bh1", op, ...params }));
  });
  ws.close();
}

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const interrupts = async (page: Page) =>
  (await page.evaluate(() => (window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? [])).filter((c) => c.input?.kind === "interrupt").length;

/** A Claude Code session in web-app, named `NAME`, whose first message is `first`. */
async function session(page: Page, first: string, theme: Theme = "dark", lang: Lang = "en") {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript(
    ([l, key, name]) => {
      localStorage.setItem("omher.lang", l);
      localStorage.removeItem("omher.sessions.recent");
      localStorage.setItem("omher.sessions.titles", JSON.stringify({ [key]: name }));
      (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/web-app";
    },
    [lang, `claude:${CLAUDE_SESSION}`, NAME] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // staged shots never show a bot named after the product
  await mock("bots.rename", { bot: "default", name: "Mira" });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-title")).toHaveText(NAME);
}

/** The background subagent of `/lateask` has asked, with no turn running: its card is up. */
async function asked(page: Page) {
  await expect(page.getByTestId("card-approval")).toBeVisible();
  await expect(page.getByTestId("subagent-row")).toHaveAttribute("data-state", "waiting");
  await expect(page.getByTestId("session-background-stop")).toBeVisible();
}

/** What the open session's agent says next, through the mock host's own event path (as an adapter's line arrives). */
async function agentSays(page: Page, events: Record<string, unknown>[]) {
  await page.evaluate(async (events) => {
    const { getHost } = (await import("/src/sessions/host.ts" as string)) as { getHost: () => unknown };
    const chats = (getHost() as { chats: Map<number, { emit: (ev: unknown) => void }> }).chats;
    const chat = [...chats.values()].pop()!;
    for (const ev of events) chat.emit(ev);
  }, events);
}

async function shot(page: Page, name: string, theme: Theme) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.mouse.move(640, 700);
  await page.waitForTimeout(350);
  await page.screenshot({ path: join(SHOTS, `bg-header-${name}-${TAG}-${theme}.png`), animations: "disabled" });
}

/** The panel's slide is over (the `settled()` of session-subagents.spec.ts): nothing of the window or the panel is
 *  moving or about to, and two reads two frames apart agree. */
async function settled(page: Page) {
  const read = () =>
    page.evaluate(async () => {
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const moving = [".window", '[data-testid="details"]'].some((sel) => document.querySelector(sel)!.getAnimations().some((a) => a.pending || a.playState === "running"));
      const boxes = ["header", "details", "session-title", "model-pill", "panel-button"].map((id) => document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().toJSON());
      return { moving, boxes };
    });
  await expect
    .poll(async () => {
      const a = await read();
      const b = await read();
      return !a.moving && !b.moving && JSON.stringify(a.boxes) === JSON.stringify(b.boxes);
    })
    .toBe(true);
}

/** The window at `width`, the right panel (on Plans, its widest tab) open or closed, and at rest. */
async function at(page: Page, width: number, open: boolean) {
  const btn = page.getByTestId("panel-button");
  await page.setViewportSize({ width, height: 800 });
  // under 1100px an open panel lies over the header: the shortcut, not a click on the button
  if ((await btn.getAttribute("aria-pressed")) !== String(open)) await page.keyboard.press("ControlOrMeta+Period");
  await expect(btn).toHaveAttribute("aria-pressed", String(open));
  if (open) await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "runs");
  await settled(page);
}

type Box = { left: number; right: number; top: number; bottom: number; width: number; height: number; client: number; scroll: number; text: string; shown: boolean };
/** The header's parts as drawn now. */
const parts = (page: Page) =>
  page.evaluate(() => {
    const box = (el: Element | null) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const e = el as HTMLElement;
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, client: e.clientWidth, scroll: e.scrollWidth, text: e.textContent ?? "", shown: r.width > 0 && r.height > 0 };
    };
    const q = (id: string) => box(document.querySelector(`[data-testid="${id}"]`));
    return {
      header: q("header")!,
      title: q("session-title")!,
      status: q("session-status")!,
      full: q("session-background"),
      short: q("session-background-short"),
      stop: q("session-background-stop"),
      right: q("head-right")!,
      model: q("model-label")!,
    };
  }) as Promise<{ header: Box; title: Box; status: Box; full: Box | null; short: Box | null; stop: Box | null; right: Box; model: Box }>;

const WIDTHS = [900, 1100, 1280, 1440];
const CELLS = [false, true].flatMap((open) => WIDTHS.map((width) => ({ width, open })));

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of SHOTS ? (["dark", "light"] as const) : (["dark"] as const)) {
  test(`work that only waits for the person is not called running; a command or a running subagent beside it is (${theme})`, async ({ page }) => {
    await session(page, "/lateask", theme);
    await asked(page);
    await shot(page, "wording", theme);
    const label = page.getByTestId("session-background");
    const head = page.getByTestId("header");
    // its only background subagent waits on the open ask: the header says what its row, card and sidebar row say
    await expect(page.getByTestId("session-status")).toHaveText("Needs you");
    await expect(label).toHaveText("1 waiting in the background");
    await expect(label).toHaveAttribute("title", "1 waiting in the background");
    await expect(head).not.toContainText(RUNNING);
    await expect(page.getByTestId("session-background-stop")).toHaveAttribute("title", "Stop what waits in the background");
    // the agent's count now holds a background command too, which has no row: nothing is guessed, today's words
    await agentSays(page, [{ event: "session.info", background: 2 }]);
    await expect(label).toHaveText("2 still running in the background");
    await expect(page.getByTestId("session-background-stop")).toHaveAttribute("title", "Stop what still runs in the background");
    // instead of the command, a second background subagent that runs: one waits, one runs, today's words
    const second = { event: "subagent", id: "sa-5", agent: "claude", name: "general-purpose", goal: "Count lines of b.txt", delegation: "claude-msg_3", index: 1, count: 2, state: "running", model: "claude-opus-5-5" };
    await agentSays(page, [second]);
    await expect(page.getByTestId("subagent-row")).toHaveCount(2);
    expect(await page.getByTestId("subagent-row").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-state")))).toEqual(["waiting", "running"]);
    await expect(label).toHaveText("2 still running in the background");
    // the second one asks too: both wait on the person
    await agentSays(page, [{ event: "approval.request", request_id: "req-9", title: "Run this command?", command: "wc -l b.txt", cwd: "/Users/you/code/web-app", choices: ["deny", "once", "session"], subagent: { id: "sa-5", name: "Count lines of b.txt" } }]);
    expect(await page.getByTestId("subagent-row").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-state")))).toEqual(["waiting", "waiting"]);
    await expect(label).toHaveText("2 waiting in the background");
    await expect(head).not.toContainText(RUNNING);
    // Stop is where it was and still sends the agent's own interrupt
    await page.getByTestId("session-background-stop").click();
    expect(await interrupts(page)).toBe(1);
    await expect(label).toHaveCount(0);
  });
}

for (const lang of LANGS) {
  test(`the waiting label in ${lang}: no word for running in the header`, async ({ page }) => {
    await session(page, "/lateask", "dark", lang);
    await asked(page);
    await expect(page.getByTestId("session-background")).toHaveText(WAITING[lang]);
    await expect(page.getByTestId("header")).not.toContainText(RUNNING);
    for (const id of ["session-background", "session-background-short", "session-background-stop"]) await expect(page.getByTestId(id)).not.toHaveAttribute("title", RUNNING);
  });
}

for (const theme of SHOTS ? (["dark", "light"] as const) : []) {
  test(`shot: the header on the narrowest chat, 1100px with Plans open (${theme})`, async ({ page }) => {
    await session(page, "/lateask", theme);
    await asked(page);
    await at(page, 1100, true);
    await shot(page, "narrow", theme);
    const p = await parts(page);
    expect(p.title.width).toBeGreaterThanOrEqual(80);
    expect(p.model.scroll).toBeLessThanOrEqual(p.model.client);
  });
}

for (const theme of ["dark", "light"] as const) {
  for (const lang of LANGS) {
    test(`with the label and Stop showing nothing that matters is cut, 900 to 1440px, panel open and closed (${lang}, ${theme})`, async ({ page }) => {
      test.setTimeout(90_000);
      await session(page, "/status", theme, lang);
      await expect(page.getByTestId("session-status")).toHaveClass(/idle/);
      // the model's name in each window before any background work
      const before: number[] = [];
      for (const { width, open } of CELLS) {
        await at(page, width, open);
        before.push((await parts(page)).model.client);
      }
      await at(page, 1280, false);
      await page.getByTestId("composer").fill("/lateask");
      await page.keyboard.press("Enter");
      await asked(page);
      for (const [i, { width, open }] of CELLS.entries()) {
        await at(page, width, open);
        const where = `${lang} ${width}px, panel ${open ? "open" : "closed"}`;
        const p = await parts(page);
        // the session's name keeps at least 80px (it is 133px long)
        expect(p.title.width, `title at ${where}`).toBeGreaterThanOrEqual(80);
        // the count is readable: the label in the form this width shows (the whole sentence, or "1 waiting") is whole
        const shown = [p.full, p.short].filter((b) => b?.shown) as Box[];
        expect(shown.length, `one label at ${where}`).toBe(1);
        expect(shown[0].text, where).toMatch(/1/);
        expect(shown[0].scroll, `label whole at ${where}`).toBeLessThanOrEqual(shown[0].client);
        // the status keeps its word from a 430px header up (under that it is its dot, the word in its tooltip)
        expect(p.status.scroll, `status whole at ${where}`).toBeLessThanOrEqual(p.status.client);
        if (p.header.width >= 430) expect(p.status.width, `status word at ${where}`).toBeGreaterThan(30);
        // Stop is whole, after the label, before the controls and inside the header
        const stop = p.stop!;
        expect(stop.scroll, `Stop whole at ${where}`).toBeLessThanOrEqual(stop.client);
        expect(stop.left, `Stop after the label at ${where}`).toBeGreaterThanOrEqual(shown[0].right - 0.5);
        expect(stop.right, `Stop before the controls at ${where}`).toBeLessThanOrEqual(p.right.left + 0.5);
        expect(stop.top, where).toBeGreaterThanOrEqual(p.header.top);
        expect(stop.bottom, where).toBeLessThanOrEqual(p.header.bottom);
        // the model's name is whole and no shorter than without background work
        expect(p.model.scroll, `model whole at ${where}`).toBeLessThanOrEqual(p.model.client);
        expect(p.model.client, `model at ${where}`).toBeGreaterThanOrEqual(before[i]);
        // a click at Stop's centre lands on Stop (under 1100px the open panel lies over the whole chat column, header
        // included, as for a bot's chat: nothing of the header is on screen to press there)
        if (open && width < 1100) continue;
        const hit = await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('[data-testid="session-background-stop"]'), [stop.left + stop.width / 2, stop.top + stop.height / 2] as const);
        expect(hit, `Stop can be pressed at ${where}`).toBe(true);
      }
    });
  }
}
