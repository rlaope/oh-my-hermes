// The merged bot-threads release (integrate node): every lane's piece wired together, and one assertion per vision
// fix the parent asked for after layer 1.
// - thread rows carry HarnessStack marks from the thread's live subagents; the thread chat shows the same subagent row
// - the terminal panel's next tab starts in the open thread's folder (home in the main chat)
// - SESSIONS is hidden: no sidebar section, ⌘N / ⌘⇧] do nothing
// - threads: connector lighter than the hairline, running spinner in the accent at 1.5px, needs-you pulse >= 0.6 in
//   the strip's amber, idle rows a hollow dot, titles >= 20px past the bot name and smaller, the bot row's time
//   follows its newest thread
// - split: link lines a tight list with an underline, Send there primary, the quoted message labelled
// - agent chat: grandchild card on the step indent, no "0.0s", a single command not repeated, muted labels readable
// - maximised Plans: the graph starts at the plan title's x
// Shots (first): OMHER_SHOTS=<dir> -> integrate-{sidebar-dark,sidebar-light,thread-with-harness,terminal}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || process.env.OMHER_SHOTS_DIR || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "ig1") res(msg);
    };
    ws.send(JSON.stringify({ id: "ig1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

async function setup(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const SEED = [
  { title: "릴리스 노트 초안 정리", ago: 4 * 3600, cwd: "/home/you/code/docs" },
  { title: "Nightly 빌드 실패 원인", ago: 3 * 3600 },
  { title: "Slack 알림 문구 다듬기", ago: 2 * 3600 },
  { title: "Docs dark mode 대비 점검", ago: 3600 },
  { title: "OG 대시보드 502 원인 찾기", ago: 60, cwd: "/home/you/code/og-gateway" },
];

/** Kami with five threads in the five states; the 502 thread runs a Codex part and a Hermes child. */
async function seed(page: Page) {
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: SEED });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const [notes, nightly, slack, docs, og] = threads as string[];
  await expect(page.getByTestId(`thread-row-${og}`)).toBeVisible();
  const sub = (id: string, index: number, extra: Record<string, unknown>) => ({
    event: "subagent", bot: "kami", session: og, id, index, count: 2, delegation: "deleg_og", state: "running", ...extra,
  });
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami", session: og },
      { event: "tool.start", bot: "kami", session: og, tool_id: "d1", name: "delegate_task", detail: "gateway 로그 확인 (+1 more)" },
      sub("sa-og-1", 0, { goal: "gateway 로그에서 502 패턴 찾기", agent: "codex", model: "gpt-6.1-sol", tool: "terminal", step: "rg 502 gateway.log" }),
      sub("sa-og-2", 1, { goal: "keep-alive 설정 비교", model: "claude-opus-5-5" }),
      { event: "turn.start", bot: "kami", session: docs },
      { event: "approval.request", bot: "kami", session: docs, request_id: "ap-docs", title: "Run shell command", command: "pnpm build:docs", choices: ["once", "deny"] },
      { event: "turn.start", bot: "kami", session: slack },
      { event: "message", bot: "kami", session: slack, id: "m-slack", text: "알림 문구를 세 가지로 다듬었어요." },
      { event: "turn.end", bot: "kami", session: slack, outcome: "done" },
      { event: "turn.start", bot: "kami", session: nightly },
      { event: "turn.end", bot: "kami", session: nightly, outcome: "error", error: "gateway timeout" },
    ],
  });
  await expect(page.getByTestId(`thread-row-${og}`)).toHaveAttribute("data-state", "running");
  await expect(page.getByTestId(`thread-row-${docs}`)).toHaveAttribute("data-state", "needs_you");
  return { notes, nightly, slack, docs, og };
}

test.beforeEach(async () => {
  await mock("mock.reset");
});
test.afterEach(async () => {
  await mock("mock.manual", { bot: "kami", on: false });
});

test.describe("shots", () => {
  test.use({ deviceScaleFactor: 2 });
  test("integrate shots: sidebar dark/light, a thread with harness marks, the terminal", async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS unset");
    mkdirSync(SHOTS, { recursive: true });
    await setup(page, "dark");
    const ids = await seed(page);
    await page.mouse.move(900, 600);
    await page.screenshot({ path: `${SHOTS}/integrate-sidebar-dark.png`, animations: "disabled" });
    await page.getByTestId(`thread-row-${ids.og}`).getByTestId("thread-open").click();
    await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", ids.og);
    await page.mouse.move(900, 600);
    await page.screenshot({ path: `${SHOTS}/integrate-thread-with-harness.png`, animations: "disabled" });
    await page.keyboard.press("Control+Backquote");
    await expect(page.getByTestId("termpanel")).toBeVisible();
    await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("/home/you/code/og-gateway");
    await page.keyboard.type("git log --oneline\r");
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/integrate-terminal.png`, animations: "disabled" });
    await page.evaluate(() => localStorage.setItem("omher.theme", "light"));
    await page.addInitScript(() => localStorage.setItem("omher.theme", "light"));
    await page.reload();
    await expect(page.getByTestId(`thread-row-${ids.nightly}`)).toBeVisible();
    await mock("mock.emit", {
      events: [
        { event: "turn.start", bot: "kami", session: ids.og },
        { event: "subagent", bot: "kami", session: ids.og, id: "sa-og-1", index: 0, count: 1, delegation: "deleg_og2", state: "running", goal: "gateway 로그", agent: "codex" },
        { event: "turn.start", bot: "kami", session: ids.docs },
        { event: "approval.request", bot: "kami", session: ids.docs, request_id: "ap-docs2", title: "Run shell command", command: "pnpm build:docs", choices: ["once", "deny"] },
        { event: "turn.start", bot: "kami", session: ids.slack },
        { event: "turn.end", bot: "kami", session: ids.slack, outcome: "done" },
        { event: "turn.start", bot: "kami", session: ids.nightly },
        { event: "turn.end", bot: "kami", session: ids.nightly, outcome: "interrupted" },
      ],
    });
    await expect(page.getByTestId(`thread-row-${ids.nightly}`)).toHaveAttribute("data-state", "failed");
    await page.mouse.move(900, 600);
    await page.screenshot({ path: `${SHOTS}/integrate-sidebar-light.png`, animations: "disabled" });
  });
});

test("a thread row carries the marks of who works in it; the thread chat shows the same subagent rows", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  const stack = page.getByTestId(`thread-row-${ids.og}`).getByTestId("harness-stack");
  await expect(stack).toBeVisible();
  // Codex (its own mark) and a Hermes child out: the row shows ONE mark (the first), no "+N"; the tooltip names both
  await expect(stack.locator("[data-harness]")).toHaveCount(1);
  await expect(stack.locator("[data-harness]")).toHaveAttribute("data-harness", "codex");
  await expect(stack.getByTestId("harness-more")).toHaveCount(0);
  await expect(stack).toHaveAttribute("title", "Codex, Hermes");
  // the title keeps >= 14 visible characters at the default sidebar width
  const visible = await page.getByTestId(`thread-row-${ids.og}`).locator(".th-title").evaluate((el) => {
    const c = document.createElement("canvas").getContext("2d")!;
    c.font = getComputedStyle(el).font;
    const s = el.textContent ?? "";
    let n = 0;
    while (n < s.length && c.measureText(s.slice(0, n + 1) + "…").width <= el.clientWidth) n++;
    return n;
  });
  expect(visible).toBeGreaterThanOrEqual(14);
  // the mark sits in the time's place while it shows; a row with nobody out keeps its time
  await expect(page.getByTestId(`thread-row-${ids.og}`).locator(".th-time")).toBeHidden();
  await expect(page.getByTestId(`thread-row-${ids.slack}`).locator(".th-time")).toBeVisible();
  // a thread with nobody out has no stack (the slot stays empty)
  await expect(page.getByTestId(`thread-row-${ids.slack}`).getByTestId("harness-stack")).toHaveCount(0);
  await page.getByTestId(`thread-row-${ids.og}`).getByTestId("thread-open").click();
  const chat = page.getByTestId("thread-chat");
  // the header reads "Kami / <title>" as one breadcrumb: no fixed-width gap after the bot's name
  const name = await page.getByTestId("thread-back").locator(".head-title").boundingBox();
  const sep = await page.getByTestId("thread-header").locator(".th-head-sep").boundingBox();
  expect(sep!.x - (name!.x + name!.width)).toBeLessThanOrEqual(16);
  await expect(chat.locator('.sa-mark[data-harness="codex"]')).toHaveCount(1);
  await expect(chat.locator('.sa-mark[data-harness="hermes"]')).toHaveCount(1);
  // the Codex child ends: the row's one mark is the Hermes child still out
  await mock("mock.emit", { events: [{ event: "subagent", bot: "kami", session: ids.og, id: "sa-og-1", index: 0, count: 2, delegation: "deleg_og", state: "done", summary: "502 at 14:31" }] });
  await expect(stack.locator("[data-harness]")).toHaveAttribute("data-harness", "hermes");
});

test("the terminal panel's next tab starts in the open thread's folder, home in the main chat", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  const cwd = () => page.evaluate(async () => ((await import("/src/terminal/state.ts" as string)) as { getTermPanel?: () => { cwd: string | null } }).getTermPanel?.().cwd ?? null);
  await page.getByTestId(`thread-row-${ids.og}`).getByTestId("thread-open").click();
  await expect.poll(cwd).toBe("/home/you/code/og-gateway");
  await page.getByTestId(`thread-row-${ids.notes}`).getByTestId("thread-open").click();
  await expect.poll(cwd).toBe("/home/you/code/docs");
  await page.getByTestId("thread-back").click();
  await expect.poll(cwd).toBe(null);
});

test("a restored thread listed without a folder: opening it gives the row its folder, and the next shell starts there", async ({ page }) => {
  await setup(page);
  await mock("mock.manual", { bot: "kami" });
  const { threads } = await mock("mock.threads", { bot: "kami", threads: [{ title: "restored", ago: 60, cwd: "/work/restored", listedCwd: "" }] });
  await page.reload();
  const row = page.getByTestId(`thread-row-${threads[0]}`);
  await expect(row).toBeVisible();
  await row.getByTestId("thread-open").click();
  await expect(page.getByTestId("thread-chat")).toHaveAttribute("data-thread", threads[0]);
  // the row takes the folder once thread.open answers; the terminal's next tab follows it
  const termCwd = () => page.evaluate(async () => ((await import("/src/terminal/state.ts" as string)) as { getTermPanel(): { cwd: string | null } }).getTermPanel().cwd);
  await expect.poll(termCwd).toBe("/work/restored");
  await page.keyboard.press("Control+Backquote");
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("login shell in /work/restored");
  expect((await page.evaluate(() => (window as unknown as { __omherShellCalls: { op: string; at?: string }[] }).__omherShellCalls)).find((c) => c.op === "start")?.at).toBe("/work/restored");
});

test("SESSIONS is hidden: no sidebar section, ⌘N and ⌘⇧] do nothing; Accounts usage stays", async ({ page }) => {
  await setup(page);
  await expect(page.getByTestId("side-bots")).toBeVisible();
  await expect(page.getByTestId("side-sessions")).toHaveCount(0);
  const mod = await page.evaluate(() => (/Mac/.test(navigator.platform) ? "Meta" : "Control"));
  await page.keyboard.press(`${mod}+n`);
  await page.keyboard.press(`${mod}+Shift+BracketRight`);
  await page.waitForTimeout(200);
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
  await expect(page.getByTestId("session-view")).toHaveCount(0);
});

test("thread rows: connector, spinner, pulse, idle dot, indent and size; bot row follows its newest thread", async ({ page }) => {
  await setup(page);
  const ids = await seed(page);
  const look = await page.evaluate((ids) => {
    const css = (el: Element | null, p: string) => (el ? getComputedStyle(el).getPropertyValue(p) : "");
    const tree = document.querySelector('[data-testid="threads-kami"]')!;
    const branch = tree.querySelector(".th-branch")!;
    const side = document.querySelector(".side")!;
    // the connector's colour vs the hairline (--line-strong) the lane used: lighter on dark
    const probe = document.createElement("span");
    probe.style.color = "var(--line-strong)";
    side.appendChild(probe);
    const hair = getComputedStyle(probe).color;
    probe.style.color = "var(--needs)";
    const needs = getComputedStyle(probe).color;
    probe.remove();
    const running = document.querySelector(`[data-testid="thread-row-${ids.og}"] .th-g-running svg path`)!;
    const accent = css(tree, "--accent").trim();
    const dot = document.querySelector(`[data-testid="thread-row-${ids.docs}"] .th-dot`)!;
    const kf = dot.getAnimations()[0] as CSSAnimation | undefined;
    const frames = (kf?.effect as KeyframeEffect | undefined)?.getKeyframes() ?? [];
    const idle = document.querySelector(`[data-testid="thread-row-${ids.notes}"] [data-testid="thread-glyph"]`)!;
    const botName = document.querySelector('[data-testid="bot-kami"] .bot-n')!;
    const title = document.querySelector(`[data-testid="thread-row-${ids.og}"] .th-title`)!;
    return {
      line: css(branch, "border-left-color"),
      hair,
      stroke: css(running, "stroke-width"),
      runningColor: css(running.closest(".th-g")!, "color"),
      accent,
      minOpacity: Math.min(...frames.map((f) => Number(f.opacity ?? 1))),
      dotBg: css(dot, "background-color"),
      needs,
      idleState: idle.getAttribute("data-state"),
      idleRing: !!idle.querySelector(".th-ring"),
      ringBorder: css(idle.querySelector(".th-ring"), "border-top-width"),
      indent: title.getBoundingClientRect().left - botName.getBoundingClientRect().left,
      titleSize: parseFloat(css(title, "font-size")),
      nameSize: parseFloat(css(botName, "font-size")),
    };
  }, ids);
  // what a colour looks like painted over the sidebar (alpha included), as one brightness number
  const lum = (c: string) =>
    page.evaluate((c) => {
      const cv = document.createElement("canvas");
      cv.width = cv.height = 1;
      const g = cv.getContext("2d")!;
      g.fillStyle = getComputedStyle(document.querySelector(".side")!).backgroundColor;
      g.fillRect(0, 0, 1, 1);
      g.fillStyle = c;
      g.fillRect(0, 0, 1, 1);
      const [r, gg, b] = g.getImageData(0, 0, 1, 1).data;
      return (r + gg + b) / 3;
    }, c);
  // (1) the connector is one step lighter than the 1px hairline on dark, and still under the text
  expect(await lum(look.line)).toBeGreaterThan(await lum(look.hair));
  // (2) running: accent colour, 1.5px stroke
  expect(look.stroke).toBe("1.5px");
  const toRgb = await page.evaluate((c) => {
    const s = document.createElement("span");
    s.style.color = c;
    document.body.appendChild(s);
    const v = getComputedStyle(s).color;
    s.remove();
    return v;
  }, look.accent);
  expect(look.runningColor).toBe(toRgb);
  // (3) needs you: pulse never under 0.6 and the strip's amber
  expect(look.minOpacity).toBeGreaterThanOrEqual(0.6);
  expect(look.dotBg).toBe(look.needs);
  // (4) idle: a faint hollow dot
  expect(look.idleState).toBe("idle");
  expect(look.idleRing).toBe(true);
  expect(look.ringBorder).toBe("1px");
  // (5) thread titles >= 20px past the bot name, and smaller than it
  expect(look.indent).toBeGreaterThanOrEqual(20);
  expect(look.titleSize).toBeLessThan(look.nameSize);
  // (6) the bot row's time and line follow the newest activity, here in a thread
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", session: ids.slack, id: "m-slack-2", text: "새 문구 초안을 올렸어요." }] });
  await expect(page.getByTestId("bot-kami").getByTestId("bot-sub")).toContainText("새 문구 초안을 올렸어요.");
});

test("split: link lines are a tight underlined list; Send there is primary; the quoted message is labelled", async ({ page }) => {
  await setup(page);
  await expect.poll(async () => ((await mock("mock.calls")).calls as { op: string }[]).some((c) => c.op === "thread.list")).toBe(true);
  const fence = (kind: string, obj: unknown) => "```" + kind + "\n" + JSON.stringify(obj) + "\n```";
  await mock("mock.answer", {
    bot: "kami",
    text: ["둘로 나눌게요.", "", fence("omher-thread", { title: "A 스레드", task: "a" }), "", fence("omher-thread", { title: "B 스레드", task: "b" })].join("\n"),
  });
  const box = page.getByTestId("composer");
  await box.click();
  await box.fill("둘 다 해줘");
  await page.keyboard.press("Enter");
  const links = page.getByTestId("thread-link");
  await expect(links).toHaveCount(2);
  const [a, b] = [await links.nth(0).boundingBox(), await links.nth(1).boundingBox()];
  // tight: the second line starts where the first ends (no paragraph gap)
  expect(b!.y - (a!.y + a!.height)).toBeLessThanOrEqual(2);
  const deco = await links.nth(0).locator(".th-link-t").evaluate((el) => getComputedStyle(el).textDecorationLine);
  expect(deco).toContain("underline");
  const ids = await page.getByTestId("threads-kami").getByRole("treeitem").evaluateAll((els) => els.map((e) => e.getAttribute("data-thread")!));
  await expect.poll(async () => page.getByTestId("threads-kami").getByRole("treeitem").evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).toEqual(["done", "done"]);
  await mock("mock.answer", { bot: "kami", text: "그 스레드에서 이어가요.\n" + fence("omher-thread-route", { thread: ids[0] }) });
  await box.click();
  await box.fill("이어서 해줘");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("thread-route");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("thread-route-send")).toHaveClass(/primary/);
  await expect(card.getByTestId("thread-route-keep")).not.toHaveClass(/primary/);
  await expect(card.getByTestId("thread-route-quote")).toContainText("Your message");
  await expect(card.getByTestId("thread-route-quote")).toContainText("“이어서 해줘”");
});

test("agent chat: grandchild on the step indent, no 0.0s, a single command not repeated, readable muted labels", async ({ page }) => {
  await mock("mock.demo");
  await setup(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  const graph = page.getByTestId("run-graph-box");
  await graph.locator('[data-testid="run-node"][data-node="contrast"]').click();
  const chat = page.getByTestId("run-session").getByTestId("agent-chat");
  await expect(chat.getByTestId("agent-chat-timeline")).toBeVisible();
  await chat.getByTestId("agent-chat-full").click();
  // (2) the last step has no later timestamp: no duration, never "0.0s"
  const times = await chat.getByTestId("activity-step-time").allTextContents();
  expect(times).not.toContain("0.0s");
  expect(times[times.length - 1]).toBe("");
  // (3) the single-command shell step opens to its result only
  const ran = chat.getByTestId("activity-step").nth(1);
  await expect(ran).toContainText("node scripts/contrast.mjs docs/theme.css");
  await ran.click();
  await expect(chat.getByTestId("activity-step-result").first()).toContainText("3.9:1");
  await expect(chat.getByTestId("activity-step-input")).toHaveCount(0);
  // (1) the grandchild card sits on the step indent: the x and right edge of the opened result box
  const io = await chat.getByTestId("activity-step-result").first().boundingBox();
  const card = await chat.getByTestId("agent-chat-child").boundingBox();
  expect(Math.abs(card!.x - io!.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(card!.x + card!.width - (io!.x + io!.width))).toBeLessThanOrEqual(2);
  // (4) muted labels (step times, the "Kami" label, the breadcrumb) use the secondary-text token (>= 4.5:1)
  const colors = await page.evaluate(() => {
    const c = (sel: string) => getComputedStyle(document.querySelector(sel)!).color;
    const s = document.createElement("span");
    s.style.color = "var(--muted)";
    document.querySelector(".ac")!.appendChild(s);
    const muted = getComputedStyle(s).color;
    s.remove();
    return { muted, time: c('.ac [data-testid="activity-step-time"]'), from: c('.ac [data-testid="bubble-from"]'), crumb: c(".ac .ac-crumb") };
  });
  expect(colors.time).toBe(colors.muted);
  expect(colors.from).toBe(colors.muted);
  expect(colors.crumb).toBe(colors.muted);
});

test("maximised Plans: the graph starts at the plan title's x", async ({ page }) => {
  await mock("mock.demo");
  await setup(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  await page.getByTestId("graph-expand").click();
  const graph = page.getByTestId("run-graph-box");
  await expect(graph).toHaveClass(/max/);
  await page.waitForTimeout(400);
  const title = await graph.getByTestId("run-plan-title").boundingBox();
  const xs = await graph.getByTestId("run-node").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().left));
  expect(Math.abs(Math.min(...xs) - title!.x)).toBeLessThanOrEqual(4);
});
