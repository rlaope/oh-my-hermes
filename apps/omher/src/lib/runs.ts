// One model for every kind of agent run omher shows (dag-ulw runs now; delegate fan-outs, Claude Code
// tasks, Codex sub-runs and CLI sessions later). The Runs tab draws only this shape, so a new source is
// one adapter, never a new view. Read-only: nothing here retries, settles or cancels a run.

export type RunKind = "dag" | "delegate" | "claude-task" | "codex-sub" | "session";
export type RunState = "running" | "done" | "failed" | "cancelled";
export type NodeState = "waiting" | "running" | "done" | "failed" | "blocked" | "parked" | "cancelled";

export interface RunAttempt {
  n: number;
  /** The settled outcome as the source wrote it (`accepted`, `failed`, `retry`, …), or "open" while out. */
  outcome: string;
  reason?: string;
  started?: number; // seconds since epoch
  ended?: number;
  lane?: string;
  /** The model the helper of this attempt ran on (from its delegation log). */
  model?: string;
}

export interface RunNode {
  id: string;
  label: string;
  deps: string[];
  /** Column in the graph: the longest dependency path to this node (`layerOf`). */
  layer: number;
  state: NodeState;
  category?: string;
  model?: string;
  provider?: string;
  effort?: string;
  /** The routing category the node went out under (`omh_delegate_route` record, else the dag's category). */
  route?: string;
  /** How the router picked the model when it was not the plain choice ("chain head", "fallback from …"). */
  routeWhy?: string;
  /** For a repair node: the failed node it repairs (drawn as a link, laid out after it). */
  repairOf?: string;
  /** The helper's final summary or error (≤ 600 chars). */
  summary?: string;
  /** The dag's role for the node ("build", "verify", "plan"…). */
  role?: string;
  /** The agent CLI a fanout node went to (the owner in the run's `fanout-*-units.json`, e.g. "codex"). */
  executor?: string;
  /** For a node nobody has reported a model for yet: what its route resolves to now (OMH's route records). */
  planned?: { model: string; provider?: string; effort?: string };
  lane?: string;
  started?: number;
  ended?: number;
  tokens?: number;
  attempts: RunAttempt[];
  /** Handoff file name when the node wrote one (text comes from `runs.get`). */
  handoff?: string;
}

export interface AgentRun {
  id: string;
  kind: RunKind;
  owner: { type: "bot" | "session"; id: string };
  /** For a CLI agent's run (`runs.cli`): which CLI, and the folder its session ran in. */
  agent?: CliAgent;
  cwd?: string;
  title: string;
  goal?: string;
  state: RunState;
  nodes: RunNode[];
  started: number;
  ended?: number;
  updated: number;
}

export interface RunCounts {
  nodes: number;
  done: number;
  running: number;
  /** Open failures: failed + blocked, minus the ones their repairs fixed. */
  failed: number;
  /** Failures their repairs fixed (present only when there is one). */
  repaired?: number;
}

/** A run without its nodes, for the run list. */
export type AgentRunSummary = Omit<AgentRun, "nodes"> & { counts: RunCounts };

/** `runs.get`: the run plus each node's handoff text (at most 8000 chars). */
export interface RunDetail {
  run: AgentRun;
  handoffs: Record<string, string>;
}

/** Longest-path layer of each node from its deps; deps on ids not in `nodes` are ignored. A cycle throws. */
export function layerOf(nodes: Pick<RunNode, "id" | "deps">[]): Record<string, number> {
  const deps = new Map(nodes.map((n) => [n.id, n.deps]));
  const memo: Record<string, number> = {};
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    if (id in memo) return memo[id];
    if (visiting.has(id)) throw new Error(`cycle through ${id}`);
    visiting.add(id);
    let layer = 0;
    for (const d of deps.get(id) ?? []) if (deps.has(d)) layer = Math.max(layer, visit(d) + 1);
    visiting.delete(id);
    return (memo[id] = layer);
  };
  for (const n of nodes) visit(n.id);
  return memo;
}

export function countsOf(run: Pick<AgentRun, "nodes">): RunCounts {
  const c: RunCounts = { nodes: run.nodes.length, done: 0, running: 0, failed: 0 };
  let fixed = 0;
  for (const n of run.nodes) {
    if (n.state === "done") c.done++;
    else if (n.state === "running") c.running++;
    else if (n.state === "failed" || n.state === "blocked") {
      if (isRepaired(n, run.nodes)) fixed++;
      else c.failed++;
    }
  }
  if (fixed) c.repaired = fixed;
  return c;
}

/** "7 nodes · 3 done · 1 running · 1 failed" (zero parts left out). */
export function summary(run: Pick<AgentRun, "nodes"> | { counts: RunCounts }): string {
  const c = "counts" in run ? run.counts : countsOf(run);
  const parts = [`${c.nodes} node${c.nodes === 1 ? "" : "s"}`];
  if (c.done) parts.push(`${c.done} done`);
  if (c.running) parts.push(`${c.running} running`);
  if (c.failed) parts.push(`${c.failed} failed`);
  if (c.repaired) parts.push(`${c.repaired} repaired`);
  return parts.join(" · ");
}

// ---- dag adapter: one `omh_dag/v1` record -> AgentRun (the bridge's `dag_to_run` is the same mapping) ----

interface DagAttempt {
  n?: number;
  outcome?: string;
  reason?: string;
  lane?: string;
  handed_out_at?: number;
  settled_at?: number;
}
interface DagNode {
  id: string;
  label?: string;
  role?: string;
  depends_on?: string[];
  category?: string;
  attempts?: DagAttempt[];
}
export interface DagRecord {
  run: string;
  session_id: string;
  name?: string;
  goal?: string;
  nodes: DagNode[];
  repairs?: Record<string, string[][]>;
  cancelled_at?: number | null;
  defined_at?: number;
  updated_at?: number;
}

const OUTCOME_STATE: Record<string, NodeState> = {
  accepted: "done",
  failed: "failed",
  blocked: "blocked",
  parked: "parked",
  retry: "waiting",
};
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

export function fromDag(rec: DagRecord, bot: string, handoffs: Iterable<string> = []): AgentRun {
  const withHandoff = new Set(handoffs);
  const raw = rec.nodes.filter((n) => n && typeof n.id === "string");
  const ids = new Set(raw.map((n) => n.id));
  const cancelled = rec.cancelled_at !== undefined && rec.cancelled_at !== null;
  const nodes: RunNode[] = raw.map((n) => {
    const attempts = (n.attempts ?? []).filter((a) => a && typeof a === "object");
    const last = attempts[attempts.length - 1];
    let state: NodeState = !last ? "waiting" : (OUTCOME_STATE[last.outcome ?? ""] ?? "running");
    if (cancelled && (state === "running" || state === "parked" || state === "waiting")) state = "cancelled";
    const node: RunNode = {
      id: n.id,
      label: n.label || n.id,
      deps: (n.depends_on ?? []).filter((d) => ids.has(d)),
      layer: 0,
      state,
      attempts: [],
    };
    if (n.category) node.category = node.route = n.category;
    if (n.role) node.role = n.role;
    for (const a of attempts) {
      const item: RunAttempt = { n: Number.isInteger(a.n) ? a.n! : node.attempts.length + 1, outcome: a.outcome || "open" };
      if (a.reason) item.reason = a.reason;
      if (a.lane) item.lane = a.lane;
      if (num(a.handed_out_at) !== undefined) item.started = a.handed_out_at;
      if (num(a.settled_at) !== undefined) item.ended = a.settled_at;
      node.attempts.push(item);
    }
    const first = node.attempts[0];
    const end = node.attempts[node.attempts.length - 1];
    if (end?.lane) node.lane = end.lane;
    if (first?.started !== undefined) node.started = first.started;
    if ((state === "done" || state === "failed" || state === "blocked") && end?.ended !== undefined) node.ended = end.ended;
    if (withHandoff.has(n.id)) node.handoff = `${n.id}.md`;
    return node;
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const groups = rec.repairs ?? {};
  // each repair member points at the node it repairs (the latest group naming it wins)
  for (const [target, g] of Object.entries(groups)) {
    if (!byId.has(target) || !Array.isArray(g)) continue;
    for (const group of g) for (const m of Array.isArray(group) ? group : []) if (byId.has(m) && m !== target) byId.get(m)!.repairOf = target;
  }
  const layers = layerOf(nodes.map((n) => ({ id: n.id, deps: n.repairOf ? [...n.deps, n.repairOf] : n.deps })));
  for (const n of nodes) n.layer = layers[n.id];

  const superseded = new Set<string>();
  for (const g of Object.values(groups))
    for (const older of g.slice(0, -1)) for (const m of older) if (byId.get(m)?.state !== "done") superseded.add(m);
  // A failed node whose latest repair group all finished counts as settled, as OMH's own derivation says.
  const satisfied = (n: RunNode) => {
    if (n.state === "done") return true;
    const latest = groups[n.id]?.[groups[n.id].length - 1] ?? [];
    return (n.state === "failed" || n.state === "blocked") && latest.length > 0 && latest.every((m) => byId.get(m)?.state === "done");
  };
  const live = nodes.filter((n) => !superseded.has(n.id));
  let state: RunState;
  if (cancelled) state = "cancelled";
  else if (live.every(satisfied)) state = "done";
  else if (live.some((n) => n.state === "running" || n.state === "parked" || (n.state === "waiting" && n.deps.every((d) => satisfied(byId.get(d)!)))))
    state = "running";
  else state = "failed";

  const run: AgentRun = {
    id: `dag:${rec.session_id}/${rec.run}`,
    kind: "dag",
    owner: { type: "bot", id: bot },
    title: rec.name || rec.run,
    state,
    nodes,
    started: num(rec.defined_at) ?? 0,
    updated: num(rec.updated_at) ?? 0,
  };
  if (rec.goal) run.goal = rec.goal;
  if (state !== "running") {
    const ends = nodes.flatMap((n) => n.attempts.map((a) => a.ended).filter((e): e is number => e !== undefined));
    const ended = cancelled ? num(rec.cancelled_at) : ends.length ? Math.max(...ends) : undefined;
    if (ended !== undefined) run.ended = ended;
  }
  return run;
}

// ---- CLI agent runs (`runs.cli`): Claude Code Task/Agent subagents and Codex spawned sub-agents, read by the bridge
// from the CLIs' own session files. One session with sub-runs = one run, one sub-run = one node.

export type CliAgent = "claude" | "codex" | "pi" | "omp" | "grok";
/** `found`: the CLI's session folder exists; `no_adapter`: installed, but it keeps no sub-run record omher reads. */
export type CliAgentStatus = "found" | "not_installed" | "no_adapter";
export const CLI_AGENTS: CliAgent[] = ["claude", "codex", "pi", "omp", "grok"];
const CLI_NAME: Record<CliAgent, string> = { claude: "Claude", codex: "Codex", pi: "pi", omp: "omp", grok: "Grok" };

/** "Claude" / "Codex": the badge on a CLI run's row. */
export const cliName = (agent: CliAgent | undefined) => (agent ? CLI_NAME[agent] : "");
/** A run id from `runs.cli` (`claude:<session>`, `codex:<thread>`), which no bot owns. */
export const isCliRun = (id: string) => CLI_AGENTS.some((a) => id.startsWith(`${a}:`));

/** Running first, then the most recently updated. */
export function sortRuns<T extends { state: RunState; updated: number }>(runs: T[]): T[] {
  return [...runs].sort((a, b) => Number(b.state === "running") - Number(a.state === "running") || b.updated - a.updated);
}

/** A run's or node's length, the one formatter for every Runs surface: under a minute "38s", under an hour "14m",
 *  under a day "2h 5m", from a day "1d 10h". A zero second part is left out ("3h", "2d"). */
export function span(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  return h % 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : `${Math.floor(h / 24)}d`;
}

// ---- delegate adapter: Hermes `delegate_task` fan-outs (the bridge's `delegation_to_run` / `attach_delegations`) ----

/** One `cache/delegation/live/deleg_*` folder as the bridge reads it (manifest + task log head and final lines). */
export interface Delegation {
  id: string;
  started: number;
  ended?: number;
  model?: string;
  provider?: string;
  /** The `omh_delegate_route` record that prepared this dispatch, when one pairs. */
  route?: { category: string; origin: string; provider?: string; effort?: string; from?: string };
  tasks: {
    index: number;
    goal: string;
    status: string;
    started?: number;
    model?: string;
    summary?: string;
    error?: string;
    dag?: { run: string; node: string };
  }[];
}

const TASK_STATE: Record<string, NodeState> = {
  running: "running",
  completed: "done",
  failed: "failed",
  error: "failed",
  timeout: "failed",
  stalled: "failed",
  interrupted: "cancelled",
  cancelled: "cancelled",
};
const ROUTE_WHY: Record<string, string> = { head: "chain head", fallback: "fallback", exhausted_to_inherit: "chain exhausted" };

function taskFields(t: Delegation["tasks"][number], d: Delegation): Partial<RunNode> {
  const out: Partial<RunNode> = {};
  if (t.model) out.model = t.model;
  const route = d.route;
  const provider = d.provider || route?.provider;
  if (provider) out.provider = provider;
  if (route?.effort) out.effort = route.effort;
  if (route?.category) {
    out.route = route.category;
    const why = ROUTE_WHY[route.origin];
    if (why) out.routeWhy = why + (why === "fallback" && route.from ? ` from ${route.from}` : "");
  }
  if (t.summary || t.error) out.summary = t.summary || t.error;
  return out;
}

/** A fan-out with no dag marker: one layer, one node per task. */
export function fromDelegation(d: Delegation, bot: string): AgentRun {
  const nodes: RunNode[] = d.tasks.map((t) => {
    const state = TASK_STATE[t.status] ?? "running";
    const att: RunAttempt = { n: 1, outcome: t.status };
    if (t.started !== undefined || d.started) att.started = t.started ?? d.started;
    if (state !== "running" && d.ended !== undefined) att.ended = d.ended;
    if ((state === "failed" || state === "cancelled") && (t.error || t.summary)) att.reason = t.error || t.summary;
    const node: RunNode = { id: `task-${t.index}`, label: t.goal || `Task ${t.index + 1}`, deps: [], layer: 0, state, attempts: [att] };
    Object.assign(node, taskFields(t, d));
    if (att.started !== undefined) node.started = att.started;
    if (att.ended !== undefined) node.ended = att.ended;
    return node;
  });
  const states = nodes.map((n) => n.state);
  const state: RunState = states.includes("running")
    ? "running"
    : states.includes("failed")
      ? "failed"
      : states.includes("cancelled")
        ? "cancelled"
        : "done";
  const first = nodes[0]?.label ?? d.id;
  const run: AgentRun = {
    id: `delegate:${d.id}`,
    kind: "delegate",
    owner: { type: "bot", id: bot },
    title: first + (nodes.length > 1 ? ` +${nodes.length - 1}` : ""),
    state,
    nodes,
    started: d.started,
    updated: Math.max(d.started, d.ended ?? 0, ...nodes.map((n) => n.started ?? 0)),
  };
  if (state !== "running" && d.ended !== undefined) run.ended = d.ended;
  return run;
}

/** Name the agent CLI that ran each fanout node, from the run's own unit files ({node id: owner}). Mutates `run`. */
export function attachOwners(run: AgentRun, owners: Record<string, string>): AgentRun {
  for (const n of run.nodes) if (n.lane === "fanout" && owners[n.id]) n.executor = owners[n.id];
  return run;
}

export interface RouteRecord {
  written_at: number;
  session_id?: string;
  category?: string;
  alias?: string;
  wire_model?: string;
  provider?: string;
  reasoning_effort?: string;
  origin: string;
}

/** {category: model}: what each routing category resolved to in the bot's newest route record (oldest first in). */
export function routeTable(records: RouteRecord[], sessions: Set<string>): Record<string, NonNullable<RunNode["planned"]>> {
  const table: Record<string, NonNullable<RunNode["planned"]>> = {};
  for (const r of records) {
    if (r.origin === "cleared" || (r.session_id && !sessions.has(r.session_id))) continue;
    const model = r.wire_model || r.alias;
    if (!r.category || !model) continue;
    const row: NonNullable<RunNode["planned"]> = { model };
    if (r.provider) row.provider = r.provider;
    if (r.reasoning_effort) row.effort = r.reasoning_effort;
    table[r.category] = row;
  }
  return table;
}

/** `planned` = the route table's model, for a node with no reported model and no named executor. Mutates `run`. */
export function attachPlanned(run: AgentRun, table: Record<string, NonNullable<RunNode["planned"]>>): AgentRun {
  for (const n of run.nodes) if (!n.model && !n.executor && n.route && table[n.route]) n.planned = { ...table[n.route] };
  return run;
}

/** A failed node whose repairs all finished: OMH counts it as satisfied, so it reads as "repaired", not as an
 *  open failure. */
export function isRepaired(n: RunNode, nodes: RunNode[]): boolean {
  if (n.state !== "failed" && n.state !== "blocked") return false;
  const fixes = nodes.filter((m) => m.repairOf === n.id);
  return fixes.length > 0 && fixes.every((m) => m.state === "done");
}

/** What a node ran on (or goes to), for its logo and its meta line: the helper's model, else the agent CLI that took
 *  a fanout node, else the model its route resolves to, else the bot's own model. */
export function nodeModel(n: RunNode, bot?: { model: string; provider: string }): { model: string; provider?: string; source: "ran" | "executor" | "route" | "bot" } | null {
  if (n.model) return { model: n.model, provider: n.provider, source: "ran" };
  if (n.executor) return { model: n.executor, source: "executor" };
  if (n.planned) return { model: n.planned.model, provider: n.planned.provider, source: "route" };
  if (bot?.model) return { model: bot.model, provider: bot.provider, source: "bot" };
  return null;
}

/** Fill a dag run's nodes with what their helpers ran on. A task belongs to a node through the
 *  `[dag:<run>/<node>]` marker in its goal; attempt k pairs with the first unused matching task that started at
 *  or after the attempt was handed out. Fields the dag already has win. Mutates and returns `run`. */
export function attachDelegations(run: AgentRun, delegs: Delegation[]): AgentRun {
  const name = run.id.split("/").pop();
  const tasks = delegs
    .flatMap((d) => d.tasks.filter((t) => t.dag?.run === name && d.started >= run.started - 60).map((t) => ({ t, d })))
    .sort((a, b) => (a.t.started ?? a.d.started) - (b.t.started ?? b.d.started));
  for (const node of run.nodes) {
    const mine = tasks.filter(({ t }) => t.dag!.node === node.id);
    if (!mine.length) continue;
    const used = new Set<number>();
    let last: (typeof mine)[number] | null = null;
    for (const att of node.attempts) {
      const at = att.started;
      const pick = mine.findIndex(({ t, d }, i) => !used.has(i) && (at === undefined || (t.started ?? d.started) >= at - 5));
      if (pick < 0) continue;
      used.add(pick);
      if (mine[pick].t.model) att.model = mine[pick].t.model;
      last = mine[pick];
    }
    if (!last) continue;
    const f = taskFields(last.t, last.d) as Record<string, unknown>;
    const target = node as unknown as Record<string, unknown>;
    for (const [k, v] of Object.entries(f)) if (target[k] === undefined) target[k] = v;
  }
  return run;
}
