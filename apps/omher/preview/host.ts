// The preview's bridge: the same ops the Python bridge answers (src/lib/protocol.ts), served inside the page from
// a staged morning (the bots Kami, Friren, Juno and Pip; neutral project names). Nothing here talks to a network,
// a Hermes profile or an agent: `FakeSocket` stands in for the WebSocket the app opens, and every answer comes
// from the data below. Turns are played by the story (story.ts) or by `reply()` when the visitor types.
import docsLight from "./media/docs-light.webp?inline";
import docsDark from "./media/docs-dark.webp?inline";

type Json = Record<string, unknown>;
const MIN = 60;
export const nowS = () => Date.now() / 1000;

// ---- staged data --------------------------------------------------------------------------------------------

export const BOTS = [
  { name: "kami", display_name: "Kami", is_default: false, model: "Opus 5.5", provider: "claude-proxy", description: "team lead", status: "online", running: false },
  { name: "friren", display_name: "Friren", is_default: false, model: "Sonnet 5.5", provider: "claude-proxy", description: "research", status: "online", running: false },
  { name: "juno-bot", display_name: "Juno", is_default: false, model: "gpt-6.1-sol", provider: "openai", description: "releases", status: "online", running: false },
  { name: "pip", display_name: "Pip", is_default: false, model: "Haiku 4.5", provider: "claude-proxy", description: "notes", status: "online", running: false },
];
const REASONING: Record<string, string> = { kami: "high", friren: "medium", "juno-bot": "medium", pip: "low" };

type Row = { id: string; role: "user" | "assistant"; text: string; ts: number };
const seed = (bot: string, rows: [Row["role"], string, number][]): Row[] =>
  rows.map(([role, text, ago], i) => ({ id: `seed-${bot}-${i}`, role, text, ts: nowS() - ago }));

export function kamiSeed(): Row[] {
  return seed("kami", [
    ["user", "Did the search filters land last night?", 15 * 3600],
    ["assistant", "Yes: **PR #121** is merged. Tag and date filters are live on the docs, and 38 search tests pass.", 15 * 3600 - 60],
    ["user", "Morning! What needs me today?", 62 * MIN],
    ["assistant", "Three things today:\n\n1. **Review** the rate-limit PR in api-server (#126).\n2. **Answer** Mina in #design about the docs theme.\n3. **Approve** Juno's deploy once the tests pass.", 61 * MIN],
    ["user", "Review #126 and merge it if it's clean.", 24 * MIN],
    ["assistant", "Reviewed **#126**: fixed two nits, CI is green. Merged into main, and Juno's deploy picks it up.", 21 * MIN],
    ["user", "Can the docs get a dark mode today? Mina keeps asking.", 3 * MIN],
    ["assistant", "Yes. It's color tokens, a theme toggle, a contrast check, code colors and the page styles, then a final check and the PR. Say the word and I'll plan it.", 2.5 * MIN],
  ]);
}

export const history: Record<string, Row[]> = {
  kami: kamiSeed(),
  friren: seed("friren", [
    ["user", "Read the Tauri 2.4 release notes for me.", 50 * MIN],
    ["assistant", "The updater got delta downloads; I'll write it up.", 48 * MIN],
  ]),
  "juno-bot": seed("juno-bot", [
    ["user", "What's in today's api-server release?", 70 * MIN],
    ["assistant", "Three changes: the **rate limits** from #126, a faster `/search` index, and the Go 1.26 bump. No migrations.", 69 * MIN],
    ["user", "Deploy api-server when the tests pass.", 40 * MIN],
    ["assistant", "On it. I'll wait for CI on main and ping you before anything goes out.", 39 * MIN],
    ["assistant", "Tests are green: **214 passed**, 0 failed. Ready to deploy.", 2 * MIN],
  ]),
  pip: seed("pip", [
    ["user", "File today's standup notes.", 3 * 3600],
    ["assistant", "Filed under Notes / Standups.", 160 * MIN],
  ]),
};

type AwaySeed = { id: string; source: string; title: string; place: string | null; url: string | null; target: string | null; reply: string; startedAt: number; lastAt: number; count: number; running?: boolean };
export const away: Record<string, AwaySeed[]> = {
  kami: [],
  friren: [],
  "juno-bot": [
    { id: "slack-releases-juno", source: "slack", title: "release train", place: "#releases", url: "slack://channel?team=T1&id=C3", target: "slack:C03RELEASES:1794200000.000200", reply: "api-server 2.4 is queued behind the tests. I'll post here when it's live.", startedAt: nowS() - 90 * MIN, lastAt: nowS() - 30 * MIN, count: 5 },
    { id: "discord-ops-juno", source: "discord", title: "on-call", place: "#ops", url: "https://discord.com/channels/1/12", target: "discord:900000000000000012", reply: "Staging p95 is back to 84 ms after the cache fix.", startedAt: nowS() - 5 * 3600, lastAt: nowS() - 3 * 3600, count: 9 },
    { id: "cron-juno-nightly", source: "cron", title: "nightly smoke test", place: null, url: null, target: null, reply: "Nightly smoke test passed: 61 of 61.", startedAt: nowS() - 9 * 3600, lastAt: nowS() - 9 * 3600 + 300, count: 2 },
  ],
  pip: [],
};

const ROUTINES: Record<string, Json[]> = {
  kami: [{ id: "cron-digest", name: "Morning digest", schedule: "Daily 09:00", next: 15 * 3600, last: -9 * 3600 }],
  "juno-bot": [
    { id: "cron-deploy-check", name: "Post-deploy health check", schedule: "After each deploy", next: 20 * MIN, last: -22 * 3600 },
    { id: "cron-release-notes", name: "Release notes draft", schedule: "Daily 17:00", next: 8 * 3600, last: -16 * 3600 },
    { id: "cron-dep-audit", name: "Dependency audit", schedule: "Mondays 09:00", next: 6 * 86400, last: -86400 },
  ],
};
const INFO: Record<string, Json> = {
  kami: { places: { slack: 41, discord: 12, cron: 6 }, first: 30 * 86400, skills: 120 },
  friren: { places: { telegram: 6 }, first: 9 * 86400, skills: 14 },
  "juno-bot": { places: { slack: 9, discord: 4 }, first: 5 * 86400, skills: 20 },
  pip: { places: { telegram: 3 }, first: 12 * 86400, skills: 9 },
};
const SKILLS = [
  { name: "dag-ulw", description: "Plan big work as parts that run in parallel, each checked before it counts." },
  { name: "plan", description: "Break the work into steps and agree on them before doing it." },
  { name: "research", description: "Find sources, read them and answer with citations." },
  { name: "review", description: "Review a diff for correctness, tests and risk, worst first." },
];
const PROVIDERS = [
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5", "Sonnet 5.5", "Haiku 4.5"] },
  { slug: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6.1-sol-mini"] },
  { slug: "openrouter", name: "OpenRouter", models: ["google/gemini-3-pro", "deepseek/deepseek-v4.1", "x-ai/grok-4.7", "qwen/qwen3-coder"] },
];
const models: Record<string, Json> = Object.fromEntries(BOTS.map((b) => [b.name, { model: b.model, provider: b.provider, reasoning: REASONING[b.name] }]));

// Plans: past ones are fixed; the story writes the live one (`setLiveRun`) and its handoff text.
export const runs: { live: Json | null; past: Json[]; handoffs: Record<string, Record<string, string>> } = { live: null, past: [], handoffs: {} };
function pastRun(id: string, title: string, goal: string, ago: number, dur: number, spec: [string, number[], string, string, string, string?][]): Json {
  const t = nowS();
  const nodes = spec.map(([label, deps, model, effort, route, executor], i) => {
    const s0 = t - ago - dur + i * 90, s1 = s0 + 240 + i * 50;
    return { id: `p${i}`, label, deps: deps.map((d) => `p${d}`), layer: 0, state: "done", model, effort, route, ...(executor ? { executor } : {}), started: s0, ended: s1, attempts: [{ n: 1, outcome: "accepted", started: s0, ended: s1 }] };
  });
  return { id, kind: "dag", owner: { type: "bot", id: "kami" }, title, goal, state: "done", started: t - ago - dur, ended: t - ago, updated: t - ago, nodes };
}
runs.past = [
  pastRun("dag:20261109_160200_aa11bb22/search-filters", "Search filters", "Add tag and date filters to docs search.", 17 * 3600, 34 * MIN, [
    ["Filter index", [], "gpt-6.1-sol", "medium", "quick", "codex"],
    ["Filter chips UI", [], "Opus 5.5", "high", "visual-engineering"],
    ["Query parser", [0, 1], "Kimi K3", "high", "deep"],
    ["Search tests", [0, 1], "DeepSeek V4.1", "medium", "quick"],
    ["Review and PR", [2, 3], "Opus 5.5", "high", "review"],
  ]),
  pastRun("dag:20261108_101500_cc33dd44/api-rate-limit", "API rate limits", "Rate-limit the public API per key.", 2 * 86400, 22 * MIN, [
    ["Token bucket", [], "GLM-5.3", "high", "deep"],
    ["Limit headers", [], "gpt-6.1-sol", "medium", "quick", "codex"],
    ["Load test", [0, 1], "DeepSeek V4.1", "high", "review"],
    ["Review and PR", [2], "Opus 5.5", "high", "review"],
  ]),
];
runs.handoffs["dag:20261109_160200_aa11bb22/search-filters"] = {
  p4: "- Merged #121: tag and date filters on docs search\n- 38 search tests pass; p95 query time 41 ms\n- Filter chips keep the URL in sync",
};

const counts = (nodes: Json[]) => ({
  nodes: nodes.length,
  done: nodes.filter((n) => n.state === "done").length,
  running: nodes.filter((n) => n.state === "running").length,
  failed: nodes.filter((n) => n.state === "failed").length,
});
const allRuns = () => [...(runs.live ? [runs.live] : []), ...runs.past];
/** GitHub's state of the PRs the live plan's parts opened (the real bridge asks `gh`; staged here). */
export const PR_REPO = "rlaope/oh-my-hermes";
export const PR_STATES: Record<number, string> = { 2353: "merged", 2352: "merged", 2359: "open", 2360: "draft" };

// ---- media: the before/after the story's last message names ----------------------------------------------------

const MEDIA: Record<string, string> = { "/w/media/docs-light.webp": docsLight, "/w/media/docs-dark.webp": docsDark };

// ---- ops ----------------------------------------------------------------------------------------------------

class OpError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}
const need = (p: Json) => {
  const b = BOTS.find((x) => x.name === p.bot);
  if (!b) throw new OpError("unknown_bot", `no bot named ${String(p.bot)}`);
  return b;
};
const awayRows = (bot: string) =>
  (away[bot] ?? [])
    .map((a) => ({
      id: a.id, source: a.source, label: a.title, title: a.title, started_at: a.startedAt, last_active: a.lastAt,
      message_count: a.count, running: !!a.running, url: a.url, place: a.place, last_reply: a.reply, last_reply_at: a.lastAt, reply_target: a.target,
    }))
    .sort((x, y) => y.last_active - x.last_active);

/** Hooks the story fills in: what a visitor's message or approval sets off. */
export const hooks: {
  send: (bot: string, text: string) => void;
  approve: (bot: string, requestId: string, choice: string) => void;
  clarify: (bot: string, requestId: string) => void;
  interrupt: (bot: string) => void;
} = { send: () => {}, approve: () => {}, clarify: () => {}, interrupt: () => {} };

const OPS: Record<string, (p: Json) => unknown> = {
  hello: () => ({ bridge: "mock", version: "preview", hermes: { home: "(preview: staged data)", version: "preview" } }),
  "bots.list": () => ({ bots: BOTS.map((b) => ({ ...b, ...(models[b.name] as object), avatar_rev: null })) }),
  "chat.open": (p) => {
    const b = need(p);
    const m = models[b.name] as Json;
    return { session_id: `main-${b.name}`, messages: history[b.name], running: false, model: m.model, provider: m.provider, reasoning: m.reasoning };
  },
  "chat.send": (p) => {
    const b = need(p);
    const text = String(p.text ?? "").trim();
    if (!text) throw new OpError("bad_request", "missing text");
    history[b.name].push({ id: `u-${Math.random().toString(36).slice(2, 9)}`, role: "user", text, ts: nowS() });
    setTimeout(() => hooks.send(b.name, text), 0);
    return { input_id: "preview" };
  },
  "chat.interrupt": (p) => (hooks.interrupt(need(p).name), {}),
  "approval.respond": (p) => (hooks.approve(need(p).name, String(p.request_id), String(p.choice)), {}),
  "clarify.respond": (p) => (hooks.clarify(need(p).name, String(p.request_id)), {}),
  "elsewhere.list": (p) => ({ sessions: awayRows(need(p).name) }),
  "elsewhere.peek": (p) => ({ messages: [], total: (away[need(p).name] ?? []).find((a) => a.id === p.session_id)?.count ?? 0 }),
  "routines.list": (p) => ({
    routines: (ROUTINES[need(p).name] ?? []).map((r) => ({ id: r.id, name: r.name, schedule: r.schedule, next_run_at: nowS() + (r.next as number), last_run_at: nowS() + (r.last as number), last_status: "ok", enabled: true })),
  }),
  "models.options": (p) => ({ providers: PROVIDERS, current: { ...(models[need(p).name] as object) }, reasoning_levels: ["none", "low", "medium", "high", "xhigh"] }),
  "chat.set_model": (p) => {
    const b = need(p);
    const cur = models[b.name];
    models[b.name] = { model: p.model ?? cur.model, provider: p.provider ?? cur.provider, reasoning: p.reasoning ?? cur.reasoning };
    return { ...(models[b.name] as object) };
  },
  "bots.info": (p) => {
    const i = INFO[need(p).name] as { places: Json; first: number; skills: number };
    return { places: { ...i.places }, first_active: nowS() - i.first, last_active: nowS() - 20, skills: i.skills, routines: (ROUTINES[String(p.bot)] ?? []).length };
  },
  "bots.avatar": () => ({ rev: null, data: null }),
  "skills.list": (p) => (need(p), { skills: SKILLS }),
  "panel.terminal": () => ({ runs: [] }),
  "panel.worktrees": () => ({ worktrees: [] }),
  "panel.diff": () => {
    throw new OpError("not_found", "nothing to show in the preview");
  },
  "media.read": (p) => {
    const path = String(p.path ?? "");
    const url = MEDIA[path];
    if (!url) throw new OpError("not_found", "not a file this bot sent");
    const data = url.slice(url.indexOf(",") + 1);
    const out = { path, name: path.split("/").pop(), mime: "image/webp", size: Math.round((data.length * 3) / 4) };
    return p.info === true ? out : { ...out, data_base64: data };
  },
  "runs.list": (p) => ({ runs: need(p).name === "kami" ? allRuns().map(({ nodes, ...r }) => ({ ...r, counts: counts(nodes as Json[]) })) : [] }),
  "runs.get": (p) => {
    const run = allRuns().find((r) => r.id === p.run);
    if (!run) throw new OpError("not_found", "no such plan");
    return { run: structuredClone(run), handoffs: { ...(runs.handoffs[String(run.id)] ?? {}) } };
  },
  "runs.prs": (p) => {
    const run = allRuns().find((r) => r.id === p.run);
    if (!run) throw new OpError("not_found", "no such plan");
    const prs: Record<string, Json> = {};
    for (const n of run.nodes as Json[]) {
      const pr = n.pr as { number: number; repo?: string } | undefined;
      if (pr) prs[String(n.id)] = { ...pr, state: (pr.repo === PR_REPO && PR_STATES[pr.number]) || "unknown" };
    }
    return { prs };
  },
  "runs.cli": () => ({ runs: [], agents: { claude: "found", codex: "found", pi: "found", omp: "found", grok: "not_installed" } }),
  "usage.read": () => ({
    providers: [
      { id: "claude", plan: "max", state: "ok", source_mtime: nowS() - 60, windows: [{ label: "5 hours", used_percent: 46, resets_at: nowS() + 132 * MIN }, { label: "Weekly", used_percent: 31, resets_at: nowS() + 4 * 86400 }] },
      { id: "codex", plan: "pro", state: "ok", source_mtime: nowS() - 120, windows: [{ label: "5 hours", used_percent: 62, resets_at: nowS() + 107 * MIN }, { label: "Weekly", used_percent: 38, resets_at: nowS() + 5 * 86400 }] },
    ],
  }),
  "accounts.list": () => ({
    groups: ["claude", "codex", "pi", "omp", "grok", "gemini"].map((cli) => ({
      cli, installed: ["claude", "codex", "pi", "omp"].includes(cli), active: "default",
      accounts: [{ id: "default", label: "", email: cli === "claude" ? "you@example.com" : "", state: ["claude", "codex", "pi"].includes(cli) ? "active" : "login", dir: null, usage: null }],
    })),
  }),
};
// Writes the app can ask for: refused with a plain reason (nothing is stored anywhere).
for (const op of ["bots.rename", "bots.set_avatar", "chat.attach", "folder.open", "folder.close", "accounts.add", "accounts.set_active", "accounts.label", "accounts.remove", "accounts.discard"])
  OPS[op] = () => {
    throw new OpError("preview", "This is a preview: download omher to do this for real.");
  };

// ---- the stand-in socket --------------------------------------------------------------------------------------

const open = new Set<FakeSocket>();
/** An event to every connected client (the app's store and any short-lived second client). */
export function broadcast(ev: Json): void {
  const data = JSON.stringify(ev);
  for (const s of open) s.onmessage?.({ data } as MessageEvent);
}
export const calls: { op: string; at: number }[] = [];

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(public url: string) {
    setTimeout(() => {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      open.add(this);
      this.onopen?.(new Event("open"));
    }, 0);
  }
  send(raw: string): void {
    let msg: Json;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const { id, op, ...params } = msg as { id: string; op: string } & Json;
    calls.push({ op, at: Date.now() });
    let reply: Json;
    try {
      const fn = Object.hasOwn(OPS, op) ? OPS[op] : null;
      if (!fn) throw new OpError("unknown_op", `no such op: ${op}`);
      reply = { id, ok: true, result: fn(params) };
    } catch (e) {
      const err = e as OpError;
      reply = { id, ok: false, error: { code: err.code ?? "internal", message: err.message ?? String(e) } };
    }
    const data = JSON.stringify(reply);
    setTimeout(() => this.readyState === 1 && this.onmessage?.({ data } as MessageEvent), 0);
  }
  close(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    open.delete(this);
    setTimeout(() => this.onclose?.(new CloseEvent("close")), 0);
  }
  addEventListener(): void {}
  removeEventListener(): void {}
}
