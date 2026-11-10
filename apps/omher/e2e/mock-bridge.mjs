// omher mock bridge: the same protocol as the real Python bridge (01-protocol.md), with seeded data and
// scripted turns, so every e2e test runs without Hermes. Node only, no dependencies: it carries its own
// minimal RFC 6455 WebSocket server (text frames, ping/pong, close, fragmentation).
//
//   node e2e/mock-bridge.mjs --port 5308 [--token T]
//
// Without --token it accepts `e2e` (playwright.config.ts) and `dev` (the UI's built-in default URL).
// Test-control ops (not part of the protocol): mock.calls, mock.submits, mock.emit {events}, mock.reset,
// mock.ask {bot, kind: approval|clarify|interview, timeout_ms?} (raise an ask on any bot, e.g. one not open),
// mock.demo (Kami's live "Docs dark mode" plan on top of his list, its nodes' PRs in mixed states; `--demo` seeds it
// at start and on every reset).
import http from "node:http";
import crypto from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : dflt;
};
const PORT = Number(arg("port", process.env.OMHER_MOCK_PORT || 5308));
const TOKENS = new Set(arg("token", "") ? [arg("token", "")] : ["e2e", "dev"]);
const GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const DEMO = argv.includes("--demo");

const now = () => Date.now() / 1000;
const BOOT = now();
const MIN = 60;

// ---- seed data -------------------------------------------------------------------------------

const BOT_SEED = [
  { name: "kami", display_name: "Kami", is_default: false, model: "Opus 5.5", provider: "claude-proxy", description: "khope's everyday assistant", status: "online", running: true, reasoning: "high" },
  { name: "friren", display_name: "Friren", is_default: false, model: "Sonnet 5.5", provider: "claude-proxy", description: "research and reading", status: "online", running: false, reasoning: "medium" },
  { name: "default", display_name: "Hermes", is_default: true, model: "Haiku 5", provider: "claude-proxy", description: "the default profile", status: "online", running: false, reasoning: "low" },
  { name: "omh-tui", display_name: "OMH TUI", is_default: false, model: "Sonnet 5.5", provider: "claude-proxy", description: "", status: "online", running: false, reasoning: "medium" },
];

const HISTORY_SEED = {
  kami: [
    ["user", "gateway 502 로그 좀 봐줄래?", 3 * 3600],
    ["assistant", "확인했어요. `/v1/responses`에서 upstream timeout이 간헐적으로 나고 있어요. 재시도 정책부터 볼게요.", 3 * 3600 - 40],
    // other bots by @name: each one opens that bot's chat (mention.spec.ts); @kami is this chat itself
    ["assistant", "keep-alive 문서는 @friren에게 찾아달라고 했어요. 배포 확인은 @hermes, TUI 화면은 @omh-tui가 보고, 정리는 제가(@kami) 할게요.", 3 * 3600 - 80],
    ["user", "Thanks. Ping me when the retry fix is up.", 2 * 3600],
  ],
  "omh-tui": [],
  friren: [
    ["user", "Summarise the Tauri 2 updater docs.", 5 * 3600],
    ["assistant", "The updater checks a signed manifest, downloads the bundle and swaps it on restart.", 5 * 3600 - 30],
  ],
  default: [
    ["assistant", "Hi, I'm Hermes. Ask me anything.", 24 * 3600],
    ["user", "Send me the chart, the clip and the report.", 2 * 3600],
    ["assistant", "Here they are.\n\nMEDIA:/w/media/chart.png\nMEDIA:/w/media/clip.mp4\nMEDIA:/w/media/report.zip", 2 * 3600 - 20],
    ["user", "Now the new chart, and both side by side.", 2 * 3600 - 60],
    // files only, no caption: still gets the face, on the bubble column
    ["assistant", "MEDIA:/w/media/chart-after.png", 2 * 3600 - 80],
    ["assistant", "Before and after:\nMEDIA:/w/media/chart.png\nMEDIA:/w/media/chart-after.png", 2 * 3600 - 81],
  ],
};

// media.read serves these tiny real files (e2e/fixtures/media) for the paths the seeded answers name.
const MEDIA_DIR = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "media");
const MEDIA_TYPES = { png: "image/png", mp4: "video/mp4", zip: "application/zip" };
const mediaLines = (text) =>
  text
    .split(/\r?\n/)
    .map((l) => /^[ \t]*MEDIA:[ \t]*(.+?)[ \t]*$/.exec(l)?.[1])
    .filter(Boolean);

// Away sessions are stored as offsets from "now" so the timeline always looks fresh.
const AWAY_SEED = {
  kami: [
    { id: "slack-og-dev-502", source: "slack", title: "gateway 502 on /v1/responses", place: "#og-dev", url: "slack://channel?team=T1&id=C1&thread_ts=1794186944.520669", target: "slack:C0123ABCD:1794186944.520669", reply: "Reading gateway logs from 14:31. Upstream resets look like keep-alive expiry.", started: 4 * MIN, last: 20, count: 14, running: true },
    { id: "discord-cron-openmaus", source: "discord", title: "OpenMausBot 조사후 브리핑", place: "#cron", url: "https://discord.com/channels/1/2", target: "discord:1569310397687791637:1569310397687791637", reply: "OpenMausBot은 Claude·Codex·Grok CLI를 채팅 앱으로 묶는 Electron 앱입니다. ⭐17,657, Apache-2.0입니다.", started: 3 * 3600, last: 2 * 3600, count: 6, running: false },
    { id: "discord-omh-2657", source: "discord", title: "PR #2657 review", place: "#oh-my-hermes", url: "https://discord.com/channels/1/3", target: "discord:1544259371528232981", started: 27 * 3600, last: 26 * 3600, count: 9, running: false },
  ],
  friren: [{ id: "telegram-reading-list", source: "telegram", title: "Reading list", started: 6 * 3600, last: 4 * 3600, count: 5, running: false }],
  default: [],
};
const PEEK_SEED = {
  "slack-og-dev-502": [
    ["user", "minji", "502s are back on /v1/responses since 14:10", 9],
    ["assistant", "", "Reading gateway logs. Upstream resets look like keep-alive expiry.", 8],
    ["user", "jun", "can we raise the pool idle timeout?", 6],
    ["assistant", "", "Trying that now, rolling to one replica first.", 4],
    ["user", "minji", "ok, watching the error rate", 2],
  ],
  "discord-cron-openmaus": [
    ["assistant", "", "Briefing: OpenMausBot ships weekly, 3 open issues, nothing blocking.", 120],
    ["user", "khope", "good, thanks", 118],
  ],
  "discord-omh-2657": [
    ["user", "rlaope", "PR #2657 is ready for review", 1600],
    ["assistant", "", "Reviewed. One blocking comment on the retry loop, otherwise fine.", 1590],
    ["user", "rlaope", "fixed, please re-check", 1570],
    ["assistant", "", "Approved.", 1560],
  ],
  "telegram-reading-list": [["user", "khope", "add the Tauri updater post", 240], ["assistant", "", "Added.", 239]],
};

const ROUTINE_SEED = {
  kami: [
    { id: "cron-repo-watch", name: "Repo watch", schedule: "Daily 09:00", next: 15 * 3600, last: -9 * 3600, status: "ok", enabled: true },
    { id: "cron-og-digest", name: "OG digest", schedule: "Weekly (Mon 09:00)", next: 6 * 24 * 3600, last: -24 * 3600, status: "ok", enabled: true },
  ],
  friren: [],
  default: [],
};

const PANEL_RUNS = {
  kami: [
    { id: "r3", command: "pytest tests/test_upstream.py -q", output: "............\n12 passed in 1.84s", exit_code: 0, cwd: "/w/gateway-keepalive", source: "tui", ago: 120 },
    { id: "r2", command: 'rg -n "keepalive|idle_timeout" gateway/', output: "gateway/upstream.py:41:    idle_timeout = 75\ngateway/upstream.py:88:    keepalive=True,", exit_code: 0, cwd: "/w/gateway-keepalive", source: "tui", ago: 300 },
    { id: "r1", command: "kubectl logs deploy/gateway --since=1h | grep -c 502", output: "37", exit_code: 0, cwd: "/w/gateway", source: "slack", ago: 900 },
    { id: "r0", command: "git push origin fix/keepalive", output: "error: failed to push some refs", exit_code: 1, cwd: "/w/gateway-keepalive", source: "tui", ago: 1800 },
  ],
  friren: [],
  default: [],
};
const PANEL_TREES = {
  kami: [
    { path: "/w/gateway-keepalive", branch: "fix/keepalive", head: "3f2c1a9e0", repo: "gateway", dirty: 2, ago: 120 },
    { path: "/w/gateway", branch: "main", head: "a91b0c2d4", repo: "gateway", dirty: 0, ago: 900 },
  ],
  friren: [],
  default: [],
};
const PANEL_DIFF = {
  "/w/gateway-keepalive": {
    scope: "uncommitted",
    files: [
      { path: "gateway/upstream.py", add: 1, del: 1 },
      { path: "tests/test_upstream.py", add: 3, del: 0 },
      { path: "notes/재시도.md", add: 0, del: 0, untracked: true },
    ],
    patch: [
      "diff --git a/gateway/upstream.py b/gateway/upstream.py",
      "--- a/gateway/upstream.py",
      "+++ b/gateway/upstream.py",
      "@@ -38,7 +38,7 @@ class Upstream:",
      "     pool_size = 32",
      "-    idle_timeout = 75",
      "+    idle_timeout = 55  # under upstream's 60s",
      "     retries = 2",
      "diff --git a/tests/test_upstream.py b/tests/test_upstream.py",
      "--- a/tests/test_upstream.py",
      "+++ b/tests/test_upstream.py",
      "@@ -1,3 +1,6 @@",
      "+def test_idle_timeout_is_below_upstream():",
      "+    assert Upstream().idle_timeout < 60",
      "+",
    ].join("\n"),
  },
  "/w/gateway": { scope: "last commit", files: [{ path: "README.md", add: 1, del: 0 }], patch: "a91b0c2 docs: note the 60s upstream limit\n\ndiff --git a/README.md b/README.md\n@@ -1 +1,2 @@\n # gateway\n+Upstream closes idle connections after 60s." },
};

// Runs tab: what the real bridge's dag_to_run returns for three real (redacted) dag runs plus a live variant
// (src/lib/__fixtures__/runs-bridge.json). The live one is moved to "now" so its times read like a running run.
const RUNS_FIXTURE = JSON.parse(readFileSync(new URL("../src/lib/__fixtures__/runs-bridge.json", import.meta.url), "utf-8"));
// T4/T5: the same runs with their helpers' models and routes joined (runs-routed.json, real bridge output), the
// omher-v02 run and two plain delegate fan-outs for "default", and a synthetic 40-node run for the layout.
const ROUTED = JSON.parse(readFileSync(new URL("../src/lib/__fixtures__/runs-routed.json", import.meta.url), "utf-8"));
const BIG = JSON.parse(readFileSync(new URL("../src/lib/__fixtures__/big-run.json", import.meta.url), "utf-8"));
const HANDOFFS = { ...RUNS_FIXTURE.handoffs, ...ROUTED.handoffs };
function runsSeed() {
  const runs = structuredClone(ROUTED.kami);
  for (const r of runs) {
    if (r.state !== "running") continue;
    const shift = now() - 90 - r.updated;
    const move = (o) => {
      for (const k of ["started", "ended", "updated"]) if (typeof o[k] === "number") o[k] += shift;
    };
    move(r);
    for (const n of r.nodes) {
      move(n);
      n.attempts.forEach(move);
    }
  }
  // "default" keeps its runs at their real times, except the live ones, moved to "now" like kami's. It also has
  // one run nobody has started (the live fan-out's plan with no attempts; `startsAt` is a mock-only field, OMH
  // records no start timer), for the plan card's "Starts in" / Start now / Edit.
  const planned = structuredClone(ROUTED.kami.find((r) => r.id.endsWith("/codex-coexist-live")));
  planned.id = "dag:20261102_235818_fcfb1bdd/codex-coexist-next";
  planned.title = "Codex coexistence (next)";
  planned.owner = { type: "bot", id: "default" };
  planned.state = "running";
  for (const n of planned.nodes) {
    n.state = "waiting";
    n.attempts = [];
    for (const k of ["started", "ended", "handoff", "model", "summary"]) delete n[k];
  }
  planned.started = planned.updated = now() - 5;
  planned.startsAt = now() + 10;
  delete planned.ended;
  const other = structuredClone([...ROUTED.default, BIG, planned]);
  for (const r of other) {
    if (r.state !== "running") continue;
    const shift = now() - 120 - r.updated;
    const move = (o) => {
      for (const k of ["started", "ended", "updated"]) if (typeof o[k] === "number") o[k] += shift;
    };
    move(r);
    for (const n of r.nodes) {
      move(n);
      n.attempts.forEach(move);
    }
  }
  return { kami: runs, friren: [], default: other };
}
// The demo plan (the site preview's and the promo's): Kami's docs dark mode, 9 minutes in. Three Hermes subagents on
// GLM, Kimi and DeepSeek, and Claude Code, Codex and omp lanes. Each part that opened a pull request names it the
// way a real helper does (a reason line or its handoff), and GitHub's state for it comes from `runs.prs`: two
// merged, one open, one draft; the two parts still to come have none.
const DEMO_RUN = "dag:20261110_091904_d4a1c7e2/docs-dark-mode";
const DEMO_REPO = "rlaope/oh-my-hermes";
const DEMO_PRS = { 2353: { state: "merged" }, 2352: { state: "merged" }, 2359: { state: "open" }, 2360: { state: "draft" } };
function demoPlan() {
  const t = now();
  const url = (n) => `https://github.com/${DEMO_REPO}/pull/${n}`;
  // [id, label, deps, model, provider, effort, category, executor, state, started (s ago), ended (s ago), pr]
  const spec = [
    ["color-tokens", "Color tokens", [], "z-ai/glm-5.3-ultrafast", "z-ai", "medium", "quick", null, "done", 520, 300, 2353],
    ["theme-toggle", "Theme toggle", [], "kimi-k3", "moonshot", "high", "visual-engineering", null, "done", 520, 250, 2352],
    ["contrast", "Contrast check", ["color-tokens"], "deepseek/deepseek-v4.1-flash", "deepseek", "high", "review", null, "running", 290, null, null],
    ["page-styles", "Page styles", ["color-tokens", "theme-toggle"], "claude-opus-5-5", "claude-proxy", "high", "visual-engineering", "claude", "running", 240, null, 2359],
    ["code-colors", "Code block colors", ["color-tokens", "theme-toggle"], "gpt-6.1-sol", "openai", "medium", "visual-engineering", "codex", "running", 235, null, 2360],
    ["verify-pr", "Verify and open PR", ["page-styles", "code-colors", "contrast"], "claude-sonnet-5-5", "claude-proxy", "high", "review", "omp", "waiting", null, null, null],
  ];
  const handoffs = {};
  const nodes = spec.map(([id, label, deps, model, provider, effort, route, executor, state, s0, s1, pr], i) => {
    const started = s0 === null ? undefined : t - s0;
    const ended = s1 === null ? undefined : t - s1;
    const n = { id, label, deps, layer: 0, state, model, provider, effort, route, category: route, role: id === "verify-pr" ? "verify" : "build", attempts: [] };
    if (executor) n.executor = executor;
    if (started !== undefined) {
      n.started = started;
      n.attempts = [{ n: 1, outcome: state === "done" ? "accepted" : "open", started, ...(ended !== undefined ? { ended } : {}) }];
    }
    if (ended !== undefined) n.ended = ended;
    if (pr) {
      n.pr = { number: pr, repo: DEMO_REPO, url: url(pr) };
      n.handoff = `${id}.md`;
      // what the helper wrote: the merged ones in their accepting reason, the others at the end of their handoff
      if (state === "done") n.attempts[0].reason = `merged ${url(pr)} (${["4e68fd8b4", "9471e35a8"][i]})`;
      handoffs[id] = `- ${label}: done on its branch\n- Opened PR #${pr}: ${url(pr)}`;
    }
    return n;
  });
  nodes.find((n) => n.id === "contrast").layer = 1;
  for (const id of ["page-styles", "code-colors"]) nodes.find((n) => n.id === id).layer = 1;
  nodes.find((n) => n.id === "verify-pr").layer = 2;
  const run = { id: DEMO_RUN, kind: "dag", owner: { type: "bot", id: "kami" }, title: "Docs dark mode", goal: "Add dark mode to the docs site and open a PR.", state: "running", started: t - 540, updated: t - 5, nodes };
  return { run, handoffs };
}
function seedDemo() {
  const { run, handoffs } = demoPlan();
  runs.kami = [run, ...runs.kami.filter((r) => r.id !== DEMO_RUN)];
  HANDOFFS[DEMO_RUN] = handoffs;
}

// T6: CLI agents' runs (runs.cli) - the real bridge's CliRuns output over the redacted Claude Code and Codex
// fixtures (src/lib/__fixtures__/runs-cli.json, bridge/tests/fixtures/cli). Plus one live copy of the Claude
// session moved to "now" with its last subagent still working (mock-only, so the running look can be checked).
const CLI_FIXTURE = JSON.parse(readFileSync(new URL("../src/lib/__fixtures__/runs-cli.json", import.meta.url), "utf-8"));
function cliSeed() {
  const runs = structuredClone(CLI_FIXTURE.runs);
  const live = structuredClone(runs.find((r) => r.agent === "claude"));
  live.id = "claude:live-session";
  live.owner = { type: "session", id: "live-session" };
  live.title = "Fix the flaky login test";
  live.state = "running";
  // the session opened 4 minutes ago; its three calls went out 3m30s, 3m and 1m30s ago
  live.started = now() - 240;
  live.updated = now() - 20;
  delete live.ended;
  live.nodes.forEach((n, i) => {
    const at = now() - [210, 180, 90][i];
    const dur = (n.ended ?? n.started) - n.started;
    n.started = at;
    if (typeof n.ended === "number") n.ended = at + Math.min(dur, 150);
    for (const a of n.attempts) {
      a.started = at;
      if (typeof a.ended === "number") a.ended = n.ended;
    }
    if (i === 0) {
      // the failed call, retried with the right agent type: done
      n.state = "done";
      n.attempts = [{ n: 1, outcome: "completed", started: n.started, ended: n.started + 40 }];
      n.ended = n.started + 40;
      n.summary = "Reviewed the login flow: the test waited on a stale selector; fixed.";
    }
    if (i === live.nodes.length - 1) {
      n.state = "running";
      n.attempts = [{ n: 1, outcome: "open", started: n.started }];
      delete n.ended;
      delete n.summary;
    }
  });
  return [live, ...runs];
}

// the bridge's run_summary: `failed` = open failures; a failure its repairs all fixed counts as `repaired`
const runCounts = (r) => {
  const fixed = r.nodes.filter(
    (n) => (n.state === "failed" || n.state === "blocked") && r.nodes.some((m) => m.repairOf === n.id) && r.nodes.filter((m) => m.repairOf === n.id).every((m) => m.state === "done"),
  ).length;
  return {
    nodes: r.nodes.length,
    done: r.nodes.filter((n) => n.state === "done").length,
    running: r.nodes.filter((n) => n.state === "running").length,
    failed: r.nodes.filter((n) => n.state === "failed" || n.state === "blocked").length - fixed,
    ...(fixed ? { repaired: fixed } : {}),
  };
};

const PROVIDERS = [
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5", "Sonnet 5.5", "Haiku 5"] },
  { slug: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6.1-terra"] },
  // several vendors behind one provider, so the picker's search and vendor chips have something to sort
  {
    slug: "openrouter",
    name: "OpenRouter",
    models: ["anthropic/claude-opus-5-5", "google/gemini-3-pro", "deepseek/deepseek-v4.1", "x-ai/grok-4.7", "qwen/qwen3-coder"],
  },
  { slug: "ollama", name: "Ollama", models: ["llama-4-maverick", "my-local-model"] },
];
const REASONING_LEVELS = ["none", "low", "medium", "high", "xhigh"];

// ---- mutable state ---------------------------------------------------------------------------

let calls = [];
// What the bridge would hand Hermes' prompt.submit (the text after the reply-target block is added).
let submits = [];
let bots, history, models, turns, pending, idSeq, queues, avatars, folders, runs, cliRuns;
// Every ask event sent, by request id: chat.open sends the ones still pending again, as the bridge does.
let asked;

// What each bot has done (bots.info): sessions per place, skills, routines.
const INFO_SEED = {
  kami: { places: { slack: 78, discord: 48, cron: 15 }, first: 14 * 24 * 3600, skills: 134 },
  friren: { places: { telegram: 6 }, first: 3 * 24 * 3600, skills: 12 },
  default: { places: {}, first: null, skills: 41 },
};

// Every bot's skills (skills.list), sorted by name as the bridge sends them: plan and review, one that only
// contains "pl", and one long name with a long description.
const SKILL_SEED = [
  { name: "deep-interview", description: "Ask the questions that settle what to build before any code is written." },
  { name: "explain-code", description: "Walk through a piece of code and say what each part does." },
  {
    name: "long-document-reading-and-summarising",
    description: "Read a document far larger than the context in passes, keep a running outline, and answer with page refe…",
  },
  { name: "plan", description: "Break the work into steps and agree on them before doing it." },
  { name: "research", description: "Find sources, read them and answer with citations." },
  { name: "review", description: "Review a diff for correctness, tests and risk, worst first." },
];

// Subscription usage (usage.read). "default": Codex 73 % / 60 %, Claude limited (no %), Grok on PATH only.
// "stale": the same Codex record after both reset times passed (no numbers). Switch with mock.usage {fixture}.
let usageFixture = "default";
const USAGE = {
  default: () => [
    { id: "codex", plan: "pro", state: "near", source_mtime: now() - 120,
      windows: [
        { label: "5 hours", used_percent: 73, resets_at: now() + 107 * MIN },
        { label: "Weekly", used_percent: 60, resets_at: now() + (4 * 24 + 23) * 3600 },
      ] },
    { id: "claude", state: "limited", source_mtime: now() - 600,
      windows: [{ label: "Weekly", resets_at: now() + 3 * 3600 + 12 * MIN }] },
    { id: "grok", state: "connected", source_mtime: null, windows: [] },
  ],
  stale: () => [
    { id: "codex", plan: "pro", state: "stale", source_mtime: now() - 9 * 24 * 3600,
      windows: [
        { label: "5 hours", resets_at: now() - 8 * 24 * 3600, stale: true },
        { label: "Weekly", resets_at: now() - 2 * 24 * 3600, stale: true },
      ] },
  ],
};

// Accounts (accounts.*), shaped like the real bridge: every coding CLI, the CLI's own login first ("default").
// Claude: signed in on this computer (owner@example.com), plus a local CLIProxyAPI holding 5 logins (counted
// only). Codex: this computer + "Work", this computer in use. pi: on this computer, signed in. oh-my-pi, Grok,
// Gemini: not installed. mock.accounts {limit: id, cli?} marks an account limited (as its usage record would).
const ACCT_CLIS = ["claude", "codex", "pi", "omp", "grok", "gemini"];
const ACCT_INSTALLED = { claude: true, codex: true, pi: true, omp: false, grok: false, gemini: false };
let acct, acctActive, acctLimited, acctLabels;
const ACCT_ID = /^[a-z0-9][a-z0-9._-]{0,39}$/;
function accountsList() {
  return {
    groups: ACCT_CLIS.map((cli) => {
      const rows = acct[cli].map((a) => {
        const limited = acctLimited[`${cli}:${a.id}`];
        const state = !a.logged_in ? "login" : limited ? "limited" : a.id === acctActive[cli] ? "active" : "ready";
        return {
          id: a.id,
          label: a.id === "default" ? acctLabels[cli] ?? "" : a.label,
          email: a.email ?? "",
          state,
          dir: a.id === "default" ? null : `/mock/.omher/accounts/${cli}/${a.id}`,
          usage: cli === "codex" && a.id === "default" ? USAGE.default()[0] : null,
          ...(limited ? { resets_at: limited } : {}),
        };
      });
      return {
        cli,
        installed: ACCT_INSTALLED[cli],
        active: acctActive[cli],
        accounts: rows,
        ...(cli === "claude" ? { also: { name: "CLIProxyAPI", accounts: 5 } } : {}),
      };
    }),
  };
}
const acctUpdate = () => setTimeout(() => broadcast({ event: "accounts.update", bot: "" }), 0);
function acctFind(p) {
  if (!ACCT_CLIS.includes(p.cli)) throw new OpError("bad_request", "unknown cli");
  const id = p.account;
  if (typeof id !== "string" || (id !== "default" && !ACCT_ID.test(id))) throw new OpError("bad_request", "bad account id");
  const a = acct[p.cli].find((x) => x.id === id);
  if (!a) throw new OpError("not_found", "no such account");
  return a;
}

function reset() {
  usageFixture = "default";
  acct = {
    claude: [{ id: "default", label: "", email: "owner@example.com", logged_in: true }],
    codex: [{ id: "default", label: "", logged_in: true }, { id: "work", label: "Work", logged_in: true }],
    pi: [{ id: "default", label: "", logged_in: true }],
    omp: [{ id: "default", label: "", logged_in: false }],
    grok: [{ id: "default", label: "", logged_in: false }],
    gemini: [{ id: "default", label: "", logged_in: false }],
  };
  acctActive = Object.fromEntries(ACCT_CLIS.map((c) => [c, "default"]));
  acctLimited = {};
  acctLabels = {};
  for (const t of Object.values(turns ?? {})) t?.timers.forEach(clearTimeout);
  bots = Object.fromEntries(BOT_SEED.map((b) => [b.name, { ...b }]));
  history = Object.fromEntries(
    Object.entries(HISTORY_SEED).map(([bot, rows]) => [
      bot,
      rows.map(([role, text, ago], i) => ({ id: `seed-${bot}-${i}`, role, text, ts: BOOT - ago })),
    ]),
  );
  models = Object.fromEntries(BOT_SEED.map((b) => [b.name, { model: b.model, provider: b.provider, reasoning: b.reasoning }]));
  turns = {};
  queues = {};
  avatars = {};
  folders = new Map(); // folder chat id -> { bot, cwd, open }
  runs = runsSeed();
  cliRuns = cliSeed();
  if (DEMO) seedDemo();
  pending = new Map();
  asked = new Map();
  idSeq = 0;
  calls = [];
  submits = [];
}
reset();

const nextId = (p) => `${p}-${++idSeq}`;
const publicBot = ({ reasoning, ...b }) => ({
  ...b,
  model: models[b.name].model,
  provider: models[b.name].provider,
  avatar_rev: avatars[b.name]?.rev ?? null,
});

// ---- WebSocket server ------------------------------------------------------------------------

const clients = new Set();

function frame(opcode, payload) {
  const len = payload.length;
  let head;
  if (len < 126) head = Buffer.from([0x80 | opcode, len]);
  else if (len < 65536) head = Buffer.from([0x80 | opcode, 126, len >> 8, len & 255]);
  else {
    head = Buffer.alloc(10);
    head[0] = 0x80 | opcode;
    head[1] = 127;
    head.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([head, payload]);
}

function sendJson(sock, obj) {
  if (!sock.destroyed && sock.writable) sock.write(frame(0x1, Buffer.from(JSON.stringify(obj))));
}
function broadcast(ev) {
  for (const c of clients) sendJson(c, ev);
}

function attach(sock, onText) {
  let buf = Buffer.alloc(0);
  let frag = null; // { opcode, parts }
  sock.on("data", (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const fin = (buf[0] & 0x80) !== 0;
      const opcode = buf[0] & 0x0f;
      const masked = (buf[1] & 0x80) !== 0;
      let len = buf[1] & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) return;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) return;
        len = Number(buf.readBigUInt64BE(2));
        off = 10;
      }
      const need = off + (masked ? 4 : 0) + len;
      if (buf.length < need) return;
      let payload = buf.subarray(off + (masked ? 4 : 0), need);
      if (masked) {
        const mask = buf.subarray(off, off + 4);
        payload = Buffer.from(payload.map((b, i) => b ^ mask[i & 3]));
      }
      buf = buf.subarray(need);
      if (opcode === 0x8) {
        sock.end(frame(0x8, payload.subarray(0, 2)));
        return;
      }
      if (opcode === 0x9) {
        sock.write(frame(0xa, payload));
        continue;
      }
      if (opcode === 0xa) continue;
      if (opcode === 0x1 || opcode === 0x2) frag = { opcode, parts: [payload] };
      else if (opcode === 0x0 && frag) frag.parts.push(payload);
      else continue;
      if (fin) {
        const text = Buffer.concat(frag.parts).toString("utf8");
        frag = null;
        onText(text);
      }
    }
  });
}

const server = http.createServer((req, res) => {
  res.writeHead(426, { "content-type": "text/plain" });
  res.end("omher mock bridge: WebSocket only\n");
});

server.on("upgrade", (req, sock) => {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const key = req.headers["sec-websocket-key"];
  if (!TOKENS.has(url.searchParams.get("token") ?? "")) {
    sock.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    return;
  }
  if (!key || String(req.headers.upgrade).toLowerCase() !== "websocket") {
    sock.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    return;
  }
  const accept = crypto.createHash("sha1").update(key + GUID).digest("base64");
  sock.write(
    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  sock.setNoDelay(true);
  clients.add(sock);
  sock.on("close", () => clients.delete(sock));
  sock.on("error", () => clients.delete(sock));
  attach(sock, (text) => handleFrame(sock, text));
});

// ---- ops -------------------------------------------------------------------------------------

class OpError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function needBot(p) {
  if (typeof p.bot !== "string" || !p.bot) throw new OpError("bad_request", "missing bot");
  const b = bots[p.bot];
  if (!b) throw new OpError("unknown_bot", `no bot named ${p.bot}`);
  if (b.status === "offline") throw new OpError("bot_offline", `${p.bot} is offline`);
  return b;
}
function needFolder(p, b) {
  const f = typeof p.session === "string" ? folders.get(p.session) : undefined;
  if (!f || !f.open || f.bot !== b.name) throw new OpError("not_found", "no such folder chat");
  return f;
}
// A folder chat's scripted turn runs under its own key; its events go out as the bot's, tagged `session`.
const folderTurnKey = (bot, session) => `${bot}\u0000${session}`;
function needStr(p, k) {
  if (typeof p[k] !== "string" || !p[k]) throw new OpError("bad_request", `missing ${k}`);
  return p[k];
}

const awayFor = (bot) =>
  (AWAY_SEED[bot] ?? [])
    .map((a) => ({
      id: a.id,
      source: a.source,
      label: a.title || `${a.source[0].toUpperCase()}${a.source.slice(1)} session`,
      title: a.title,
      started_at: now() - a.started,
      last_active: now() - a.last,
      message_count: a.count,
      running: a.running,
      url: a.url ?? null,
      place: a.place ?? null,
      last_reply: a.reply ?? null,
      last_reply_at: a.reply ? now() - a.last : null,
      reply_target: a.target ?? null,
    }))
    .sort((x, y) => y.last_active - x.last_active)
    .slice(0, 20);

const OPS = {
  hello: () => ({ bridge: "mock", version: "0.1.0", hermes: { home: "/mock/.hermes", version: "mock" } }),
  "bots.list": () => ({ bots: Object.values(bots).map(publicBot) }),
  "chat.open": (p) => {
    const b = needBot(p);
    const m = models[b.name];
    // asks still waiting on the person go out again after the reply (the bridge's replay)
    const waiting = [...pending.keys()].map((id) => asked.get(id)).filter((e) => e && e.bot === b.name && !e.session);
    if (waiting.length) setTimeout(() => waiting.forEach(broadcast), 0);
    return {
      session_id: `main-${b.name}`,
      messages: history[b.name],
      running: Boolean(turns[b.name]),
      model: m.model,
      provider: m.provider,
      reasoning: m.reasoning,
    };
  },
  "folder.open": (p) => {
    const b = needBot(p);
    const cwd = needStr(p, "cwd");
    if (!cwd.startsWith("/") && !/^[A-Za-z]:\\/.test(cwd)) throw new OpError("bad_request", "cwd must be an existing folder");
    const session = nextId("f");
    folders.set(session, { bot: b.name, cwd, open: true });
    const m = models[b.name];
    return { session, cwd, model: m.model, provider: m.provider, reasoning: m.reasoning };
  },
  "folder.close": (p) => {
    needBot(p);
    const f = folders.get(p.session);
    if (!f || !f.open) throw new OpError("not_found", "no such folder chat");
    f.open = false;
    const key = folderTurnKey(f.bot, p.session);
    if (turns[key]) endTurn(key, "interrupted", { drop: true });
    return {};
  },
  "chat.send": (p) => {
    const b = needBot(p);
    const text = needStr(p, "text");
    // Same as the real bridge: a reply_to session adds one context block for the bot. Nothing is posted.
    let submitted = text;
    let reply_to = null;
    if (p.reply_to !== undefined) {
      if (typeof p.reply_to !== "string" || !p.reply_to) throw new OpError("bad_request", "reply_to must be a session id");
      const seed = (AWAY_SEED[b.name] ?? []).find((a) => a.id === p.reply_to);
      if (!seed?.target) throw new OpError("bad_request", "that session has no thread to reply in");
      const label = seed.place || seed.source;
      const kind = seed.target.split(":").length >= 3 ? "thread" : "channel";
      reply_to = { target: seed.target, label };
      submitted =
        `${text.trimEnd()}\n\n[omher] Reply target: ${seed.target} (${kind} "${label}"). Post there only if the user asked; ` +
        `use your own messaging tool or \`hermes send --to ${seed.target}\`.`;
    }
    submits.push({ bot: b.name, session_id: `main-${b.name}`, text: submitted });
    const input_id = nextId("input");
    if (p.session !== undefined) {
      const f = needFolder(p, b);
      const key = folderTurnKey(b.name, p.session);
      if (turns[key]) throw new OpError("busy", "a turn is running");
      startTurn(key, text, f);
      return { input_id };
    }
    history[b.name].push({ id: nextId("u"), role: "user", text, ts: now(), ...(reply_to ? { reply_to } : {}) });
    if (turns[b.name]) (queues[b.name] ??= []).push(text);
    else startTurn(b.name, text);
    return { input_id };
  },
  "chat.interrupt": (p) => {
    const b = needBot(p);
    if (p.session !== undefined) {
      needFolder(p, b);
      const key = folderTurnKey(b.name, p.session);
      if (turns[key]) endTurn(key, "interrupted", { drop: true });
      return {};
    }
    if (turns[b.name]) endTurn(b.name, "interrupted", { drop: true });
    return {};
  },
  "approval.respond": (p) => {
    const b = needBot(p);
    const id = needStr(p, "request_id");
    const choice = needStr(p, "choice");
    if (!["once", "session", "always", "deny"].includes(choice)) throw new OpError("bad_request", "bad choice");
    const target = p.session !== undefined ? (needFolder(p, b), folderTurnKey(b.name, p.session)) : b.name;
    const wait = pending.get(id);
    if (!wait || wait.bot !== target || wait.kind !== "approval") throw new OpError("not_found", `no pending approval ${id}`);
    pending.delete(id);
    clearTimeout(wait.timer);
    resumeApproval(target, choice);
    return {};
  },
  "clarify.respond": (p) => {
    const b = needBot(p);
    const id = needStr(p, "request_id");
    const answers = p.answers;
    if (answers !== undefined) {
      if (!answers || typeof answers !== "object" || Array.isArray(answers) ||
          !Object.values(answers).every((v) => v === null || typeof v === "string"))
        throw new OpError("bad_request", "answers must map question ids to text or null");
    } else if (typeof p.answer !== "string") throw new OpError("bad_request", "missing answer");
    const wait = pending.get(id);
    if (!wait || wait.bot !== b.name || wait.kind !== "clarify") throw new OpError("not_found", `no pending clarification ${id}`);
    pending.delete(id);
    clearTimeout(wait.timer);
    if (wait.qids) {
      const given = wait.qids.filter((q) => answers?.[q] != null).length;
      resumeClarify(b.name, `${given} of ${wait.qids.length} answers`);
    } else resumeClarify(b.name, p.answer ?? Object.values(answers).find((v) => v !== null) ?? "");
    return {};
  },
  "elsewhere.list": (p) => ({ sessions: awayFor(needBot(p).name) }),
  "elsewhere.peek": (p) => {
    const b = needBot(p);
    const sid = needStr(p, "session_id");
    const away = awayFor(b.name).find((a) => a.id === sid);
    if (!away) throw new OpError("not_found", `no session ${sid} for ${b.name}`);
    const limit = Number.isInteger(p.limit) && p.limit > 0 ? p.limit : 4;
    const rows = (PEEK_SEED[sid] ?? []).map(([role, author, text, ago]) => ({
      role,
      ...(author ? { author } : {}),
      text: text.slice(0, 400),
      ts: now() - ago,
    }));
    return { messages: rows.slice(-limit), total: Math.max(away.message_count, rows.length) };
  },
  "bots.rename": (p) => {
    const b = needBot(p);
    if (typeof p.name !== "string") throw new OpError("bad_request", "name must be text");
    const name = p.name.split(/\s+/).filter(Boolean).join(" ");
    if (name.length > 64) throw new OpError("bad_request", `name is too long (${name.length} characters, max 64)`);
    const seed = BOT_SEED.find((x) => x.name === b.name);
    b.display_name = name || (b.name === "default" ? "Hermes" : seed?.name[0].toUpperCase() + seed?.name.slice(1));
    broadcast({ event: "bots.update", bot: b.name });
    return { display_name: b.display_name };
  },
  "bots.avatar": (p) => {
    const a = avatars[needBot(p).name];
    return { rev: a?.rev ?? null, data: a?.data ?? null };
  },
  "bots.set_avatar": (p) => {
    const b = needBot(p);
    if (p.clear === true) delete avatars[b.name];
    else {
      if (typeof p.data !== "string" || !/^data:image\/(png|jpeg|webp);base64,/.test(p.data))
        throw new OpError("bad_request", "use a PNG, JPEG or WebP picture");
      if (p.data.length > 2_700_000) throw new OpError("bad_request", "picture is larger than 2 MB");
      avatars[b.name] = { rev: ++idSeq, data: p.data };
    }
    broadcast({ event: "bots.update", bot: b.name });
    return { avatar_rev: avatars[b.name]?.rev ?? null };
  },
  "bots.info": (p) => {
    const b = needBot(p);
    const i = INFO_SEED[b.name] ?? { places: {}, first: null, skills: 0 };
    return {
      places: { ...i.places },
      first_active: i.first === null ? null : now() - i.first,
      last_active: Object.keys(i.places).length ? now() - 20 : null,
      skills: i.skills,
      routines: (ROUTINE_SEED[b.name] ?? []).length,
    };
  },
  "skills.list": (p) => (needBot(p), { skills: SKILL_SEED.map((x) => ({ ...x })) }),
  "panel.terminal": (p) => ({
    runs: (PANEL_RUNS[needBot(p).name] ?? []).map(({ ago, ...r }) => ({ ...r, session_id: "s-" + r.id, ts: now() - ago })),
  }),
  "panel.worktrees": (p) => ({
    worktrees: (PANEL_TREES[needBot(p).name] ?? []).map(({ ago, ...w }) => ({ ...w, last: now() - ago })),
  }),
  "panel.diff": (p) => {
    const b = needBot(p);
    const w = (PANEL_TREES[b.name] ?? []).find((t) => t.path === p.path);
    if (!w) throw new OpError("not_found", "not a worktree this bot worked in");
    return { path: w.path, branch: w.branch, repo: w.repo, truncated: false, ...PANEL_DIFF[w.path] };
  },
  "media.read": (p) => {
    const b = needBot(p);
    const path = needStr(p, "path");
    const named = history[b.name].some((m) => m.role === "assistant" && mediaLines(m.text).includes(path));
    const name = path.split("/").pop();
    const file = join(MEDIA_DIR, name);
    let size;
    try {
      if (!named || !path.startsWith("/w/media/")) throw new Error("not named");
      size = statSync(file).size;
    } catch {
      throw new OpError("not_found", "not a file this bot sent");
    }
    const out = { path, name, mime: MEDIA_TYPES[name.split(".").pop()] ?? "application/octet-stream", size };
    if (p.info === true) return out;
    return { ...out, data_base64: readFileSync(file).toString("base64") };
  },
  // Stages a file for the next chat.send, like Hermes' image.attach_bytes / pdf.attach / file.attach.
  // A name starting with "fail" is refused, so the e2e can check that nothing is sent after a failed attach.
  "chat.attach": (p) => {
    needBot(p);
    const kind = needStr(p, "kind");
    const name = needStr(p, "name");
    const data = needStr(p, "data_base64");
    if (!["image", "pdf", "file"].includes(kind)) throw new OpError("bad_request", "need kind image|pdf|file");
    if (name.startsWith("fail")) throw new OpError("attach_failed", `unsupported ${kind}`);
    const bytes = Buffer.from(data, "base64").length;
    if (kind === "image") return { kind, name, text: `[User attached image: ${name}]`, ref_text: "", bytes };
    if (kind === "pdf") return { kind, name, text: `[User attached PDF: ${name} (1 page(s))]`, ref_text: "", bytes };
    return { kind, name, text: "", ref_text: `@file:.hermes/attachments/${name}`, bytes };
  },
  "runs.list": (p) => ({
    runs: (runs[needBot(p).name] ?? [])
      .map(({ nodes, ...r }) => ({ ...r, counts: runCounts({ nodes }) }))
      .sort((a, b) => Number(b.state === "running") - Number(a.state === "running") || b.updated - a.updated),
  }),
  "runs.cli": (p) => {
    const AGENTS = ["claude", "codex", "pi", "omp", "grok"];
    if (p.agent !== undefined && !AGENTS.includes(p.agent)) throw new OpError("bad_request", `agent must be one of ${AGENTS.join(", ")}`);
    if (p.cwd !== undefined && (typeof p.cwd !== "string" || !p.cwd)) throw new OpError("bad_request", "cwd must be a folder path");
    if (p.since !== undefined && typeof p.since !== "number") throw new OpError("bad_request", "since must be epoch seconds");
    return {
      runs: cliRuns
        .filter((r) => (p.agent === undefined || r.agent === p.agent) && (p.cwd === undefined || r.cwd === p.cwd) && r.started >= (p.since ?? 0))
        .map(({ nodes, ...r }) => ({ ...r, counts: runCounts({ nodes }) }))
        .sort((a, b) => Number(b.state === "running") - Number(a.state === "running") || b.updated - a.updated),
      agents: CLI_FIXTURE.agents,
    };
  },
  // the GitHub state of each PR the run's nodes name (the real bridge asks `gh`): the demo's from DEMO_PRS, any
  // other `unknown` (no gh); a PR with no repo is never asked
  "runs.prs": (p) => {
    const b = needBot(p);
    const id = needStr(p, "run");
    if (cliRuns.some((r) => r.id === id)) return { prs: {} };
    const run = (runs[b.name] ?? []).find((r) => r.id === id);
    if (!run) throw new OpError("not_found", `no run ${id} for ${b.name}`);
    const prs = {};
    for (const n of run.nodes) {
      if (!n.pr) continue;
      const known = n.pr.repo === DEMO_REPO ? DEMO_PRS[n.pr.number] : undefined;
      prs[n.id] = { ...n.pr, state: known?.state ?? "unknown" };
    }
    return { prs };
  },
  "runs.get": (p) => {
    const b = needBot(p);
    const id = needStr(p, "run");
    const cli = cliRuns.find((r) => r.id === id);
    if (cli) return { run: cli, handoffs: {} };
    const run = (runs[b.name] ?? []).find((r) => r.id === id);
    if (!run) throw new OpError("not_found", `no run ${id} for ${b.name}`);
    return { run, handoffs: HANDOFFS[id] ?? {} };
  },
  "routines.list": (p) => ({
    routines: (ROUTINE_SEED[needBot(p).name] ?? []).map((r) => ({
      id: r.id,
      name: r.name,
      schedule: r.schedule,
      next_run_at: now() + r.next,
      last_run_at: now() + r.last,
      last_status: r.status,
      enabled: r.enabled,
    })),
  }),
  "models.options": (p) => {
    const b = needBot(p);
    return { providers: PROVIDERS, current: { ...models[b.name] }, reasoning_levels: REASONING_LEVELS };
  },
  "chat.set_model": (p) => {
    const b = needBot(p);
    if (p.session !== undefined) {
      needFolder(p, b); // a folder chat's model changes for that chat only
      if (typeof p.model !== "string") throw new OpError("bad_request", "need model");
      return { model: p.model, provider: p.provider ?? models[b.name].provider, reasoning: models[b.name].reasoning };
    }
    const cur = models[b.name];
    if (p.provider !== undefined && !PROVIDERS.some((x) => x.slug === p.provider)) throw new OpError("bad_request", `unknown provider ${p.provider}`);
    if (p.reasoning !== undefined && !REASONING_LEVELS.includes(p.reasoning)) throw new OpError("bad_request", `unknown reasoning level ${p.reasoning}`);
    if (p.model !== undefined && typeof p.model !== "string") throw new OpError("bad_request", "model must be a string");
    models[b.name] = {
      model: p.model ?? cur.model,
      provider: p.provider ?? cur.provider,
      reasoning: p.reasoning ?? cur.reasoning,
    };
    return { ...models[b.name] };
  },
  "usage.read": () => ({ providers: USAGE[usageFixture]() }),
  "accounts.list": () => accountsList(),
  "accounts.add": (p) => {
    if (!ACCT_CLIS.includes(p.cli)) throw new OpError("bad_request", "unknown cli");
    const label = String(p.label ?? "").trim().slice(0, 40);
    const list = acct[p.cli];
    let id = label.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "");
    if (!id || id === "default") {
      let n = 2;
      while (list.some((a) => a.id === `account-${n}`)) n += 1;
      id = `account-${n}`;
    }
    if (list.some((a) => a.id === id)) throw new OpError("exists", `an account named ${id} already exists`);
    list.push({ id, label, logged_in: false });
    acct[p.cli] = [list[0], ...list.slice(1).sort((a, b) => a.id.localeCompare(b.id))];
    acctUpdate();
    return { id, dir: `/mock/.omher/accounts/${p.cli}/${id}` };
  },
  "accounts.set_active": (p) => {
    acctFind(p);
    acctActive[p.cli] = p.account;
    acctUpdate();
    return {};
  },
  "accounts.label": (p) => {
    const a = acctFind(p);
    const label = String(p.label ?? "").trim().slice(0, 40);
    if (a.id === "default") acctLabels[p.cli] = label;
    else a.label = label;
    acctUpdate();
    return {};
  },
  "accounts.remove": (p) => {
    const a = acctFind(p);
    if (a.id === "default") throw new OpError("bad_request", "bad account id");
    acct[p.cli] = acct[p.cli].filter((x) => x !== a);
    if (acctActive[p.cli] === a.id) acctActive[p.cli] = "default";
    acctUpdate();
    return {};
  },
  "accounts.discard": (p) => {
    const a = acctFind(p);
    if (a.id === "default") throw new OpError("bad_request", "bad account id");
    if (a.logged_in) throw new OpError("signed_in", "this account is signed in; remove it from its menu");
    acct[p.cli] = acct[p.cli].filter((x) => x !== a);
    acctUpdate();
    return {};
  },
  // ---- test control (not part of the protocol)
  "mock.usage": (p) => {
    if (!(p.fixture in USAGE)) throw new OpError("bad_request", "unknown usage fixture");
    usageFixture = p.fixture;
    return {};
  },
  "mock.accounts": (p) => {
    const cli = typeof p.cli === "string" ? p.cli : "codex";
    if (typeof p.limit === "string") acctLimited[`${cli}:${p.limit}`] = now() + 2 * 3600;
    if (p.signed_in && typeof p.signed_in === "object") {
      const a = acct[cli]?.find((x) => x.id === p.signed_in.id);
      if (a) Object.assign(a, { logged_in: true, email: p.signed_in.email ?? "" });
    }
    broadcast({ event: "accounts.update", bot: "" });
    return {};
  },
  "mock.calls": () => ({ calls: calls.map((c) => ({ ...c })) }),
  "mock.submits": () => ({ submits: submits.map((x) => ({ ...x })) }),
  "mock.emit": (p) => {
    if (!Array.isArray(p.events)) throw new OpError("bad_request", "events must be an array");
    for (const ev of p.events) broadcast(ev);
    return { count: p.events.length };
  },
  "mock.reset": () => {
    reset();
    return {};
  },
  "mock.demo": () => {
    seedDemo();
    return { run: DEMO_RUN };
  },
  // a bot whose main chat has no messages yet (first run)
  "mock.clearHistory": (p) => {
    history[needBot(p).name] = [];
    return {};
  },
  "mock.ask": (p) => {
    const b = needBot(p);
    const kind = p.kind ?? "approval";
    if (!["approval", "clarify", "interview"].includes(kind)) throw new OpError("bad_request", "kind is approval, clarify or interview");
    if (turns[b.name]) throw new OpError("bad_request", `${b.name} is busy`);
    turns[b.name] = { timers: [], text: `(${kind})` };
    bots[b.name].running = true;
    ev(b.name, "bot.status", { status: bots[b.name].status, running: true });
    ev(b.name, "turn.start");
    const timeout = Number.isInteger(p.timeout_ms) && p.timeout_ms > 0 ? p.timeout_ms : 0;
    const request_id = kind === "approval" ? raiseApproval(b.name, timeout) : kind === "clarify" ? raiseClarify(b.name, timeout) : raiseInterview(b.name, timeout);
    return { request_id };
  },
};

function handleFrame(sock, text) {
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    sendJson(sock, { id: null, ok: false, error: { code: "bad_request", message: "frame is not JSON" } });
    return;
  }
  const id = msg && typeof msg === "object" && typeof msg.id === "string" ? msg.id : null;
  if (!id || typeof msg.op !== "string") {
    sendJson(sock, { id, ok: false, error: { code: "bad_request", message: "need string id and op" } });
    return;
  }
  const { id: _id, op, ...params } = msg;
  if (!op.startsWith("mock.")) calls.push({ op, params, ts: now() });
  try {
    const fn = Object.hasOwn(OPS, op) ? OPS[op] : null;
    if (!fn) throw new OpError("unknown_op", `no such op: ${op}`);
    sendJson(sock, { id, ok: true, result: fn(params) });
  } catch (e) {
    const code = e instanceof OpError ? e.code : "internal";
    sendJson(sock, { id, ok: false, error: { code, message: e?.message ?? String(e) } });
  }
}

// ---- scripted turns --------------------------------------------------------------------------

const ev = (bot, event, fields = {}) => {
  const [b, session] = bot.split("\u0000");
  if (session !== undefined && event === "bot.status") return; // a folder chat never moves the bot's status
  const out = session !== undefined ? { event, bot: b, session, ...fields } : { event, bot, ...fields };
  if (event === "approval.request" || event === "clarify.request") asked.set(fields.request_id, out);
  broadcast(out);
};
const hangul = /[\u3131-\u318e\uac00-\ud7a3]/;

function schedule(bot, steps) {
  const t = turns[bot];
  for (const [ms, fn] of steps) {
    const h = setTimeout(() => {
      if (turns[bot] === t) fn();
    }, ms);
    t.timers.push(h);
  }
}

function endTurn(bot, outcome, { drop = false } = {}) {
  const t = turns[bot];
  if (!t) return;
  t.timers.forEach(clearTimeout);
  for (const [id, w] of pending) if (w.bot === bot) pending.delete(id);
  delete turns[bot];
  if (bots[bot]) bots[bot].running = false;
  if (drop) queues[bot] = [];
  ev(bot, "turn.end", { outcome });
  ev(bot, "bot.status", { status: bots[bot]?.status, running: false });
  const next = queues[bot]?.shift();
  if (next !== undefined) setTimeout(() => startTurn(bot, next), 50);
}

function say(bot, text) {
  const id = nextId("a");
  if (history[bot]) history[bot].push({ id, role: "assistant", text, ts: now() });
  ev(bot, "message", { id, text });
}

function tool(bot, tool_id, name, detail, startMs, endMs, extra = []) {
  return [
    [startMs, () => { ev(bot, "tool.start", { tool_id, name, detail }); for (const e of extra) e(); }],
    [endMs, () => ev(bot, "tool.end", { tool_id, name, ok: true, ms: endMs - startMs })],
  ];
}

function startTurn(bot, text, folder) {
  turns[bot] = { timers: [], text };
  if (bots[bot]) bots[bot].running = true;
  ev(bot, "bot.status", { status: bots[bot]?.status, running: true });
  if (folder) {
    ev(bot, "turn.start");
    if (text.startsWith("/approve")) return scriptApproval(bot);
    return schedule(bot, [
      ...tool(bot, "f-tool-1", "terminal", `ls ${folder.cwd}`, 80, 300),
      [360, () => say(bot, `(mock oh-my-hermes) Working in ${folder.cwd}: ${text}`)],
      [460, () => endTurn(bot, "done")],
    ]);
  }
  ev(bot, "turn.start");
  if (text.startsWith("/approve")) return scriptApproval(bot);
  if (text.startsWith("/clarify")) return scriptClarify(bot);
  if (text.startsWith("/interview")) return schedule(bot, [[150, () => raiseInterview(bot, 0)]]);
  if (text.startsWith("/delegate")) return scriptDelegate(bot);
  scriptNormal(bot, text);
}

function scriptNormal(bot, text) {
  const ko = hangul.test(text);
  const answer = ko
    ? `확인했어요. 로그에서 \`/v1/responses\` 502는 keep-alive 만료 때문이었고, 재시도 정책을 고쳤어요.\n\n- 원인: upstream 연결 재사용\n- 조치: idle timeout 상향`
    : `Done. The 502s on \`/v1/responses\` came from expired keep-alive connections.\n\n- Cause: upstream connection reuse\n- Fix: raised the idle timeout`;
  const parts = [answer.slice(0, 40), answer.slice(40, 90), answer.slice(90)];
  schedule(bot, [
    [80, () => ev(bot, "status", { text: "Looking into it…" })],
    [200, () => ev(bot, "thinking")],
    ...tool(bot, "tool-1", "terminal", "git log --oneline -5", 350, 700),
    ...tool(bot, "tool-2", "skill_view", "plan", 750, 950, [() => ev(bot, "skill", { name: "plan" })]),
    ...tool(bot, "tool-3", "read_file", "src/gateway/router.py", 1000, 1350),
    ...tool(bot, "tool-4", "search_files", "502 upstream", 1400, 1850),
    [1900, () => ev(bot, "thinking")],
    [2000, () => ev(bot, "delta", { text: parts[0] })],
    [2150, () => ev(bot, "delta", { text: parts[1] })],
    [2300, () => ev(bot, "delta", { text: parts[2] })],
    [2400, () => say(bot, answer)],
    [2500, () => endTurn(bot, "done")],
  ]);
}

// A delegate_task that hands out two parts of the codex-coexist dag run (one returns, one keeps working).
function scriptDelegate(bot) {
  const dag = [
    { run: "codex-coexist-live", node: "t3-doctor" },
    { run: "codex-coexist-live", node: "t5-verify" },
  ];
  schedule(bot, [
    [80, () => ev(bot, "tool.start", { tool_id: "d1", name: "delegate_task", detail: "Doctor check for the Codex pack (+1 more)", dag })],
    [400, () => ev(bot, "tool.end", { tool_id: "d1", name: "delegate_task", ok: true, ms: 320 })],
    [500, () => say(bot, "Both helpers are on it.")],
    [600, () => endTurn(bot, "done")],
  ]);
}

function scriptApproval(bot) {
  const request_id = nextId("approval");
  schedule(bot, [
    [100, () => ev(bot, "status", { text: "Preparing to clean the build folder…" })],
    [300, () => {
      pending.set(request_id, { bot, kind: "approval" });
      ev(bot, "approval.request", {
        request_id,
        title: "Run shell command",
        command: "rm -rf ./build",
        choices: ["once", "session", "always", "deny"],
      });
    }],
  ]);
}

function resumeApproval(bot, choice) {
  if (choice === "deny") return endTurn(bot, "interrupted");
  schedule(bot, [
    ...tool(bot, "tool-a1", "terminal", "rm -rf ./build", 100, 500),
    [600, () => say(bot, `Cleaned the build folder (approved: ${choice}).`)],
    [700, () => endTurn(bot, "done")],
  ]);
}

function scriptClarify(bot) {
  const request_id = nextId("clarify");
  schedule(bot, [
    [100, () => ev(bot, "status", { text: "Checking what you meant…" })],
    [250, () => {
      pending.set(request_id, { bot, kind: "clarify" });
      ev(bot, "clarify.request", { request_id, question: "Which environment should I deploy to?", choices: ["staging", "production"] });
    }],
  ]);
}

// An ask the gateway gives up on: after `timeout` ms it stops waiting (prompt.expired) and the turn goes on.
function expireLater(bot, request_id, timeout) {
  if (!timeout) return undefined;
  const t = turns[bot];
  const h = setTimeout(() => {
    if (!pending.has(request_id) || turns[bot] !== t) return;
    pending.delete(request_id);
    ev(bot, "prompt.expired", { request_id, reason: "timeout" });
    say(bot, "No answer, so I left it as it was.");
    endTurn(bot, "done");
  }, timeout);
  t.timers.push(h);
  return h;
}

function raiseApproval(bot, timeout) {
  const request_id = nextId("approval");
  pending.set(request_id, { bot, kind: "approval", timer: expireLater(bot, request_id, timeout) });
  ev(bot, "status", { text: "Preparing to clean the build folder…" });
  ev(bot, "approval.request", {
    request_id,
    title: "Run shell command",
    command: "rm -rf build/",
    choices: ["once", "session", "always", "deny"],
    ...(timeout ? { timeout_s: timeout / 1000 } : {}),
  });
  return request_id;
}

function raiseClarify(bot, timeout) {
  const request_id = nextId("clarify");
  pending.set(request_id, { bot, kind: "clarify", timer: expireLater(bot, request_id, timeout) });
  ev(bot, "clarify.request", {
    request_id,
    question: "Which environment should I deploy to?",
    choices: ["staging", "production"],
    ...(timeout ? { timeout_s: timeout / 1000 } : {}),
  });
  return request_id;
}

// Hermes' clarify tool asking several questions at once: one interview card.
const INTERVIEW = [
  { qid: "q1", question: "Who is the release note for?", choices: ["Users", "Developers", "Both"] },
  { qid: "q2", question: "Which sections should it have?", choices: ["Highlights", "Fixes", "Breaking changes", "Thanks"], multi_select: true },
  { qid: "q3", question: "Anything to leave out?" },
];
function raiseInterview(bot, timeout) {
  const request_id = nextId("interview");
  pending.set(request_id, { bot, kind: "clarify", qids: INTERVIEW.map((q) => q.qid), timer: expireLater(bot, request_id, timeout) });
  ev(bot, "status", { text: "Planning the release note…" });
  ev(bot, "clarify.request", {
    request_id,
    question: INTERVIEW[0].question,
    questions: INTERVIEW,
    ...(timeout ? { timeout_s: timeout / 1000 } : {}),
  });
  return request_id;
}

function resumeClarify(bot, answer) {
  schedule(bot, [
    [100, () => say(bot, `Got it, using ${answer}.`)],
    [200, () => endTurn(bot, "done")],
  ]);
}

// ---- boot ------------------------------------------------------------------------------------

server.listen(PORT, "127.0.0.1", () => {
  console.log(`MOCK_READY ${server.address().port}`);
});
const stop = () => {
  for (const c of clients) c.destroy();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 500).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
