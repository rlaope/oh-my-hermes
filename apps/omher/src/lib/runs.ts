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
  /** Why the node went to its model, when a router recorded it. */
  route?: string;
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
  /** failed + blocked */
  failed: number;
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
  const c = { nodes: run.nodes.length, done: 0, running: 0, failed: 0 };
  for (const n of run.nodes) {
    if (n.state === "done") c.done++;
    else if (n.state === "running") c.running++;
    else if (n.state === "failed" || n.state === "blocked") c.failed++;
  }
  return c;
}

/** "7 nodes · 3 done · 1 running · 1 failed" (zero parts left out). */
export function summary(run: Pick<AgentRun, "nodes"> | { counts: RunCounts }): string {
  const c = "counts" in run ? run.counts : countsOf(run);
  const parts = [`${c.nodes} node${c.nodes === 1 ? "" : "s"}`];
  if (c.done) parts.push(`${c.done} done`);
  if (c.running) parts.push(`${c.running} running`);
  if (c.failed) parts.push(`${c.failed} failed`);
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
    if (n.category) node.category = n.category;
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
  const layers = layerOf(nodes);
  for (const n of nodes) n.layer = layers[n.id];

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const groups = rec.repairs ?? {};
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

/** Running first, then the most recently updated. */
export function sortRuns<T extends { state: RunState; updated: number }>(runs: T[]): T[] {
  return [...runs].sort((a, b) => Number(b.state === "running") - Number(a.state === "running") || b.updated - a.updated);
}

/** "38s", "14m", "2h 5m", "3d": a run's or node's length, coarse on purpose. */
export function span(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  return `${Math.floor(h / 24)}d`;
}
