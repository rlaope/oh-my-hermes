// The preview's live scenario: the window keeps moving with no input. Kami is ~9 minutes into the docs dark mode
// plan with three Hermes subagents running; parts finish one by one, the next starts, the open part's detail grows,
// Slack / Discord replies and other bots' messages land, Kami posts the PR with a before/after, and the loop
// starts over (~55-65 s, a little different each time). Real clock: requestAnimationFrame plus Date.now, with a 250 ms timer when frames are held back.
// The visitor always wins: any click, key or wheel pauses the story for 8 s, and what they set off (a reply, the
// plan built from scratch, Juno's deploy) plays on its own timers. Hidden tab or window off-screen: paused.
// Everything is staged data inside the page; nothing runs anywhere.
import { getStore } from "../src/state/store";
import { getSessions } from "../src/sessions/sessions";
import type { AgentId } from "../src/sessions/agents";
import { away, history, hooks, kamiSeed, nowS, runs } from "./host";

type Ev = { event: string; [k: string]: unknown };
const store = () => getStore();
const ev = (bot: string, e: Ev, at = Date.now()) => store().dispatch({ type: "event", ev: { bot, ...e } as never, now: at });
const RM = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const rand = (a: number, b: number) => a + Math.random() * (b - a);

// ---- the plan ------------------------------------------------------------------------------------------------

const RUN_BASE = "dag:20261110_091904_d4a1c7e2/docs-dark-mode";
let runSeq = 0;
let RUN = RUN_BASE;
const runName = () => RUN.split("/").pop()!;
const REQUEST = "Go ahead: add dark mode to the docs site and open a PR.";
// [id, label, deps, model, provider, effort, category, executor]. The cast: three Hermes subagents on GLM, Kimi and
// DeepSeek, and three lanes handed to agent CLIs (Claude Code on Opus, Codex on GPT-6.1 Sol, omp on Sonnet), side by side.
const NODES: [string, string, string[], string, string, string, string, string?][] = [
  ["color-tokens", "Color tokens", [], "GLM-5.3", "z-ai", "medium", "quick"],
  ["theme-toggle", "Theme toggle", [], "Kimi K3", "moonshot", "high", "visual-engineering"],
  ["contrast", "Contrast check", ["color-tokens"], "DeepSeek V4.1", "deepseek", "high", "review"],
  ["page-styles", "Page styles", ["color-tokens", "theme-toggle"], "Opus 5.5", "claude-proxy", "high", "visual-engineering", "claude"],
  ["code-colors", "Code block colors", ["color-tokens", "theme-toggle"], "gpt-6.1-sol", "openai", "medium", "visual-engineering", "codex"],
  ["verify-pr", "Verify and open PR", ["page-styles", "code-colors", "contrast"], "Sonnet 5.5", "claude-proxy", "high", "review", "omp"],
];
const SUMMARY: Record<string, string> = {
  "color-tokens": "12 light/dark token pairs in theme.css.",
  "theme-toggle": "A toggle in the header; it remembers the choice and follows the system theme.",
  "page-styles": "Body, sidebar and search moved to the new tokens.",
  "code-colors": "A dark code theme with the same contrast as the light one.",
  contrast: "Every token pair passes WCAG AA.",
  "verify-pr": "Built the docs, checked 14 pages, opened PR #128.",
};
// what the open part's subagent reports, line by line, while it works
const STREAM: Record<string, string[]> = {
  "page-styles": [
    "- Body and sidebar read `--bg`, `--ink` and `--line` now",
    "- Search box and results moved to the new tokens",
    "- Links use `--accent` (Mina's purple) in both themes",
    "- Tables and callouts: borders from `--line`, fills from `--soft`",
    "- `pnpm docs:build` passes; 14 pages checked",
  ],
  "verify-pr": [
    "- `pnpm docs:build` passes",
    "- Checked 14 pages in light and dark",
    "- Every token pair passes WCAG AA",
    "- Opened **PR #128**: docs dark mode",
  ],
};
type NodeSt = { state: string; started?: number; ended?: number };
let st: Record<string, NodeSt> = {};
let runStarted = 0;

function pushRun(state = "running") {
  const t = nowS();
  const nodes = NODES.map(([id, label, deps, model, provider, effort, route, executor]) => {
    const s = st[id] ?? { state: "waiting" };
    return {
      id, label, deps, layer: 0, state: s.state, model, provider, effort, route,
      role: id === "verify-pr" ? "verify" : "build",
      ...(executor ? { executor } : {}),
      ...(s.started ? { started: s.started, attempts: [{ n: 1, outcome: s.state === "done" ? "accepted" : "open", started: s.started, ...(s.ended ? { ended: s.ended } : {}) }] } : { attempts: [] }),
      ...(s.ended ? { ended: s.ended } : {}),
      ...(s.state === "done" ? { summary: SUMMARY[id] } : {}),
    };
  });
  runs.live = { id: RUN, kind: "dag", owner: { type: "bot", id: "kami" }, title: "Docs dark mode", goal: "Add dark mode to the docs site and open a PR.", state, started: runStarted, updated: t, nodes, ...(state === "done" ? { ended: t } : {}) };
  window.dispatchEvent(new Event("omher-preview:runs"));
}
function setNode(id: string, state: string, at = nowS()) {
  const s = (st[id] ??= { state: "waiting" });
  if (state === "running") s.started = at;
  if (state === "done") {
    s.started ??= at - 60;
    s.ended = at;
  }
  s.state = state;
}
function stream(id: string, n: number) {
  const lines = STREAM[id] ?? [];
  (runs.handoffs[RUN] ??= {})[id] = lines.slice(0, n).join("\n");
}
const dag = (ids: string[]) => ids.map((node) => ({ run: runName(), node }));

// ---- the story clock -----------------------------------------------------------------------------------------

type Step = [number, () => void];
let steps: Step[] = []; // the autoplay loop, on the story clock
let live: Step[] = []; // what the visitor set off, on real time
let storyT = 0;
let liveT = 0;
let lastInput = -1e9;
let lastInputType = "";
let visible = true;
let touched = false; // the visitor opened something this loop: the story stops moving the view
let liveEnd = 0; // when the last thing the visitor set off finished (its result stays on screen a while)
const YIELD_MS = 8000;
const yielded = () => Date.now() - lastInput < YIELD_MS;

function onInput(e: Event) {
  if (!e.isTrusted) return;
  lastInput = Date.now();
  lastInputType = e.type;
  if (e.type !== "wheel") {
    if (!touched) parent.postMessage({ type: "omher-preview:touched" }, location.origin);
    touched = true;
  }
}
for (const t of ["pointerdown", "keydown", "wheel"]) addEventListener(t, onInput, { capture: true, passive: true });
addEventListener("message", (e) => {
  if (e.origin !== location.origin) return;
  const d = e.data as { type?: string; visible?: boolean };
  if (d?.type === "omher-preview:visible") visible = !!d.visible;
});

/** Is the visitor on Kami's chat, so the story may open things in its panel? */
const onKami = () => {
  const s = store().getState();
  return !touched && !yielded() && s.selectedBot === "kami" && s.ui.view === "chat";
};
function openNode(id: string) {
  if (!onKami()) return;
  const s = store();
  if (!s.getState().ui.panelOpen || s.getState().ui.panelTab !== "runs" || s.getState().ui.runId !== runName()) s.actions.openRun(runName());
  let tries = 0;
  const go = () => {
    const el = document.querySelector<HTMLButtonElement>(`[data-testid="run-node"][data-node="${id}"]`);
    if (el) {
      if (el.getAttribute("aria-pressed") !== "true") el.click();
    } else if (tries++ < 20) setTimeout(go, 100);
  };
  setTimeout(go, 60);
}

// ---- one loop --------------------------------------------------------------------------------------------------

let loop = 0;
let junoAsk = "";
let junoBusy = false;

function resetKami(turnStart: number) {
  const seedRows = kamiSeed();
  const ask = { id: `ask-${loop}`, role: "user" as const, text: REQUEST, ts: turnStart / 1000 - 6 };
  history.kami = [...seedRows, ask];
  away.kami = [];
  const s = store();
  s.dispatch({ type: "chat.forget", bot: "kami" });
  s.dispatch({ type: "chat.opened", bot: "kami", res: { session_id: "main-kami", messages: history.kami, running: false, model: "Opus 5.5", provider: "claude-proxy", reasoning: "high" }, now: Date.now() });
  s.dispatch({ type: "elsewhere", bot: "kami", sessions: [] });
}

function startLoop() {
  loop += 1;
  // a new loop opens on Kami again (the visitor has been idle for a while when it comes)
  const app = store();
  if (app.getState().ui.view !== "chat") app.actions.openSession(null);
  if (app.getState().ui.view === "settings") app.actions.closeSettings();
  if (app.getState().ui.runsFull) app.actions.setRunsFull(false);
  if (app.getState().selectedBot !== "kami") void app.actions.selectBot("kami");
  touched = false;
  storyT = 0;
  const j = rand(0.94, 1.08); // each loop a little different
  const t0 = Date.now();
  const elapsed = rand(540, 600) * 1000;
  const T = t0 - elapsed; // when the turn started: the status timer reads 9m-10m on arrival
  runStarted = T / 1000 + 40;
  RUN = RUN_BASE;
  st = {};
  runs.handoffs[RUN] = {};
  resetKami(T);
  ev("kami", { event: "bot.status", status: "online", running: true }, T);
  ev("kami", { event: "turn.start" }, T);
  ev("kami", { event: "tool.start", tool_id: "k1", name: "skill_view", detail: "dag-ulw" }, T + 1500);
  ev("kami", { event: "skill", name: "dag-ulw" }, T + 1500);
  ev("kami", { event: "tool.end", tool_id: "k1", name: "skill_view", ok: true, ms: 900 }, T + 2400);
  ev("kami", { event: "message", id: `k-plan-${loop}`, text: "Planned it in **6 parts**: 3 Hermes subagents on GLM, Kimi and DeepSeek, plus Claude Code, Codex and omp lanes. omp verifies and opens the PR." }, T + 30_000);
  ev("kami", { event: "tool.start", tool_id: "k2", name: "delegate_task", detail: "Color tokens, Theme toggle", dag: dag(["color-tokens", "theme-toggle"]) }, T + 40_000);
  setNode("color-tokens", "done", T / 1000 + 400);
  st["color-tokens"].started = T / 1000 + 40;
  setNode("theme-toggle", "done", T / 1000 + 455);
  st["theme-toggle"].started = T / 1000 + 40;
  ev("kami", { event: "tool.end", tool_id: "k2", name: "delegate_task", ok: true, ms: 415_000 }, T + 455_000);
  const s3 = T / 1000 + 462;
  ev("kami", { event: "tool.start", tool_id: "k3", name: "delegate_task", detail: "Page styles, Code block colors, Contrast check", dag: dag(["page-styles", "code-colors", "contrast"]) }, s3 * 1000);
  for (const id of ["page-styles", "code-colors", "contrast"]) setNode(id, "running", s3 - rand(0, 20));
  ev("kami", { event: "status", text: "Running 3 parts" });
  stream("page-styles", 1);
  pushRun();

  // the others: Friren reading, Juno waiting on an approval, two coding sessions busy
  ev("friren", { event: "bot.status", status: "online", running: true }, t0 - 50_000);
  ev("friren", { event: "turn.start" }, t0 - 50_000);
  ev("friren", { event: "tool.start", tool_id: `f${loop}`, name: "web_extract", detail: "Tauri 2.4 release notes" }, t0 - 20_000);
  if (!junoAsk && !junoBusy) raiseJuno(t0 - 60_000);

  const k = (s: number) => s * 1.1 * j;
  steps = [
    [k(0.2), () => openNode("page-styles")],
    [k(1.8), () => { stream("page-styles", 2); pushRun(); }],
    [k(2.6), () => ev("friren", { event: "status", text: "Reading the updater section" })],
    [k(3.6), () => {
      setNode("contrast", "done"); pushRun();
      ev("kami", { event: "status", text: "Running 2 parts" });
    }],
    [k(6), () => { stream("page-styles", 3); pushRun(); }],
    [k(8.5), () => landAway("discord")],
    [k(10.5), () => { stream("page-styles", 4); pushRun(); }],
    [k(12.5), () => ev("pip", { event: "message", id: `pip-${loop}`, text: "Standup notes are filed: 4 updates, 1 blocker (the iOS build)." })],
    [k(14), () => {
      setNode("code-colors", "done"); pushRun();
      ev("kami", { event: "status", text: "Running 1 part" });
    }],
    [k(16.5), () => { stream("page-styles", 5); pushRun(); }],
    [k(19.5), () => {
      setNode("page-styles", "done"); setNode("verify-pr", "running");
      runs.handoffs[RUN]["verify-pr"] = STREAM["verify-pr"][0];
      pushRun();
      ev("kami", { event: "tool.end", tool_id: "k3", name: "delegate_task", ok: true, ms: 560_000 });
      ev("kami", { event: "tool.start", tool_id: "k4", name: "delegate_task", detail: "Verify and open PR", dag: dag(["verify-pr"]) });
      ev("kami", { event: "status", text: "Running 1 part" });
      openNode("verify-pr");
    }],
    [k(22.5), () => {
      ev("friren", { event: "tool.end", tool_id: `f${loop}`, name: "web_extract", ok: true, ms: 50_000 });
      ev("friren", { event: "message", id: `fr-${loop}`, text: "Wrote up the Tauri 2.4 notes: delta updates, smaller bundles, nothing breaking for us." });
      ev("friren", { event: "turn.end", outcome: "done" });
      ev("friren", { event: "bot.status", status: "online", running: false });
    }],
    [k(23.5), () => { stream("verify-pr", 2); pushRun(); }],
    [k(27), () => { stream("verify-pr", 3); pushRun(); }],
    [k(31), () => {
      stream("verify-pr", 4);
      setNode("verify-pr", "done");
      pushRun("done");
      ev("kami", { event: "tool.end", tool_id: "k4", name: "delegate_task", ok: true, ms: 60_000 });
    }],
    [k(32.5), () => {
      ev("kami", { event: "message", id: `k-pr-${loop}`, text: "PR #128 is open: the docs have a dark theme now. Before and after:\n\nMEDIA:/w/media/docs-light.webp\nMEDIA:/w/media/docs-dark.webp" });
      ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: false });
    }],
    [k(39), () => landAway("slack")],
    [k(52), () => fadeThen(startLoop)],
  ];
}

function landAway(source: "slack" | "discord") {
  const t = nowS();
  const row =
    source === "slack"
      ? { id: "slack-design-docs", source: "slack", title: "docs theme", place: "#design", url: "slack://channel?team=T1&id=C2", target: "slack:C02DESIGN:1794200000.000100", reply: "Told Mina in #design that dark mode is in review as PR #128, with her purple on links.", startedAt: t - 300, lastAt: t, count: 8 }
      : { id: "discord-releases", source: "discord", title: "release notes", place: "#releases", url: "https://discord.com/channels/1/9", target: "discord:900000000000000009", reply: "Sam asked if dark mode follows the system theme. It does, and it lands today.", startedAt: t - 200, lastAt: t, count: 5 };
  away.kami = [...away.kami.filter((a) => a.id !== row.id), row];
  void store().actions.loadElsewhere("kami");
}

function raiseJuno(at = Date.now()) {
  junoAsk = `juno-ap-${loop}`;
  ev("juno-bot", { event: "bot.status", status: "online", running: true }, at);
  ev("juno-bot", { event: "turn.start" }, at);
  ev("juno-bot", { event: "approval.request", request_id: junoAsk, title: "Run shell command", command: "pnpm deploy api-server --prod", choices: ["deny", "once", "session"] }, at + 10_000);
}

let fading = false;
function fadeThen(fn: () => void) {
  const root = document.getElementById("root");
  if (!root || RM) return fn();
  if (fading) return;
  fading = true;
  root.style.transition = "opacity .32s ease";
  root.style.opacity = "0";
  setTimeout(() => {
    fn();
    fading = false;
    requestAnimationFrame(() => (root.style.opacity = "1"));
  }, 340);
}

// ---- what the visitor sets off -----------------------------------------------------------------------------------

const KO = /[\u3131-\u318e\uac00-\ud7a3]/;
function after(steps2: Step[]) {
  const base = liveT;
  live.push(...steps2.map(([t, f]) => [base + t, f] as Step));
}

hooks.send = (bot, text) => {
  const chat = store().getState().chats[bot];
  if (bot === "kami" && /dag-ulw|\bplan\b|dark mode|계획|다크/i.test(text)) return planFromScratch();
  const answer = KO.test(text)
    ? "여긴 미리보기 창이라 실제로 실행된 건 없어요. omher를 내려받으면 당신의 Hermes 프로필에서 제가 진짜로 맡아서 할게요."
    : "This window is a preview with staged data, so nothing ran. Download omher and I'll take this on for real in your own Hermes profile.";
  const id = `v-${Math.random().toString(36).slice(2, 8)}`;
  if (chat?.turn) {
    // the bot is mid-turn: it answers in the thread without ending its work
    after([[1.4, () => ev(bot, { event: "message", id, text: answer })]]);
    return;
  }
  after([
    [0, () => { ev(bot, { event: "bot.status", status: "online", running: true }); ev(bot, { event: "turn.start" }); ev(bot, { event: "thinking" }); }],
    [1.3, () => ev(bot, { event: "delta", text: answer.slice(0, 40) })],
    [1.5, () => ev(bot, { event: "delta", text: answer.slice(40) })],
    [1.7, () => ev(bot, { event: "message", id, text: answer })],
    [1.8, () => { ev(bot, { event: "turn.end", outcome: "done" }); ev(bot, { event: "bot.status", status: "online", running: false }); }],
  ]);
};

/** The plan built from scratch: the parts appear one after another, run and land, in about 14 s. */
function planFromScratch() {
  steps = []; // the autoplay loop gives way; a new loop starts once the visitor is idle again
  runSeq += 1;
  RUN = `${RUN_BASE}-${runSeq}`;
  st = {};
  runs.handoffs[RUN] = {};
  runStarted = nowS();
  const k = store().getState().chats.kami;
  touched = true;
  after([
    [0, () => {
      if (k?.turn) ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: true });
      ev("kami", { event: "turn.start" });
      ev("kami", { event: "thinking" });
    }],
    [0.7, () => { ev("kami", { event: "tool.start", tool_id: "p1", name: "skill_view", detail: "dag-ulw" }); ev("kami", { event: "skill", name: "dag-ulw" }); }],
    [1.6, () => {
      ev("kami", { event: "tool.end", tool_id: "p1", name: "skill_view", ok: true, ms: 900 });
      pushRun();
      store().actions.openRun(runName());
      ev("kami", { event: "message", id: `p-plan-${runSeq}`, text: "Planned it in **6 parts**: 3 Hermes subagents on GLM, Kimi and DeepSeek, plus Claude Code, Codex and omp lanes. Starting the first two now." });
    }],
    [2.8, () => {
      setNode("color-tokens", "running"); setNode("theme-toggle", "running"); pushRun();
      ev("kami", { event: "tool.start", tool_id: "p2", name: "delegate_task", detail: "Color tokens, Theme toggle", dag: dag(["color-tokens", "theme-toggle"]) });
      ev("kami", { event: "status", text: "Running 2 parts" });
    }],
    [4.6, () => { setNode("color-tokens", "done"); pushRun(); ev("kami", { event: "status", text: "Running 1 part" }); }],
    [5.6, () => {
      setNode("theme-toggle", "done"); for (const id of ["page-styles", "code-colors", "contrast"]) setNode(id, "running"); pushRun();
      ev("kami", { event: "tool.end", tool_id: "p2", name: "delegate_task", ok: true, ms: 2800 });
      ev("kami", { event: "tool.start", tool_id: "p3", name: "delegate_task", detail: "Page styles, Code block colors, Contrast check", dag: dag(["page-styles", "code-colors", "contrast"]) });
      ev("kami", { event: "status", text: "Running 3 parts" });
    }],
    [7.2, () => { setNode("contrast", "done"); pushRun(); ev("kami", { event: "status", text: "Running 2 parts" }); }],
    [8.4, () => { setNode("code-colors", "done"); pushRun(); ev("kami", { event: "status", text: "Running 1 part" }); }],
    [9.6, () => {
      setNode("page-styles", "done"); setNode("verify-pr", "running"); pushRun();
      ev("kami", { event: "tool.end", tool_id: "p3", name: "delegate_task", ok: true, ms: 4000 });
      ev("kami", { event: "tool.start", tool_id: "p4", name: "delegate_task", detail: "Verify and open PR", dag: dag(["verify-pr"]) });
    }],
    [12, () => { setNode("verify-pr", "done"); pushRun("done"); ev("kami", { event: "tool.end", tool_id: "p4", name: "delegate_task", ok: true, ms: 2400 }); }],
    [12.8, () => {
      ev("kami", { event: "message", id: `p-pr-${runSeq}`, text: "Done in the preview: that is how a plan runs in omher. Before and after:\n\nMEDIA:/w/media/docs-light.webp\nMEDIA:/w/media/docs-dark.webp" });
      ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: false });
    }],
  ]);
}

hooks.approve = (bot, requestId, choice) => {
  if (bot !== "juno-bot" || requestId !== junoAsk) return;
  junoAsk = "";
  junoBusy = true;
  const done = () => { ev("juno-bot", { event: "turn.end", outcome: "done" }); ev("juno-bot", { event: "bot.status", status: "online", running: false }); junoBusy = false; };
  if (choice === "deny") {
    after([[0.5, () => { ev("juno-bot", { event: "message", id: `jd-${loop}`, text: "Okay, I won't deploy. The build stays on staging until you say so." }); done(); }]]);
    return;
  }
  after([
    [0.2, () => ev("juno-bot", { event: "tool.start", tool_id: `jt-${loop}`, name: "terminal", detail: "pnpm deploy api-server --prod" })],
    [2.6, () => ev("juno-bot", { event: "tool.end", tool_id: `jt-${loop}`, name: "terminal", ok: true, ms: 2400 })],
    [2.8, () => ev("juno-bot", { event: "message", id: `jo-${loop}`, text: "Deployed api-server 2.4 (in this preview, staged). Health checks are green and p95 is 83 ms." })],
    [3.6, () => { ev("juno-bot", { event: "message", id: `jp-${loop}`, text: "Posted the release in Slack #releases." }); done(); }],
  ]);
};
hooks.interrupt = (bot) => {
  if (bot === "kami") steps = []; // Stop on Kami ends this loop; a new one starts once the visitor is idle
  ev(bot, { event: "turn.end", outcome: "interrupted" });
  ev(bot, { event: "bot.status", status: "online", running: false });
};

// ---- the frame loop ---------------------------------------------------------------------------------------------

// One tick per display frame (requestAnimationFrame), timed with Date.now. A browser can hold back an iframe's frames
// (it was hidden while it loaded, a recording, a busy page): a 250 ms timer then keeps the story on time.
let last = 0;
let lastTick = 0;
let lastPin = 0;
// The chat follows the newest message while the story runs. The app's own "stick to the bottom" can lose that when a
// row grows between its scroll and the scroll event (two events in the same moment), which left the last bubble
// below the fold, under the composer. Scrolling to the end again also resets the app's flag, so it follows on.
function pinThread() {
  const el = document.querySelector<HTMLElement>('[data-testid="timeline"]');
  if (el && el.scrollHeight - el.scrollTop - el.clientHeight > 1) el.scrollTop = el.scrollHeight;
}
function frame() {
  tick();
  requestAnimationFrame(frame);
}
setInterval(() => {
  if (Date.now() - lastTick > 300) tick();
}, 250);
function tick() {
  const now = Date.now();
  lastTick = now;
  if (!last) {
    last = now;
    return;
  }
  const dt = Math.min(500, now - last) / 1000;
  last = now;
  const on = visible && !document.hidden;
  if (on) {
    liveT += dt;
    live.sort((a, b) => a[0] - b[0]);
    while (live.length && live[0][0] <= liveT) {
      live.shift()![1]();
      if (!live.length) liveEnd = Date.now();
    }
    if (!yielded() && !touched && now - lastPin > 250) {
      lastPin = now;
      pinThread();
    }
    if (!yielded() && !RM) {
      storyT += dt;
      while (steps.length && steps[0][0] <= storyT) steps.shift()![1]();
      // the visitor's own plan has landed and they are idle: the loop starts over
      if (!steps.length && !live.length && Date.now() - Math.max(lastInput, liveEnd) > YIELD_MS) fadeThen(startLoop);
    }
  }
}

// ---- start ---------------------------------------------------------------------------------------------------

async function seedSessions() {
  const S = getSessions();
  const ids: Record<string, string> = {};
  // two sessions: what fits whole under the four bots and the "needs you" strip in the hero-sized window (a third
  // row was cut in half at 975x568)
  for (const [folder, agent] of [["api-server", "codex"], ["web-app", "claude"]] as [string, AgentId][]) {
    const id = await S.launch(agent, `/Users/you/code/${folder}`);
    if (id) ids[folder] = id;
  }
  store().actions.openSession(null);
  const t = Date.now();
  for (const [f, cmd, ago] of [["web-app", "pnpm build", 4], ["api-server", "go test ./...", 9]] as [string, string, number][]) {
    const key = S.chatKey(ids[f]);
    if (!key) continue;
    ev(key, { event: "turn.start" }, t - ago * 60_000);
    ev(key, { event: "tool.start", tool_id: "x", name: "terminal", detail: cmd }, t - 30_000);
  }
}

export async function startStory(): Promise<void> {
  const s = store();
  // the app's init (bots, then every bot's chat): wait for all of them, or a chat that loads after the story raised
  // its turn (Juno's ask, Friren reading) would replace that turn with the plain history
  const loaded = () => ["kami", "friren", "juno-bot", "pip"].every((b) => s.getState().chats[b]?.loaded);
  for (let i = 0; i < 150 && !loaded(); i++) await new Promise((r) => setTimeout(r, 30));
  await seedSessions().catch(() => undefined);
  if (s.getState().selectedBot !== "kami") await s.actions.selectBot("kami");
  startLoop();
  // reduced motion: the settled state above with the running part open; nothing moves after it
  if (RM) {
    steps = [];
    setTimeout(() => openNode("page-styles"), 300);
  }
  requestAnimationFrame(frame);
  await new Promise((r) => setTimeout(r, 450));
  // the graph is drawn: tell the page the window is ready to show
  for (let i = 0; i < 40 && !document.querySelector('[data-testid="run-node"]'); i++) await new Promise((r) => setTimeout(r, 50));
  parent.postMessage({ type: "omher-preview:ready" }, location.origin);
}

/** For the page's own checks (e2e, recordings): where the story is. */
(window as unknown as { __omherPreview: unknown }).__omherPreview = {
  get t() { return storyT; },
  get loop() { return loop; },
  get yielded() { return yielded(); },
  get visible() { return visible && !document.hidden; },
  get lastInput() { return lastInputType; },
};
