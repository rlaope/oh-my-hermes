// The preview's live scenario: the window keeps moving with no input. Kami is a few minutes into the docs dark mode
// plan: its chat is the person's short ask and one big answer, with the spinner and one or two plain Hermes lines
// under it, while the Plans panel shows the parts; parts finish one by one, the next starts, the open part's detail
// grows, Slack / Discord replies and other bots' messages land, Kami posts the PR, and the loop
// starts over (~55-65 s, a little different each time). Since 0.2.12 the sidebar moves too: Kami's threads (one
// working, one waiting on an approval; both finish) change state and preview line, the PR message opens two threads
// (the bridge's split path: `thread.split`), and in TERMINALS a Codex card and a Claude Code card each work through
// their own task, drawn the way those CLIs draw it. Real clock: requestAnimationFrame plus Date.now, with a 250 ms timer when frames are held back.
// The visitor always wins: any click, key or wheel pauses the story for 8 s, and what they set off (a reply, the
// plan built from scratch, Juno's deploy) plays on its own timers. Hidden tab or window off-screen: paused.
// Everything is staged data inside the page; nothing runs anywhere.
import { getStore } from "../src/state/store";
import { getSessions } from "../src/sessions/sessions";
import { type AgentId } from "../src/sessions/agents";
import { threadKey } from "../src/threads/types";
import { refreshRuns } from "../src/runs/live";
import { addThread, away, broadcast, dropThread, history, hooks, nowS, PR_REPO, runs, threads, threadSaid, visitorThreads } from "./host";
import recordings from "./media/terminals.json";

type Ev = { event: string; [k: string]: unknown };
const store = () => getStore();
const ev = (bot: string, e: Ev, at = Date.now()) => store().dispatch({ type: "event", ev: { bot, ...e } as never, now: at });
const RM = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const rand = (a: number, b: number) => a + Math.random() * (b - a);

// ---- the plan ------------------------------------------------------------------------------------------------

const RUN_BASE = "dag:20261110_091904_d4a1c7e2/dark-mode";
let runSeq = 0;
let RUN = RUN_BASE;
const runName = () => RUN.split("/").pop()!;
// Kami's chat at rest: the person's short ask, ONE big answer from Kami, and under it the spinner with one or two
// plain grey Hermes lines (what the running parts do now) and the time. The answer names the places the way a person
// would, by their links: the Discord and Slack chips take their #channel from host.ts links.places, the GitHub one
// points at the staged acme/web-app (Tasks); guard.ts keeps every chip from opening anything.
const REQUEST = "Can you add dark mode to the docs today? Open a PR when it's done.";
const PROGRESS =
  "I'm following Mina's notes in https://acme.slack.com/archives/C02DESIGN/p1794195216893139?thread_ts=1794195216.893139: links stay purple, and the theme follows the system. " +
  "Sam asked for the same in https://discord.com/channels/1/900000000000000009, so I'll tell him there when it's live. " +
  "The new code colors also fix https://github.com/acme/web-app/issues/139. " +
  "I'll post the PR here once every page passes a contrast check in both themes.";
const PR_URL = "https://github.com/acme/web-app/pull/146";
// [id, label, deps, model, provider, effort, category, executor]. The cast: three Hermes subagents on GLM, Kimi and
// DeepSeek, and three lanes handed to agent CLIs (Claude Code on Opus, Codex on GPT-6.1 Sol, omp on Sonnet), side by side.
// Two parts to a row, then the fan-in (contrast after both styles, then verify): the graph the promo film and the
// stills draw, which fits the hero window's Plans panel whole with each box's model, effort and route on one line
// (a lane says "via Claude" where a subagent names its category, as in the film).
const NODES: [string, string, string[], string, string, string, string, string?][] = [
  ["color-tokens", "Color tokens", [], "GLM-5.3", "z-ai", "medium", "quick"],
  ["theme-toggle", "Theme toggle", [], "Kimi K3", "moonshot", "high", "visual-engineering"],
  ["page-styles", "Page styles", ["color-tokens", "theme-toggle"], "Opus 5.5", "claude-proxy", "high", "", "claude"],
  ["code-colors", "Code block colors", ["color-tokens", "theme-toggle"], "gpt-6.1-sol", "openai", "medium", "", "codex"],
  ["contrast", "Contrast check", ["page-styles", "code-colors"], "DeepSeek V4.1", "deepseek", "high", "review"],
  ["verify-pr", "Verify and open PR", ["contrast"], "Sonnet 5.5", "claude-proxy", "high", "", "omp"],
];
// the pull request each part opens, once it has started (GitHub's state for it: host.ts PR_STATES)
const PR: Record<string, number> = { "color-tokens": 2353, "theme-toggle": 2352, "page-styles": 2359, "code-colors": 2360 };
const SUMMARY: Record<string, string> = {
  "color-tokens": "12 light/dark token pairs in theme.css.",
  "theme-toggle": "A toggle in the header; it remembers the choice and follows the system theme.",
  "page-styles": "Body, sidebar and search moved to the new tokens.",
  "code-colors": "A dark code theme with the same contrast as the light one.",
  contrast: "Every token pair passes WCAG AA.",
  "verify-pr": "Built the docs, checked 14 pages, opened PR #146.",
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
    "- Opened **PR #146**: docs dark mode",
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
      id, label, deps, layer: 0, state: s.state, model, provider, effort,
      ...(route ? { route } : {}),
      role: id === "verify-pr" ? "verify" : "build",
      ...(executor ? { executor } : {}),
      ...(s.started ? { started: s.started, attempts: [{ n: 1, outcome: s.state === "done" ? "accepted" : "open", started: s.started, ...(s.ended ? { ended: s.ended } : {}) }] } : { attempts: [] }),
      ...(s.ended ? { ended: s.ended } : {}),
      ...(s.state === "done" ? { summary: SUMMARY[id] } : {}),
      ...(s.started && PR[id] ? { pr: { number: PR[id], repo: PR_REPO, url: `https://github.com/${PR_REPO}/pull/${PR[id]}` } } : {}),
    };
  });
  runs.live = { id: RUN, kind: "dag", owner: { type: "bot", id: "kami" }, title: "Docs dark mode", goal: "Add dark mode to the docs site and open a PR.", state, started: runStarted, updated: t, nodes, ...(state === "done" ? { ended: t } : {}) };
  // the app's own reader (Plans, the header's panel button) reads the plan again now, not at its next 3 s poll
  void refreshRuns("kami");
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
/** Kami's working lines under the big bubble: the app's spinner line (Hermes' status and the turn's time) and, while a
 *  second part runs, one more plain grey line: the turn's `plan` rows, which preview.css shows as bare text under the
 *  status (no head, no boxes). The chat shows no per-part cards (no subagent events, no delegate_task rows): the Plans
 *  panel and the threads already show the parts, and the middle stays calm. */
function working(text: string, also = "", at = Date.now()) {
  ev("kami", { event: "status", text }, at);
  ev("kami", { event: "plan", items: also ? [{ text: also, status: "in_progress" }] : [] }, at);
}

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
  return !touched && !yielded() && s.selectedBot === "kami" && s.ui.view === "chat" && !s.ui.thread;
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
      setTimeout(snapPanel, 120);
    } else if (tries++ < 20) setTimeout(go, 100);
  };
  setTimeout(go, 60);
}

/** Bringing the open part's details into view scrolls the Plans panel; a line left half under its tab bar (the
 *  plan's goal) reads as clipped in the hero, so the panel moves on until that line is out of view. */
function snapPanel() {
  const sc = document.querySelector<HTMLElement>('[data-testid="details"] .pn-scroll');
  if (!sc || sc.scrollTop <= 0) return;
  const top = sc.getBoundingClientRect().top;
  for (const el of sc.querySelectorAll<HTMLElement>(".ph-goal, [data-testid=\"run-node\"]")) {
    const r = el.getBoundingClientRect();
    if (r.top < top - 1 && r.bottom > top + 1) {
      sc.scrollTop += Math.ceil(r.bottom - top);
      return;
    }
  }
}

// ---- Kami's threads ----------------------------------------------------------------------------------------------

const WEB = "/Users/you/code/web-app";
type RestThread = { id: string; title: string; ask: string; ago: number };
/** The two threads every loop opens on: one working, one waiting on an approval (both finish before the PR). Two, so
 *  the "+ New thread" row under them (1.0) sits whole above the BOTS cut in the hero-sized window. */
const REST: Record<"flake" | "notes", RestThread> = {
  notes: { id: "", title: "Release notes 2.4", ask: "Draft the 2.4 release notes and push them to a branch.", ago: 4 * 60 },
  flake: { id: "", title: "Flaky search test", ask: "The search test fails about 1 run in 10 on CI. Find out why and fix it.", ago: 6 * 60 },
};
for (const k of ["notes", "flake"] as const) REST[k].id = addThread("kami", REST[k].title, WEB);
/** Threads Kami opened during this loop (removed when the next loop starts). */
let split: string[] = [];
/** Open asks of threads, by request id: the thread and what happens once it is allowed. */
const threadAsks = new Map<string, { thread: string; run: Step[] }>();

/** A thread's event. Live ones go through the bridge socket, so the app's own thread handling runs (the row's state
 *  and last activity); the seeded past is dispatched with its time. */
const tev = (thread: string, e: Ev, at = Date.now()) =>
  at < Date.now() - 1000 ? ev("kami", { ...e, session: thread }, at) : broadcast({ ...e, bot: "kami", session: thread });
const said = (thread: string, role: "user" | "assistant", id: string, text: string, at = Date.now()) => {
  threadSaid("kami", thread, { id, role, text, ts: at / 1000 });
  if (role === "assistant") tev(thread, { event: "message", id, text }, at);
};
const threadStart = (thread: string, at = Date.now()) => {
  threadSaid("kami", thread, null, true);
  tev(thread, { event: "turn.start" }, at);
};
const threadEnd = (thread: string, at = Date.now()) => {
  threadSaid("kami", thread, null, false);
  tev(thread, { event: "turn.end", outcome: "done" }, at);
};
function threadAsk(thread: string, id: string, command: string, run: Step[], at = Date.now()) {
  threadAsks.set(id, { thread, run });
  tev(thread, { event: "approval.request", request_id: id, title: "Run shell command", command, choices: ["deny", "once", "session"] }, at);
}
/** The person allows a thread's ask (the story stands in for them while the visitor only watches). */
function allow(id: string) {
  const a = threadAsks.get(id);
  if (!a) return;
  void store().actions.respondApproval(id, "once", threadKey("kami", a.thread));
}

/** Every loop starts from the same two threads; the ones Kami or the visitor opened last loop are gone (archived). */
function resetThreads(t0: number) {
  const s = store();
  for (const th of split) {
    dropThread("kami", th);
    broadcast({ event: "thread.removed", bot: "kami", thread: th });
  }
  split = [];
  for (const [bot, th] of visitorThreads.splice(0)) {
    dropThread(bot, th);
    broadcast({ event: "thread.removed", bot, thread: th });
  }
  threadAsks.clear();
  for (const r of Object.values(REST)) {
    const t = threads.kami.find((x) => x.thread === r.id);
    if (t) {
      t.msgs = [];
      t.running = false;
    }
    s.dispatch({ type: "chat.forget", bot: threadKey("kami", r.id) });
  }
  const { notes, flake } = REST;
  said(notes.id, "user", `tn-u-${loop}`, notes.ask, t0 - notes.ago * 1000);
  threadStart(notes.id, t0 - notes.ago * 1000 + 4_000);
  said(notes.id, "assistant", `tn-a-${loop}`, "Drafted `docs/releases/2.4.md`: delta updates, faster search, the rate limits.", t0 - 70_000);
  threadAsk(notes.id, `tn-ap-${loop}`, "git push origin release-notes-2.4", [
    [0.3, () => tev(notes.id, { event: "tool.start", tool_id: `tn-p-${loop}`, name: "terminal", detail: "git push origin release-notes-2.4" })],
    [1.7, () => tev(notes.id, { event: "tool.end", tool_id: `tn-p-${loop}`, name: "terminal", ok: true, ms: 1400 })],
    [2.1, () => { said(notes.id, "assistant", `tn-b-${loop}`, "Pushed `release-notes-2.4` and opened **PR #131** for it."); threadEnd(notes.id); }],
  ], t0 - 25_000);
  said(flake.id, "user", `tf-u-${loop}`, flake.ask, t0 - flake.ago * 1000);
  threadStart(flake.id, t0 - flake.ago * 1000 + 5_000);
  tev(flake.id, { event: "tool.start", tool_id: `tf-t-${loop}`, name: "terminal", detail: "pnpm test search --repeat 50" }, t0 - 40_000);
}

/** Kami opens two threads from its PR message (the bridge's split path: `thread.split`; the main chat shows a link
 *  line for each under that message), so the chat gets no extra ask and answer. */
function splitThreads(msg: string) {
  const post = addThread("kami", "Release post 2.4", WEB);
  const links = addThread("kami", "Docs link check", WEB);
  split = [post, links];
  for (const [th, title, task] of [
    [post, "Release post 2.4", "Draft the 2.4 release on GitHub from docs/releases/2.4.md. Leave it as a draft."],
    [links, "Docs link check", "Check every link in the docs and fix what is broken."],
  ] as const) {
    broadcast({ event: "thread.split", bot: "kami", thread: th, title, message: msg });
    said(th, "user", `${th}-u`, task);
    threadStart(th);
  }
}

// ---- TERMINALS ---------------------------------------------------------------------------------------------------

/** The terminal cards in web-app: Codex and Claude Code, each in its own terminal and at work on its own task, side
 *  by side. Two cards, so TERMINALS and Kami's threads both fit whole in the hero-sized window (the app's own auto
 *  split shows the smaller region whole and cuts the other on a whole row: three cards left a thread under the cut). */
const term: Record<"codex" | "claude", string | null> = { codex: null, claude: null };
const w = window as unknown as { __omherMockOut?: (id: number, d: string) => boolean };
/** Print into a terminal card's program, as it would (its second line reads the last line). */
function say(role: keyof typeof term, text: string) {
  const id = term[role];
  const pty = id ? getSessions().ptyOf(id) : null;
  if (pty !== null) w.__omherMockOut?.(pty, text);
}

// What each card shows is a recording, not a mock: Claude Code 2.1.327 and Codex CLI 0.169 were run for real in a
// 75x31 pty (the size the hero's terminal pane gets at font 12.5, boot.ts) on a staged copy of web-app, each given
// one task. The pty bytes were played into a virtual screen and sampled every 0.1-0.2 s; each sample keeps the rows
// that changed, written whole (media/terminals.json; the temp home folder shown as /Users/you). A TUI repaints by
// diff, so editing its raw bytes would break every later screen; whole rows keep each one exactly as the CLI drew it:
// Claude Code's mascot header, spinner, diff and prompt box; Codex's header, tool groups, "• Working (12s • esc to
// interrupt)", composer and footer. The story plays them on the real clock; each loop starts them over a few seconds
// in, so a card opened at any moment shows work.
type Rec = { cols: number; rows: number; frames: [number, string][] };
const REC = recordings as unknown as Record<keyof typeof term, Rec>;
/** Seconds into each recording where a loop picks it up: the prompt is already sent and the agent is at work. */
const REC_FROM = { claude: 6, codex: 20 } as const;
const recAt = { claude: 0, codex: 0 };
let recT0 = 0;
/** ms the page has been on screen: the recordings' clock (a hidden tab holds them where they are). */
let recClock = 0;
/** Plays each recording up to `now` on the recordings' clock (called every tick). */
function playTerms(now: number) {
  for (const role of ["codex", "claude"] as const) {
    const r = REC[role];
    const until = REC_FROM[role] + (now - recT0) / 1000;
    let chunk = "";
    while (recAt[role] < r.frames.length && r.frames[recAt[role]][0] <= until) chunk += r.frames[recAt[role]++][1];
    if (chunk) say(role, chunk);
  }
}
/** Both cards at the start of a loop: a fresh screen with the recording played up to `REC_FROM` at once. */
function termsAtStart() {
  recT0 = recClock;
  for (const role of ["codex", "claude"] as const) {
    recAt[role] = 0;
    say(role, "\x1bc");
  }
  playTerms(recClock);
}

// ---- one loop --------------------------------------------------------------------------------------------------

let loop = 0;
let junoAsk = "";
let junoBusy = false;

function resetKami(asked: number, answered: number) {
  const ask = { id: `ask-${loop}`, role: "user" as const, text: REQUEST, ts: asked / 1000 };
  const answer = { id: `k-plan-${loop}`, role: "assistant" as const, text: PROGRESS, ts: answered / 1000 };
  history.kami = [ask, answer];
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
  if (app.getState().ui.panelMax) app.actions.setPanelMax(false);
  if (app.getState().selectedBot !== "kami" || app.getState().ui.thread) void app.actions.selectBot("kami");
  touched = false;
  storyT = 0;
  const j = rand(0.94, 1.08); // each loop a little different
  const t0 = Date.now();
  const asked = t0 - rand(540, 600) * 1000; // the ask came ~9-10 minutes ago: the plan started then
  const T = t0 - rand(125, 145) * 1000; // Kami's answer and the working line under it: ~2m 14s on arrival
  runStarted = asked / 1000 + 40;
  RUN = RUN_BASE;
  st = {};
  runs.handoffs[RUN] = {};
  resetKami(asked, T - 1000);
  resetThreads(t0);
  setNode("color-tokens", "done", T / 1000 - 60);
  st["color-tokens"].started = runStarted;
  setNode("theme-toggle", "done", T / 1000 - 8);
  st["theme-toggle"].started = runStarted;
  // Page styles (the part the Plans panel opens) started with the turn, so its time and the working line's agree
  setNode("page-styles", "running", T / 1000);
  setNode("code-colors", "running", T / 1000 + rand(2, 6));
  ev("kami", { event: "bot.status", status: "online", running: true }, T);
  ev("kami", { event: "turn.start" }, T);
  working("Editing docs/styles/code.css", "Moving the sidebar to the new colors", T + 500);
  stream("page-styles", 1);
  pushRun();
  termsAtStart();

  // the others: Friren reading, Juno waiting on an approval, two coding sessions busy
  ev("friren", { event: "bot.status", status: "online", running: true }, t0 - 50_000);
  ev("friren", { event: "turn.start" }, t0 - 50_000);
  ev("friren", { event: "tool.start", tool_id: `f${loop}`, name: "web_extract", detail: "Tauri 2.4 release notes" }, t0 - 20_000);
  if (!junoAsk && !junoBusy) raiseJuno(t0 - 60_000);

  const k = (s: number) => s * 1.1 * j;
  const notesAsk = `tn-ap-${loop}`;
  const { flake } = REST;
  steps = [
    [k(0.2), () => openNode("page-styles")],
    [k(1.8), () => { stream("page-styles", 2); pushRun(); }],
    [k(2.6), () => ev("friren", { event: "status", text: "Reading the updater section" })],
    [k(3.2), () => working("Checking code blocks in light and dark", "Moving the sidebar to the new colors")],
    [k(5), () => allow(notesAsk)],
    [k(6), () => { stream("page-styles", 3); pushRun(); }],
    [k(7.6), () => working("Checking code blocks in light and dark", "Editing docs/styles/search.css")],
    [k(10.5), () => { stream("page-styles", 4); pushRun(); working("Writing the dark code theme", "Editing docs/styles/search.css"); }],
    [k(12.5), () => ev("pip", { event: "message", id: `pip-${loop}`, text: "Standup notes are filed: 4 updates, 1 blocker (the iOS build)." })],
    [k(13.2), () => {
      tev(flake.id, { event: "tool.end", tool_id: `tf-t-${loop}`, name: "terminal", ok: true, ms: 41_000 });
      said(flake.id, "assistant", `tf-a-${loop}`, "Found it: the test raced the index refresh. It waits for the refresh now, and 50 of 50 runs pass.");
      threadEnd(flake.id);
    }],
    [k(14), () => { setNode("code-colors", "done"); pushRun(); working("Editing docs/styles/search.css"); }],
    [k(16), () => { stream("page-styles", 5); pushRun(); }],
    [k(17.5), () => { setNode("page-styles", "done"); setNode("contrast", "running"); pushRun(); working("Checking contrast in light and dark"); }],
    [k(20.5), () => {
      setNode("contrast", "done"); setNode("verify-pr", "running");
      runs.handoffs[RUN]["verify-pr"] = STREAM["verify-pr"][0];
      pushRun();
      working("Building the docs");
      openNode("verify-pr");
    }],
    [k(22.5), () => {
      ev("friren", { event: "tool.end", tool_id: `f${loop}`, name: "web_extract", ok: true, ms: 50_000 });
      ev("friren", { event: "message", id: `fr-${loop}`, text: "Wrote up the Tauri 2.4 notes: delta updates, smaller bundles, nothing breaking for us." });
      ev("friren", { event: "turn.end", outcome: "done" });
      ev("friren", { event: "bot.status", status: "online", running: false });
    }],
    [k(23.5), () => { stream("verify-pr", 2); pushRun(); working("Checking 14 pages in light and dark"); }],
    [k(27), () => { stream("verify-pr", 3); pushRun(); working("Opening the pull request"); }],
    [k(31), () => { stream("verify-pr", 4); setNode("verify-pr", "done"); pushRun("done"); }],
    [k(32), () => {
      ev("kami", { event: "message", id: `k-pr-${loop}`, text: `The PR is up: ${PR_URL}. I told Sam in #releases, and I opened two threads, one for the 2.4 release post and one to check the docs links.` });
      ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: false });
      splitThreads(`k-pr-${loop}`);
    }],
    // replies elsewhere land once the turn is over (the header's places chip and the panel count them; preview.css
    // keeps them out of Kami's chat, which stays the ask, the big answer and the PR)
    [k(33.8), () => landAway("discord")],
    [k(40), () => landAway("slack")],
    [k(40.5), () => split[1] && tev(split[1], { event: "tool.start", tool_id: `tk-l-${loop}`, name: "terminal", detail: "lychee docs/" })],
    [k(42.5), () => {
      const post = split[0];
      if (!post) return;
      threadAsk(post, `tp-ap-${loop}`, "gh release create v2.4 --draft --notes-file docs/releases/2.4.md", [
        [0.3, () => tev(post, { event: "tool.start", tool_id: `tp-r-${loop}`, name: "terminal", detail: "gh release create v2.4 --draft" })],
        [1.5, () => tev(post, { event: "tool.end", tool_id: `tp-r-${loop}`, name: "terminal", ok: true, ms: 1200 })],
        [1.9, () => { said(post, "assistant", `tp-a-${loop}`, "The v2.4 release is drafted on GitHub, not published. It links PR #146 and PR #131."); threadEnd(post); }],
      ]);
    }],
    [k(45.5), () => {
      const links = split[1];
      if (!links) return;
      tev(links, { event: "tool.end", tool_id: `tk-l-${loop}`, name: "terminal", ok: true, ms: 6_000 });
      said(links, "assistant", `tk-a-${loop}`, "All 214 docs links resolve. Fixed 2 that pointed at old redirects.");
      threadEnd(links);
    }],
    [k(48.5), () => allow(`tp-ap-${loop}`)],
    [k(52), () => fadeThen(startLoop)],
  ].sort((a, b) => (a[0] as number) - (b[0] as number)) as Step[];
}

function landAway(source: "slack" | "discord") {
  const t = nowS();
  const row =
    source === "slack"
      ? { id: "slack-design-docs", source: "slack", title: "docs theme", place: "#design", url: "slack://channel?team=T1&id=C2", target: "slack:C02DESIGN:1794200000.000100", reply: "Told Mina the dark theme is in review as PR #146.", startedAt: t - 300, lastAt: t, count: 8 }
      : { id: "discord-releases", source: "discord", title: "release notes", place: "#releases", url: "https://discord.com/channels/1/9", target: "discord:900000000000000009", reply: "Sam asked if dark mode follows the system theme. It does, and the PR is up.", startedAt: t - 200, lastAt: t, count: 5 };
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
  // the answer first, then the turn: its working line sits under the last bubble (a turn's line stays above what is
  // said during it)
  after([
    [0, () => {
      if (k?.turn) ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: true });
    }],
    [1.2, () => {
      pushRun();
      store().actions.openRun(runName());
      ev("kami", { event: "message", id: `p-plan-${runSeq}`, text: "On it. The plan is on the right, and I'll post the PR here." });
      ev("kami", { event: "turn.start" });
      working("Editing docs/theme.css", "Adding the theme toggle");
    }],
    [2.8, () => { setNode("color-tokens", "running"); setNode("theme-toggle", "running"); pushRun(); }],
    [4.6, () => { setNode("color-tokens", "done"); pushRun(); working("Adding the theme toggle"); }],
    [5.6, () => {
      setNode("theme-toggle", "done"); for (const id of ["page-styles", "code-colors"]) setNode(id, "running"); pushRun();
      working("Editing docs/styles/code.css", "Moving the sidebar to the new colors");
    }],
    [7.4, () => { setNode("code-colors", "done"); pushRun(); working("Editing docs/styles/search.css"); }],
    [8.4, () => { setNode("page-styles", "done"); setNode("contrast", "running"); pushRun(); working("Checking contrast in light and dark"); }],
    [9.6, () => { setNode("contrast", "done"); setNode("verify-pr", "running"); pushRun(); working("Building the docs"); }],
    [12, () => { setNode("verify-pr", "done"); pushRun("done"); }],
    [12.8, () => {
      ev("kami", { event: "message", id: `p-pr-${runSeq}`, text: "That's how a plan runs in omher. Nothing ran in this preview, but here's the before and after.\n\nMEDIA:/w/media/docs-light.webp\nMEDIA:/w/media/docs-dark.webp" });
      ev("kami", { event: "turn.end", outcome: "done" });
      ev("kami", { event: "bot.status", status: "online", running: false });
    }],
  ]);
}

/** An oh-my-hermes session (a folder chat of the bot) answers its message with the preview note, through the same
 *  bridge events a real folder chat sends. */
hooks.folder = (bot, session) => {
  const name = bot === "juno-bot" ? "Juno" : bot.charAt(0).toUpperCase() + bot.slice(1);
  const isThread = (threads[bot] ?? []).some((t) => t.thread === session);
  const ko = document.documentElement.lang === "ko";
  const text = isThread
    ? ko
      ? `미리보기 스레드라 ${name}는 실행되지 않았어요. omher를 내려받으면 내 Hermes 봇과 진짜 스레드를 열 수 있어요.`
      : `This thread is a preview, so ${name} did not run. Download omher to open real threads with your own Hermes bots.`
    : ko
      ? `미리보기 세션이라 ${name}는 실행되지 않았어요. omher를 내려받으면 내 폴더에서 진짜 세션을 시작할 수 있어요.`
      : `This session is a preview, so ${name} did not run. Download omher to start a real one in your own folder.`;
  const id = `fv-${Math.random().toString(36).slice(2, 8)}`;
  // mid-turn (a thread at work): the note lands in the thread without ending its work
  const busy = !!store().getState().chats[threadKey(bot, session)]?.turn;
  after([
    ...(busy ? [] : ([[0, () => { broadcast({ event: "turn.start", bot, session }); broadcast({ event: "thinking", bot, session }); }]] as Step[])),
    [0.9, () => { threadSaid(bot, session, { id, role: "assistant", text, ts: nowS() }); broadcast({ event: "message", bot, session, id, text }); }],
    ...(busy ? [] : ([[1.0, () => broadcast({ event: "turn.end", bot, session, outcome: "done" })]] as Step[])),
  ]);
};

hooks.approve = (bot, requestId, choice, session) => {
  const ta = session ? threadAsks.get(requestId) : undefined;
  if (ta && ta.thread === session) {
    threadAsks.delete(requestId);
    if (choice === "deny") {
      after([[0.4, () => { said(ta.thread, "assistant", `${requestId}-no`, "Okay, I won't run it. Tell me when it should go out."); threadEnd(ta.thread); }]]);
      return;
    }
    after(ta.run);
    return;
  }
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
    // the terminals keep running while the visitor looks around, as real ones do; only a hidden page holds them
    recClock += dt * 1000;
    playTerms(recClock);
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

/** The TERMINALS cards, through the app's own + path (startTerminal): each starts in web-app and opens once so its
 *  terminal runs, then the window goes back to Kami. Claude Code and Codex run in their own terminals; the Shell is
 *  a login shell (the in-page one: nothing runs anywhere). */
async function seedTerminals() {
  const S = getSessions();
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  for (const [role, agent, name] of [["codex", "codex", "Search lang filter"], ["claude", "claude", "Search filters docs"]] as [keyof typeof term, AgentId, string][]) {
    const id = S.startTerminal(agent, WEB);
    if (!id) continue;
    term[role] = id;
    for (let i = 0; i < 100 && S.ptyOf(id) === null; i++) await sleep(40);
    if (name) S.rename(id, name);
  }
  await sleep(120);
  store().actions.openSession(null);
}

export async function startStory(): Promise<void> {
  const s = store();
  // the app's init (bots, then every bot's chat): wait for all of them, or a chat that loads after the story raised
  // its turn (Juno's ask, Friren reading) would replace that turn with the plain history
  const loaded = () => ["kami", "friren", "juno-bot", "pip"].every((b) => s.getState().chats[b]?.loaded);
  for (let i = 0; i < 150 && !loaded(); i++) await new Promise((r) => setTimeout(r, 30));
  await seedTerminals().catch(() => undefined);
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
